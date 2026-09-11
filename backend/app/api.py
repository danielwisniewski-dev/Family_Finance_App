from __future__ import annotations

import argparse
import json
import re
import sqlite3
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
    merchant_rule_to_dict,
    notification_event_to_dict,
    safe_to_spend_to_dict,
    summary_to_dict,
    transaction_detail_to_dict,
)
from .plaid import (
    PlaidIntegrationError,
    PlaidConnectionService,
    build_plaid_service_from_env,
    link_token_to_dict,
    plaid_connection_result_to_dict,
    plaid_sync_outcome_to_dict,
    sanitize_plaid_error,
)


class UnauthorizedError(Exception):
    pass


class RequestBodyTooLargeError(Exception):
    pass


MAX_REQUEST_BODY_BYTES = 256 * 1024
REQUEST_TIMEOUT_SECONDS = 15


ERROR_CODES = {
    HTTPStatus.BAD_REQUEST: "validation_error",
    HTTPStatus.UNAUTHORIZED: "unauthorized",
    HTTPStatus.FORBIDDEN: "forbidden",
    HTTPStatus.NOT_FOUND: "not_found",
    HTTPStatus.CONFLICT: "conflict",
    HTTPStatus.REQUEST_TIMEOUT: "request_timeout",
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE: "request_too_large",
    HTTPStatus.SERVICE_UNAVAILABLE: "service_unavailable",
    HTTPStatus.INTERNAL_SERVER_ERROR: "backend_error",
}


