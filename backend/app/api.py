from __future__ import annotations

import argparse
import json
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .coach import (
    BudgetChangeSuggestionRequest,
    CoachService,
    SafeToSpendCoachRequest,
    build_coach_service_from_env,
    coach_response_to_dict,
)
from .db import (
    BudgetRepository,
    account_to_dict,
    notification_event_to_dict,
    safe_to_spend_to_dict,
    summary_to_dict,
    transaction_detail_to_dict,
)
from .plaid import (
    PlaidConnectionService,
    build_plaid_service_from_env,
    link_token_to_dict,
    plaid_connection_result_to_dict,
    plaid_sync_outcome_to_dict,
)


class UnauthorizedError(Exception):
    pass


class ApiHandler(BaseHTTPRequestHandler):
    repository: BudgetRepository
    plaid_service: PlaidConnectionService
    coach_service: CoachService

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/health":
                self.send_json({"ok": True})
                return
            if parsed.path == "/budget-months":
                auth = self.require_auth()
                self.send_json({"budget_months": self.repository.list_budget_months(auth["household_id"])})
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/summary"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                query = parse_qs(parsed.query)
                today = parse_date(query.get("today", [date.today().isoformat()])[0])
                summary = self.repository.get_summary(budget_month_id, today)
                self.send_json(summary_to_dict(summary))
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/budget-detail"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                query = parse_qs(parsed.query)
                today = parse_date(query.get("today", [date.today().isoformat()])[0])
                self.send_json(self.repository.get_budget_detail(budget_month_id, today))
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/accounts"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                accounts = self.repository.list_accounts(budget_month_id)
                self.send_json({"accounts": [account_to_dict(account) for account in accounts]})
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/transactions"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                transactions = self.repository.list_budget_transactions(budget_month_id)
                self.send_json({"transactions": [transaction_detail_to_dict(item) for item in transactions]})
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/transaction-review-queue"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                transactions = self.repository.list_transaction_review_queue(budget_month_id)
                self.send_json({"transactions": [transaction_detail_to_dict(item) for item in transactions]})
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/notifications"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                query = parse_qs(parsed.query)
                events = self.repository.list_notification_events(
                    budget_month_id=budget_month_id,
                    user_id=auth["user_id"],
                    event_type=optional_query_value(query, "event_type"),
                    severity=optional_query_value(query, "severity"),
                )
                self.send_json({"notifications": [notification_event_to_dict(event) for event in events]})
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/notifications/unread-count"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                count = self.repository.unread_notification_count(
                    budget_month_id=budget_month_id,
                    user_id=auth["user_id"],
                )
                self.send_json({"unread_count": count})
                return
            if parsed.path.startswith("/households/") and parsed.path.endswith("/notifications"):
                auth = self.require_auth()
                household_id = int(parsed.path.split("/")[2])
                require_same_household(household_id, auth)
                query = parse_qs(parsed.query)
                events = self.repository.list_notification_events(
                    household_id=household_id,
                    user_id=auth["user_id"],
                    event_type=optional_query_value(query, "event_type"),
                    severity=optional_query_value(query, "severity"),
                )
                self.send_json({"notifications": [notification_event_to_dict(event) for event in events]})
                return
            if parsed.path.startswith("/households/") and parsed.path.endswith("/notifications/unread-count"):
                auth = self.require_auth()
                household_id = int(parsed.path.split("/")[2])
                require_same_household(household_id, auth)
                count = self.repository.unread_notification_count(
                    household_id=household_id,
                    user_id=auth["user_id"],
                )
                self.send_json({"unread_count": count})
                return
            if parsed.path.startswith("/transactions/"):
                auth = self.require_auth()
                transaction_id = int(parsed.path.split("/")[2])
                self.repository.require_transaction_access(transaction_id, auth["household_id"])
                detail = self.repository.get_transaction_detail(transaction_id)
                self.send_json(transaction_detail_to_dict(detail))
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Route not found")
        except UnauthorizedError as exc:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, str(exc))
        except PermissionError as exc:
            self.send_error_json(HTTPStatus.FORBIDDEN, str(exc))
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/auth/login":
                auth_payload = self.repository.authenticate_local_user(
                    login=str(payload.get("username") or payload.get("email") or ""),
                    password=str(payload.get("password") or ""),
                )
                if auth_payload is None:
                    raise UnauthorizedError("Invalid credentials")
                self.send_json(auth_payload)
                return
            if parsed.path == "/households":
                self.require_auth()
                raise PermissionError("Household creation is not available through the API")
                return
            if parsed.path == "/budget-months":
                auth = self.require_auth()
                require_same_household(int(payload["household_id"]), auth)
                budget_month_id = self.repository.create_budget_month(
                    household_id=int(payload["household_id"]),
                    month=payload["month"],
                    included_account_balance_cents=int(payload.get("included_account_balance_cents", 0)),
                    low_cushion_daily_cents=int(payload.get("low_cushion_daily_cents", 5_000)),
                    copy_from_budget_month_id=optional_int(payload, "copy_from_budget_month_id"),
                )
                self.send_json({"id": budget_month_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/income":
                auth = self.require_auth()
                self.repository.require_budget_month_access(int(payload["budget_month_id"]), auth["household_id"])
                income_id = self.repository.add_income(
                    budget_month_id=int(payload["budget_month_id"]),
                    name=payload["name"],
                    kind=payload["kind"],
                    planned_cents=int(payload.get("planned_cents", 0)),
                    received_cents=int(payload.get("received_cents", 0)),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"id": income_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/budget-groups":
                auth = self.require_auth()
                self.repository.require_budget_month_access(int(payload["budget_month_id"]), auth["household_id"])
                group_id = self.repository.add_budget_group(
                    budget_month_id=int(payload["budget_month_id"]),
                    name=payload["name"],
                    display_order=int(payload.get("display_order", 0)),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"id": group_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/categories":
                auth = self.require_auth()
                self.repository.require_budget_group_access(int(payload["budget_group_id"]), auth["household_id"])
                category_id = self.repository.add_category(
                    budget_group_id=int(payload["budget_group_id"]),
                    name=payload["name"],
                    planned_cents=int(payload.get("planned_cents", 0)),
                    display_order=int(payload.get("display_order", 0)),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"id": category_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/spending":
                auth = self.require_auth()
                self.repository.require_category_access(int(payload["category_id"]), auth["household_id"])
                spending_id = self.repository.record_spending(
                    category_id=int(payload["category_id"]),
                    amount_cents=int(payload["amount_cents"]),
                    occurred_on=parse_date(payload["occurred_on"]),
                    note=payload.get("note"),
                )
                self.send_json({"id": spending_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/expected-bills":
                auth = self.require_auth()
                self.repository.require_budget_month_access(int(payload["budget_month_id"]), auth["household_id"])
                bill_id = self.repository.add_expected_bill(
                    budget_month_id=int(payload["budget_month_id"]),
                    name=payload["name"],
                    amount_cents=int(payload["amount_cents"]),
                    due_on=parse_date(payload["due_on"]),
                    paid=bool(payload.get("paid", False)),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"id": bill_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/paydays":
                auth = self.require_auth()
                require_same_household(int(payload["household_id"]), auth)
                payday_id = self.repository.add_payday(
                    household_id=int(payload["household_id"]),
                    payday_date=parse_date(payload["payday_date"]),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"id": payday_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/safe-to-spend":
                auth = self.require_auth()
                budget_month_id = int(payload["budget_month_id"])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                self.repository.require_category_access(int(payload["category_id"]), auth["household_id"])
                result = self.repository.safe_to_spend(
                    budget_month_id=budget_month_id,
                    category_id=int(payload["category_id"]),
                    purchase_amount_cents=int(payload["purchase_amount_cents"]),
                    today=parse_date(payload.get("today", date.today().isoformat())),
                    urgency=payload.get("urgency", "planned_want"),
                    actor_user_id=auth["user_id"],
                )
                self.send_json(safe_to_spend_to_dict(result))
                return
            if parsed.path == "/coach/safe-to-spend":
                auth = self.require_auth()
                amount_cents = require_int(payload, "amount_cents", fallback_key="purchase_amount_cents")
                category_id = require_int(payload, "category_id")
                budget_month_id = require_int(payload, "budget_month_id")
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                self.repository.require_category_access(category_id, auth["household_id"])
                result = self.repository.safe_to_spend(
                    budget_month_id=budget_month_id,
                    category_id=category_id,
                    purchase_amount_cents=amount_cents,
                    today=parse_date(payload.get("today", date.today().isoformat())),
                    urgency=payload.get("urgency", "planned_want"),
                    actor_user_id=auth["user_id"],
                )
                coach_response = self.coach_service.explain_safe_to_spend(
                    result=result,
                    request=SafeToSpendCoachRequest(
                        amount_cents=amount_cents,
                        category_id=category_id,
                        note=payload.get("note"),
                        purpose=payload.get("purpose"),
                    ),
                )
                self.send_json(
                    {
                        "safe_to_spend": safe_to_spend_to_dict(result),
                        "coach": coach_response_to_dict(coach_response),
                    }
                )
                return
            if parsed.path == "/coach/budget-change-suggestion":
                auth = self.require_auth()
                budget_month_id = require_int(payload, "budget_month_id")
                amount_cents = require_int(payload, "amount_cents")
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                from_category_id = optional_int(payload, "from_category_id")
                to_category_id = optional_int(payload, "to_category_id")
                if from_category_id is not None:
                    self.repository.require_category_access(from_category_id, auth["household_id"])
                if to_category_id is not None:
                    self.repository.require_category_access(to_category_id, auth["household_id"])
                summary = self.repository.get_summary(
                    budget_month_id,
                    parse_date(payload.get("today", date.today().isoformat())),
                )
                coach_response = self.coach_service.suggest_budget_change(
                    summary=summary,
                    request=BudgetChangeSuggestionRequest(
                        budget_month_id=budget_month_id,
                        amount_cents=amount_cents,
                        from_category_id=from_category_id,
                        to_category_id=to_category_id,
                        note=payload.get("note"),
                        purpose=payload.get("purpose"),
                    ),
                )
                coach_payload = coach_response_to_dict(coach_response)
                self.repository.create_notification_event(
                    household_id=self.repository.household_id_for_budget_month(budget_month_id),
                    budget_month_id=budget_month_id,
                    event_type="coach_suggestion_generated",
                    actor_user_id=auth["user_id"],
                    affected_entity_type="coach_suggestion",
                    affected_entity_id=None,
                    title="Coach suggestion generated",
                    message=coach_response.summary,
                    severity="caution" if coach_response.requires_spouse_discussion else "info",
                    metadata={
                        "amount_cents": amount_cents,
                        "from_category_id": from_category_id,
                        "to_category_id": to_category_id,
                        "warning_level": coach_response.warning_level,
                        "has_proposed_budget_change": coach_response.proposed_budget_change is not None,
                    },
                )
                self.send_json({"coach": coach_payload})
                return
            if parsed.path == "/plaid/link-token":
                auth = self.require_auth()
                link_token = self.plaid_service.create_link_token(
                    household_id=auth["household_id"],
                )
                self.send_json(link_token_to_dict(link_token), status=HTTPStatus.CREATED)
                return
            if parsed.path == "/plaid/exchange-public-token":
                auth = self.require_auth()
                budget_month_id = int(payload["budget_month_id"])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                result = self.plaid_service.exchange_public_token(
                    household_id=auth["household_id"],
                    budget_month_id=budget_month_id,
                    public_token=payload["public_token"],
                )
                self.send_json(plaid_connection_result_to_dict(result), status=HTTPStatus.CREATED)
                return
            if parsed.path == "/plaid/sync":
                auth = self.require_auth()
                sync_type = payload["sync_type"]
                plaid_item_id = int(payload["plaid_item_id"])
                self.repository.require_plaid_item_access(plaid_item_id, auth["household_id"])
                if sync_type == "balance":
                    outcome = self.plaid_service.sync_balances(plaid_item_id)
                elif sync_type == "transaction":
                    outcome = self.plaid_service.sync_transactions(plaid_item_id)
                else:
                    raise ValueError("sync_type must be 'balance' or 'transaction'")
                self.send_json(plaid_sync_outcome_to_dict(outcome))
                return
            if parsed.path == "/merchant-category-rules":
                auth = self.require_auth()
                category_id = int(payload["category_id"])
                self.repository.require_category_access(category_id, auth["household_id"])
                rule_id = self.repository.create_merchant_rule(
                    household_id=auth["household_id"],
                    merchant_match_text=payload["merchant_match_text"],
                    category_id=category_id,
                    priority=int(payload.get("priority", 100)),
                )
                self.send_json({"id": rule_id}, status=HTTPStatus.CREATED)
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Route not found")
        except UnauthorizedError as exc:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, str(exc))
        except PermissionError as exc:
            self.send_error_json(HTTPStatus.FORBIDDEN, str(exc))
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/activate"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.set_active_budget_month(
                    household_id=auth["household_id"],
                    budget_month_id=budget_month_id,
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.count("/") == 2:
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                self.repository.update_budget_month(
                    budget_month_id=budget_month_id,
                    month=payload.get("month"),
                    included_account_balance_cents=optional_int(payload, "included_account_balance_cents"),
                    low_cushion_daily_cents=optional_int(payload, "low_cushion_daily_cents"),
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/income/"):
                auth = self.require_auth()
                income_id = int(parsed.path.split("/")[2])
                self.repository.require_income_access(income_id, auth["household_id"])
                self.repository.update_income(
                    income_id=income_id,
                    name=payload.get("name"),
                    kind=payload.get("kind"),
                    planned_cents=optional_int(payload, "planned_cents"),
                    received_cents=optional_int(payload, "received_cents"),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/budget-groups/"):
                auth = self.require_auth()
                budget_group_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_group_access(budget_group_id, auth["household_id"])
                self.repository.update_budget_group(
                    budget_group_id=budget_group_id,
                    name=payload.get("name"),
                    display_order=optional_int(payload, "display_order"),
                    archived=payload.get("archived"),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/categories/"):
                auth = self.require_auth()
                category_id = int(parsed.path.split("/")[2])
                self.repository.require_category_access(category_id, auth["household_id"])
                if payload.get("budget_group_id") is not None:
                    self.repository.require_budget_group_access(int(payload["budget_group_id"]), auth["household_id"])
                self.repository.update_category(
                    category_id=category_id,
                    name=payload.get("name"),
                    budget_group_id=optional_int(payload, "budget_group_id"),
                    planned_cents=optional_int(payload, "planned_cents"),
                    display_order=optional_int(payload, "display_order"),
                    archived=payload.get("archived"),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/expected-bills/"):
                auth = self.require_auth()
                bill_id = int(parsed.path.split("/")[2])
                self.repository.require_bill_access(bill_id, auth["household_id"])
                self.repository.update_expected_bill(
                    bill_id=bill_id,
                    name=payload.get("name"),
                    amount_cents=optional_int(payload, "amount_cents"),
                    due_on=parse_date(payload["due_on"]) if payload.get("due_on") is not None else None,
                    paid=payload.get("paid"),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/paydays/"):
                auth = self.require_auth()
                payday_id = int(parsed.path.split("/")[2])
                self.repository.require_payday_access(payday_id, auth["household_id"])
                self.repository.update_payday(
                    payday_id=payday_id,
                    payday_date=parse_date(payload["payday_date"]),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/account-balance"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                self.repository.update_account_balance(
                    budget_month_id,
                    int(payload["included_account_balance_cents"]),
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/accounts/"):
                auth = self.require_auth()
                account_id = int(parsed.path.split("/")[2])
                self.repository.require_account_access(account_id, auth["household_id"])
                if "included_in_cash_reality" in payload:
                    self.repository.set_account_included(
                        account_id=account_id,
                        included_in_cash_reality=bool(payload["included_in_cash_reality"]),
                    )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/transactions/") and parsed.path.endswith("/review"):
                auth = self.require_auth()
                transaction_id = int(parsed.path.split("/")[2])
                self.repository.require_transaction_access(transaction_id, auth["household_id"])
                self.repository.mark_transaction_reviewed(
                    transaction_id,
                    reviewed=bool(payload.get("reviewed", True)),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/transactions/") and parsed.path.endswith("/category"):
                auth = self.require_auth()
                transaction_id = int(parsed.path.split("/")[2])
                self.repository.require_transaction_access(transaction_id, auth["household_id"])
                if payload.get("category_id") is None:
                    self.repository.remove_transaction_category(
                        transaction_id,
                        reviewed=bool(payload.get("reviewed", False)),
                        actor_user_id=auth["user_id"],
                    )
                else:
                    self.repository.require_category_access(int(payload["category_id"]), auth["household_id"])
                    self.repository.assign_transaction_category(
                        transaction_id=transaction_id,
                        category_id=int(payload["category_id"]),
                        source=payload.get("source", "manual"),
                        reviewed=bool(payload.get("reviewed", True)),
                        actor_user_id=auth["user_id"],
                    )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/transactions/") and parsed.path.endswith("/split"):
                auth = self.require_auth()
                transaction_id = int(parsed.path.split("/")[2])
                self.repository.require_transaction_access(transaction_id, auth["household_id"])
                for split in payload["splits"]:
                    self.repository.require_category_access(int(split["category_id"]), auth["household_id"])
                self.repository.split_transaction(
                    transaction_id=transaction_id,
                    splits=payload["splits"],
                    reviewed=bool(payload.get("reviewed", True)),
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/transactions/") and parsed.path.endswith("/ignore"):
                auth = self.require_auth()
                transaction_id = int(parsed.path.split("/")[2])
                self.repository.require_transaction_access(transaction_id, auth["household_id"])
                self.repository.set_transaction_ignored(
                    transaction_id=transaction_id,
                    ignored=bool(payload.get("ignored", True)),
                    reason=payload.get("reason"),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/notifications/") and parsed.path.endswith("/read"):
                auth = self.require_auth()
                notification_id = int(parsed.path.split("/")[2])
                self.repository.require_notification_access(notification_id, auth["household_id"])
                self.repository.mark_notification_read(
                    notification_id,
                    user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/households/") and parsed.path.endswith("/notifications/read-all"):
                auth = self.require_auth()
                household_id = int(parsed.path.split("/")[2])
                require_same_household(household_id, auth)
                self.repository.mark_all_notifications_read(
                    household_id=household_id,
                    budget_month_id=optional_int(payload, "budget_month_id"),
                    user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/notifications/read-all"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                self.repository.mark_all_notifications_read(
                    budget_month_id=budget_month_id,
                    user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Route not found")
        except UnauthorizedError as exc:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, str(exc))
        except PermissionError as exc:
            self.send_error_json(HTTPStatus.FORBIDDEN, str(exc))
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/income/"):
                auth = self.require_auth()
                income_id = int(parsed.path.split("/")[2])
                self.repository.require_income_access(income_id, auth["household_id"])
                self.repository.remove_income(income_id=income_id, actor_user_id=auth["user_id"])
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/expected-bills/"):
                auth = self.require_auth()
                bill_id = int(parsed.path.split("/")[2])
                self.repository.require_bill_access(bill_id, auth["household_id"])
                self.repository.remove_expected_bill(bill_id=bill_id, actor_user_id=auth["user_id"])
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/paydays/"):
                auth = self.require_auth()
                payday_id = int(parsed.path.split("/")[2])
                self.repository.require_payday_access(payday_id, auth["household_id"])
                self.repository.remove_payday(payday_id=payday_id, actor_user_id=auth["user_id"])
                self.send_json({"ok": True})
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Route not found")
        except UnauthorizedError as exc:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, str(exc))
        except PermissionError as exc:
            self.send_error_json(HTTPStatus.FORBIDDEN, str(exc))
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def require_auth(self) -> dict[str, Any]:
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.casefold() != "bearer" or not token.strip():
            raise UnauthorizedError("Authentication required")
        context = self.repository.auth_context_for_token(token.strip())
        if context is None:
            raise UnauthorizedError("Authentication required")
        return context

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status=status)

    def log_message(self, format: str, *args: object) -> None:
        return


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def require_int(payload: dict[str, Any], key: str, fallback_key: str | None = None) -> int:
    if key not in payload and (fallback_key is None or fallback_key not in payload):
        if fallback_key is None:
            raise ValueError(f"{key} is required")
        raise ValueError(f"{key} or {fallback_key} is required")
    value = payload.get(key, payload.get(fallback_key))
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def optional_int(payload: dict[str, Any], key: str) -> int | None:
    if key not in payload or payload[key] is None:
        return None
    try:
        return int(payload[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def require_user_id(payload: dict[str, Any]) -> int:
    for key in ("user_id", "spouse_id", "actor_user_id"):
        if key in payload and payload[key] is not None:
            return require_int(payload, key)
    raise ValueError("user_id or spouse_id is required")


def require_same_household(household_id: int, auth: dict[str, Any]) -> None:
    if household_id != int(auth["household_id"]):
        raise PermissionError("Household is not available to this user")


def optional_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def require_query_int(query: dict[str, list[str]], key: str, fallback_key: str | None = None) -> int:
    value = optional_query_int(query, key, fallback_key=fallback_key)
    if value is None:
        if fallback_key is None:
            raise ValueError(f"{key} is required")
        raise ValueError(f"{key} or {fallback_key} is required")
    return value


def optional_query_int(query: dict[str, list[str]], key: str, fallback_key: str | None = None) -> int | None:
    value = optional_query_value(query, key)
    if value is None and fallback_key is not None:
        value = optional_query_value(query, fallback_key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc


def build_server(db_path: Path, host: str, port: int) -> ThreadingHTTPServer:
    repository = BudgetRepository(db_path)
    repository.initialize()
    ApiHandler.repository = repository
    ApiHandler.plaid_service = build_plaid_service_from_env(repository)
    ApiHandler.coach_service = build_coach_service_from_env()
    return ThreadingHTTPServer((host, port), ApiHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Family Finance staged MVP API")
    parser.add_argument("--db", default="work/family_finance.sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    server = build_server(Path(args.db), args.host, args.port)
    print(f"Serving on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