class ApiHandler(BaseHTTPRequestHandler):
    repository: BudgetRepository
    plaid_service: PlaidConnectionService
    coach_service: CoachService

    def setup(self) -> None:
        self.request.settimeout(REQUEST_TIMEOUT_SECONDS)
        super().setup()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/health":
                self.send_json({"ok": True})
                return
            if parsed.path == "/setup/status":
                self.send_json(self.repository.setup_status(self.optional_auth()))
                return
            if parsed.path == "/settings/account":
                auth = self.require_auth()
                self.send_json(self.repository.account_settings_summary(auth["user_id"]))
                return
            if parsed.path == "/app/diagnostics":
                auth = self.require_auth()
                self.send_json(self.repository.app_diagnostics(auth))
                return
            if parsed.path == "/budget-months":
                auth = self.require_auth()
                self.send_json({"budget_months": self.repository.list_budget_months(auth["household_id"])})
                return
            if resource_path(parsed.path, "budget-months", "summary"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                query = parse_qs(parsed.query)
                today = parse_date(query.get("today", [date.today().isoformat()])[0])
                summary = self.repository.get_summary(budget_month_id, today)
                self.send_json(summary_to_dict(summary))
                return
            if resource_path(parsed.path, "budget-months", "budget-detail"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                query = parse_qs(parsed.query)
                today = parse_date(query.get("today", [date.today().isoformat()])[0])
                self.send_json(self.repository.get_budget_detail(budget_month_id, today))
                return
            if resource_path(parsed.path, "budget-months", "accounts"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                accounts = self.repository.list_accounts(budget_month_id)
                self.send_json({"accounts": [account_to_dict(account) for account in accounts]})
                return
            if resource_path(parsed.path, "budget-months", "transactions"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                transactions = self.repository.list_budget_transactions(budget_month_id)
                self.send_json({"transactions": [transaction_detail_to_dict(item) for item in transactions]})
                return
            if resource_path(parsed.path, "budget-months", "transaction-review-queue"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                query = parse_qs(parsed.query)
                account_id = optional_query_int(query, "account_id")
                if account_id is not None:
                    self.repository.require_account_access(account_id, auth["household_id"])
                transactions = self.repository.list_review_transactions(
                    budget_month_id,
                    status=optional_query_value(query, "status") or "needs_review",
                    start_date=parse_date(optional_query_value(query, "start_date")) if optional_query_value(query, "start_date") else None,
                    end_date=parse_date(optional_query_value(query, "end_date")) if optional_query_value(query, "end_date") else None,
                    account_id=account_id,
                )
                self.send_json({"transactions": [transaction_detail_to_dict(item) for item in transactions]})
                return
            if parsed.path == "/merchant-category-rules":
                auth = self.require_auth()
                query = parse_qs(parsed.query)
                include_inactive = (optional_query_value(query, "include_inactive") or "false").casefold() == "true"
                rules = self.repository.list_merchant_rules(
                    auth["household_id"],
                    include_inactive=include_inactive,
                )
                self.send_json({"rules": [merchant_rule_to_dict(rule) for rule in rules]})
                return
            if resource_path(parsed.path, "budget-months", "notifications"):
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
            if resource_path(parsed.path, "budget-months", "notifications/unread-count"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                count = self.repository.unread_notification_count(
                    budget_month_id=budget_month_id,
                    user_id=auth["user_id"],
                )
                self.send_json({"unread_count": count})
                return
            if resource_path(parsed.path, "households", "notifications"):
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
            if resource_path(parsed.path, "households", "notifications/unread-count"):
                auth = self.require_auth()
                household_id = int(parsed.path.split("/")[2])
                require_same_household(household_id, auth)
                count = self.repository.unread_notification_count(
                    household_id=household_id,
                    user_id=auth["user_id"],
                )
                self.send_json({"unread_count": count})
                return
            if resource_path(parsed.path, "transactions"):
                auth = self.require_auth()
                transaction_id = int(parsed.path.split("/")[2])
                self.repository.require_transaction_access(transaction_id, auth["household_id"])
                detail = self.repository.get_transaction_detail(transaction_id)
                self.send_json(transaction_detail_to_dict(detail))
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Route not found")
        except Exception as exc:
            self.send_exception(exc)

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
            if parsed.path == "/setup/initialize":
                result = self.repository.initialize_private_household(
                    household_name=str(payload.get("household_name") or payload.get("name") or ""),
                    users=payload.get("users") or [],
                )
                self.send_json(result, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/households":
                self.require_auth()
                raise PermissionError("Household creation is not available through the API")
                return
            if parsed.path == "/starter-budget/current-month":
                auth = self.require_auth()
                result = self.repository.create_starter_budget_for_current_month(
                    household_id=auth["household_id"],
                    actor_user_id=auth["user_id"],
                    today=parse_date(payload.get("today", date.today().isoformat())),
                    next_payday=parse_date(payload["next_payday"]) if payload.get("next_payday") else None,
                )
                self.send_json(result, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/budget-months":
                auth = self.require_auth()
                require_same_household(require_int(payload, "household_id"), auth)
                budget_month_id = self.repository.create_budget_month(
                    household_id=require_int(payload, "household_id"),
                    month=payload["month"],
                    included_account_balance_cents=require_int(payload, "included_account_balance_cents", default=0),
                    low_cushion_daily_cents=require_int(payload, "low_cushion_daily_cents", default=5_000),
                    copy_from_budget_month_id=optional_int(payload, "copy_from_budget_month_id"),
                )
                self.send_json({"id": budget_month_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/income":
                auth = self.require_auth()
                self.repository.require_budget_month_access(require_int(payload, "budget_month_id"), auth["household_id"])
                income_id = self.repository.add_income(
                    budget_month_id=require_int(payload, "budget_month_id"),
                    name=payload["name"],
                    kind=payload["kind"],
                    planned_cents=require_int(payload, "planned_cents", default=0),
                    received_cents=require_int(payload, "received_cents", default=0),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"id": income_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/budget-groups":
                auth = self.require_auth()
                self.repository.require_budget_month_access(require_int(payload, "budget_month_id"), auth["household_id"])
                group_id = self.repository.add_budget_group(
                    budget_month_id=require_int(payload, "budget_month_id"),
                    name=payload["name"],
                    display_order=require_int(payload, "display_order", default=0),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"id": group_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/categories":
                auth = self.require_auth()
                self.repository.require_budget_group_access(require_int(payload, "budget_group_id"), auth["household_id"])
                category_id = self.repository.add_category(
                    budget_group_id=require_int(payload, "budget_group_id"),
                    name=payload["name"],
                    planned_cents=require_int(payload, "planned_cents", default=0),
                    display_order=require_int(payload, "display_order", default=0),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"id": category_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/spending":
                auth = self.require_auth()
                self.repository.require_category_access(require_int(payload, "category_id"), auth["household_id"])
                spending_id = self.repository.record_spending(
                    category_id=require_int(payload, "category_id"),
                    amount_cents=require_int(payload, "amount_cents"),
                    occurred_on=parse_date(payload["occurred_on"]),
                    note=payload.get("note"),
                )
                self.send_json({"id": spending_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/expected-bills":
                auth = self.require_auth()
                self.repository.require_budget_month_access(require_int(payload, "budget_month_id"), auth["household_id"])
                bill_id = self.repository.add_expected_bill(
                    budget_month_id=require_int(payload, "budget_month_id"),
                    name=payload["name"],
                    amount_cents=require_int(payload, "amount_cents"),
                    due_on=parse_date(payload["due_on"]),
                    paid=boolean_field(payload, "paid", False),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"id": bill_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/paydays":
                auth = self.require_auth()
                require_same_household(require_int(payload, "household_id"), auth)
                payday_id = self.repository.add_payday(
                    household_id=require_int(payload, "household_id"),
                    payday_date=parse_date(payload["payday_date"]),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"id": payday_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/safe-to-spend":
                auth = self.require_auth()
                budget_month_id = require_int(payload, "budget_month_id")
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                self.repository.require_category_access(require_int(payload, "category_id"), auth["household_id"])
                result = self.repository.safe_to_spend(
                    budget_month_id=budget_month_id,
                    category_id=require_int(payload, "category_id"),
                    purchase_amount_cents=require_int(payload, "purchase_amount_cents"),
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
                budget_month_id = require_int(payload, "budget_month_id")
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
                plaid_item_id = require_int(payload, "plaid_item_id")
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
                category_id = require_int(payload, "category_id")
                self.repository.require_category_access(category_id, auth["household_id"])
                merchant_match_text = payload.get("merchant_match_text")
                transaction_id = optional_int(payload, "transaction_id")
                if transaction_id is not None:
                    self.repository.require_transaction_access(transaction_id, auth["household_id"])
                    detail = self.repository.get_transaction_detail(transaction_id)
                    if merchant_match_text is None:
                        merchant_match_text = detail.transaction.merchant_name or detail.transaction.name
                rule_id = self.repository.create_merchant_rule(
                    household_id=auth["household_id"],
                    merchant_match_text=str(merchant_match_text or ""),
                    category_id=category_id,
                    priority=require_int(payload, "priority", default=100),
                    actor_user_id=auth["user_id"],
                    apply_to_existing_unreviewed=boolean_field(payload, "apply_to_existing_unreviewed", False),
                )
                self.send_json({"id": rule_id}, status=HTTPStatus.CREATED)
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Route not found")
        except Exception as exc:
            self.send_exception(exc)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/settings/display-name":
                auth = self.require_auth()
                user = self.repository.update_user_display_name(
                    user_id=auth["user_id"],
                    display_name=str(payload.get("display_name") or payload.get("name") or ""),
                )
                self.send_json({"user": user})
                return
            if parsed.path == "/settings/password":
                auth = self.require_auth()
                self.repository.change_user_password(
                    user_id=auth["user_id"],
                    current_password=str(payload.get("current_password") or ""),
                    new_password=str(payload.get("new_password") or ""),
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "budget-months", "activate"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.set_active_budget_month(
                    household_id=auth["household_id"],
                    budget_month_id=budget_month_id,
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "budget-months"):
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
            if resource_path(parsed.path, "income"):
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
            if resource_path(parsed.path, "budget-groups"):
                auth = self.require_auth()
                budget_group_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_group_access(budget_group_id, auth["household_id"])
                self.repository.update_budget_group(
                    budget_group_id=budget_group_id,
                    name=payload.get("name"),
                    display_order=optional_int(payload, "display_order"),
                    archived=boolean_field(payload, "archived"),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "categories"):
                auth = self.require_auth()
                category_id = int(parsed.path.split("/")[2])
                self.repository.require_category_access(category_id, auth["household_id"])
                if payload.get("budget_group_id") is not None:
                    self.repository.require_budget_group_access(require_int(payload, "budget_group_id"), auth["household_id"])
                self.repository.update_category(
                    category_id=category_id,
                    name=payload.get("name"),
                    budget_group_id=optional_int(payload, "budget_group_id"),
                    planned_cents=optional_int(payload, "planned_cents"),
                    display_order=optional_int(payload, "display_order"),
                    archived=boolean_field(payload, "archived"),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "expected-bills"):
                auth = self.require_auth()
                bill_id = int(parsed.path.split("/")[2])
                self.repository.require_bill_access(bill_id, auth["household_id"])
                self.repository.update_expected_bill(
                    bill_id=bill_id,
                    name=payload.get("name"),
                    amount_cents=optional_int(payload, "amount_cents"),
                    due_on=parse_date(payload["due_on"]) if payload.get("due_on") is not None else None,
                    paid=boolean_field(payload, "paid"),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "paydays"):
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
            if resource_path(parsed.path, "budget-months", "account-balance"):
                auth = self.require_auth()
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.require_budget_month_access(budget_month_id, auth["household_id"])
                self.repository.update_account_balance(
                    budget_month_id,
                    require_int(payload, "included_account_balance_cents"),
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "accounts"):
                auth = self.require_auth()
                account_id = int(parsed.path.split("/")[2])
                self.repository.require_account_access(account_id, auth["household_id"])
                if "included_in_cash_reality" in payload:
                    self.repository.set_account_included(
                        account_id=account_id,
                        included_in_cash_reality=boolean_field(payload, "included_in_cash_reality", False),
                    )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "transactions", "review"):
                auth = self.require_auth()
                transaction_id = int(parsed.path.split("/")[2])
                self.repository.require_transaction_access(transaction_id, auth["household_id"])
                self.repository.mark_transaction_reviewed(
                    transaction_id,
                    reviewed=boolean_field(payload, "reviewed", True),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "transactions", "category"):
                auth = self.require_auth()
                transaction_id = int(parsed.path.split("/")[2])
                self.repository.require_transaction_access(transaction_id, auth["household_id"])
                if payload.get("category_id") is None:
                    self.repository.remove_transaction_category(
                        transaction_id,
                        reviewed=boolean_field(payload, "reviewed", False),
                        actor_user_id=auth["user_id"],
                    )
                else:
                    self.repository.require_category_access(require_int(payload, "category_id"), auth["household_id"])
                    self.repository.assign_transaction_category(
                        transaction_id=transaction_id,
                        category_id=require_int(payload, "category_id"),
                        source=payload.get("source", "manual"),
                        reviewed=boolean_field(payload, "reviewed", True),
                        actor_user_id=auth["user_id"],
                    )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "transactions", "split"):
                auth = self.require_auth()
                transaction_id = int(parsed.path.split("/")[2])
                self.repository.require_transaction_access(transaction_id, auth["household_id"])
                splits = [
                    dict(split, category_id=require_int(split, "category_id"),
                         amount_cents=require_int(split, "amount_cents"))
                    for split in payload["splits"]
                ]
                for split in splits:
                    self.repository.require_category_access(split["category_id"], auth["household_id"])
                self.repository.split_transaction(
                    transaction_id=transaction_id,
                    splits=splits,
                    reviewed=boolean_field(payload, "reviewed", True),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "transactions", "ignore"):
                auth = self.require_auth()
                transaction_id = int(parsed.path.split("/")[2])
                self.repository.require_transaction_access(transaction_id, auth["household_id"])
                self.repository.set_transaction_ignored(
                    transaction_id=transaction_id,
                    ignored=boolean_field(payload, "ignored", True),
                    reason=payload.get("reason"),
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "merchant-category-rules"):
                auth = self.require_auth()
                rule_id = int(parsed.path.split("/")[2])
                self.repository.require_merchant_rule_access(rule_id, auth["household_id"])
                category_id = optional_int(payload, "category_id")
                if category_id is not None:
                    self.repository.require_category_access(category_id, auth["household_id"])
                self.repository.update_merchant_rule(
                    rule_id=rule_id,
                    merchant_match_text=payload.get("merchant_match_text"),
                    category_id=category_id,
                    priority=optional_int(payload, "priority"),
                    active=boolean_field(payload, "active"),
                    actor_user_id=auth["user_id"],
                    apply_to_existing_unreviewed=boolean_field(payload, "apply_to_existing_unreviewed", False),
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "notifications", "read"):
                auth = self.require_auth()
                notification_id = int(parsed.path.split("/")[2])
                self.repository.require_notification_access(notification_id, auth["household_id"])
                self.repository.mark_notification_read(
                    notification_id,
                    user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "households", "notifications/read-all"):
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
            if resource_path(parsed.path, "budget-months", "notifications/read-all"):
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
        except Exception as exc:
            self.send_exception(exc)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            if resource_path(parsed.path, "income"):
                auth = self.require_auth()
                income_id = int(parsed.path.split("/")[2])
                self.repository.require_income_access(income_id, auth["household_id"])
                self.repository.remove_income(income_id=income_id, actor_user_id=auth["user_id"])
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "expected-bills"):
                auth = self.require_auth()
                bill_id = int(parsed.path.split("/")[2])
                self.repository.require_bill_access(bill_id, auth["household_id"])
                self.repository.remove_expected_bill(bill_id=bill_id, actor_user_id=auth["user_id"])
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "paydays"):
                auth = self.require_auth()
                payday_id = int(parsed.path.split("/")[2])
                self.repository.require_payday_access(payday_id, auth["household_id"])
                self.repository.remove_payday(payday_id=payday_id, actor_user_id=auth["user_id"])
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "transactions", "split"):
                auth = self.require_auth()
                transaction_id = int(parsed.path.split("/")[2])
                self.repository.require_transaction_access(transaction_id, auth["household_id"])
                self.repository.remove_transaction_split(
                    transaction_id,
                    actor_user_id=auth["user_id"],
                )
                self.send_json({"ok": True})
                return
            if resource_path(parsed.path, "merchant-category-rules"):
                auth = self.require_auth()
                rule_id = int(parsed.path.split("/")[2])
                self.repository.require_merchant_rule_access(rule_id, auth["household_id"])
                self.repository.delete_merchant_rule(rule_id=rule_id, actor_user_id=auth["user_id"])
                self.send_json({"ok": True})
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Route not found")
        except Exception as exc:
            self.send_exception(exc)

    def require_auth(self) -> dict[str, Any]:
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.casefold() != "bearer" or not token.strip():
            raise UnauthorizedError("Authentication required")
        context = self.repository.auth_context_for_token(token.strip())
        if context is None:
            raise UnauthorizedError("Authentication required")
        return context

    def optional_auth(self) -> dict[str, Any] | None:
        if "Authorization" not in self.headers:
            return None
        return self.require_auth()

    def read_json(self) -> dict[str, Any]:
        if self.headers.get("Transfer-Encoding") is not None:
            raise ValueError("Transfer-Encoding is not supported")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            raise ValueError("Content-Length must appear only once")
        length_text = lengths[0] if lengths else "0"
        if re.fullmatch(r"[0-9]+", length_text) is None:
            raise ValueError("Content-Length must be a nonnegative integer")
        length = int(length_text)
        if length > MAX_REQUEST_BODY_BYTES:
            raise RequestBodyTooLargeError()
        if length == 0:
            return {}
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("Request body is incomplete")
        try:
            payload = json.loads(
                raw.decode("utf-8"), parse_constant=reject_json_constant, object_pairs_hook=unique_json_object,
            )
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object")
            validate_text_fields(payload)
        except (UnicodeDecodeError, RecursionError) as exc:
            raise ValueError("Request body must be valid UTF-8 JSON") from exc
        return payload

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json(
            {
                "error": message,
                "message": message,
                "code": ERROR_CODES.get(status, "api_error"),
                "status": status.value,
            },
            status=status,
        )

    def send_exception(self, exc: Exception) -> None:
        status, message = error_response_for_exception(exc)
        self.send_error_json(status, message)

    def log_message(self, format: str, *args: object) -> None:
        return


def error_response_for_exception(exc: Exception) -> tuple[HTTPStatus, str]:
    if isinstance(exc, RequestBodyTooLargeError):
        return HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body is too large"
    if isinstance(exc, TimeoutError):
        return HTTPStatus.REQUEST_TIMEOUT, "Request timed out"
    if isinstance(exc, UnauthorizedError):
        return HTTPStatus.UNAUTHORIZED, "Invalid credentials" if str(exc) == "Invalid credentials" else "Authentication required"
    if isinstance(exc, PermissionError):
        return HTTPStatus.FORBIDDEN, sanitize_api_error(str(exc) or "Forbidden")
    if isinstance(exc, LookupError) and not isinstance(exc, (KeyError, IndexError)):
        return HTTPStatus.NOT_FOUND, sanitize_api_error(str(exc) or "Not found")
    if isinstance(exc, PlaidIntegrationError):
        return HTTPStatus.SERVICE_UNAVAILABLE, sanitize_plaid_error(str(exc))
    if isinstance(exc, sqlite3.IntegrityError):
        return HTTPStatus.CONFLICT, "Request conflicts with existing data"
    if isinstance(exc, (json.JSONDecodeError, ValueError, KeyError, TypeError, IndexError, OverflowError)):
        return HTTPStatus.BAD_REQUEST, sanitize_api_error(validation_message(exc))
    return HTTPStatus.INTERNAL_SERVER_ERROR, "Backend error"


def validation_message(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, json.JSONDecodeError):
        return "Request body must be valid JSON"
    if isinstance(exc, KeyError):
        key = str(exc).strip("'")
        return f"{key} is required" if key else "Required field is missing"
    if isinstance(exc, (TypeError, IndexError, OverflowError)):
        return "Request contains an invalid field value"
    if "invalid literal for int()" in message:
        return "Numeric fields must be valid whole numbers"
    if "Invalid isoformat string" in message:
        return "Date fields must use YYYY-MM-DD"
    if not message:
        return "Invalid request"
    return message


def sanitize_api_error(message: str) -> str:
    forbidden_terms = (
        "access_token",
        "access token",
        "token_ref",
        "password_hash",
        "session token",
        "openai_api_key",
        "api_key",
        "secret",
        "traceback",
        ".env",
    )
    lowered = message.casefold()
    if any(term in lowered for term in forbidden_terms):
        return "Request failed; sensitive details were redacted."
    return message


def parse_date(value: str) -> date:
    try:
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("Invalid date format")
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Date fields must use YYYY-MM-DD") from exc


def require_int(payload: dict[str, Any], key: str, fallback_key: str | None = None, *, default: int | None = None) -> int:
    if key not in payload and (fallback_key is None or fallback_key not in payload):
        if default is not None:
            return default
        if fallback_key is None:
            raise ValueError(f"{key} is required")
        raise ValueError(f"{key} or {fallback_key} is required")
    value = payload.get(key, payload.get(fallback_key))
    return parse_integer(value, key)


def optional_int(payload: dict[str, Any], key: str) -> int | None:
    if key not in payload or payload[key] is None:
        return None
    return parse_integer(payload[key], key)


def parse_integer(value: Any, key: str) -> int:
    # Retain whole-number strings used by existing clients, without truncating
    # JSON floats or accepting booleans as money/identifiers.
    if type(value) is not int and not (isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip())):
        raise ValueError(f"{key} must be an integer")
    result = int(value)
    if not -(2**63) <= result < 2**63:
        raise ValueError(f"{key} is outside the supported integer range")
    return result


def boolean_field(payload: dict[str, Any], key: str, default: bool | None = None) -> bool | None:
    if key not in payload:
        return default
    value = payload[key]
    if value is None and default is None:
        return None
    if type(value) is not bool:
        raise ValueError(f"{key} must be a boolean")
    return value


def reject_json_constant(value: str) -> None:
    raise ValueError("Request body must use finite JSON numbers")


def unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Request body contains duplicate fields")
        result[key] = value
    return result


def validate_text_fields(payload: dict[str, Any]) -> None:
    text_fields = {
        "username", "email", "password", "household_name", "name", "display_name", "role",
        "current_password", "new_password", "month", "kind", "note", "purpose",
        "urgency", "public_token", "sync_type", "merchant_match_text", "source", "reason",
    }
    for key in text_fields & payload.keys():
        if payload[key] is not None and not isinstance(payload[key], str):
            raise ValueError(f"{key} must be text")
    for key in ("users", "splits"):
        if key in payload:
            values = payload[key]
            if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
                raise ValueError(f"{key} must be an array of objects")
            for item in values:
                validate_text_fields(item)


def resource_path(path: str, resource: str, action: str = "") -> bool:
    suffix = "/" + re.escape(action) if action else ""
    return re.fullmatch("/" + re.escape(resource) + r"/[0-9]+" + suffix, path) is not None


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
    return parse_integer(value, key)


def build_server(db_path: Path, host: str, port: int) -> ThreadingHTTPServer:
    repository = BudgetRepository(db_path)
    repository.initialize()

    class ConfiguredApiHandler(ApiHandler):
        pass

    ConfiguredApiHandler.repository = repository
    ConfiguredApiHandler.plaid_service = build_plaid_service_from_env(repository)
    ConfiguredApiHandler.coach_service = build_coach_service_from_env()
    return ThreadingHTTPServer((host, port), ConfiguredApiHandler)


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
