from __future__ import annotations

import argparse
import json
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .db import BudgetRepository, account_to_dict, safe_to_spend_to_dict, summary_to_dict
from .plaid import (
    PlaidConnectionService,
    link_token_to_dict,
    plaid_connection_result_to_dict,
    plaid_sync_outcome_to_dict,
)


class ApiHandler(BaseHTTPRequestHandler):
    repository: BudgetRepository
    plaid_service: PlaidConnectionService

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/health":
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/summary"):
                budget_month_id = int(parsed.path.split("/")[2])
                query = parse_qs(parsed.query)
                today = parse_date(query.get("today", [date.today().isoformat()])[0])
                summary = self.repository.get_summary(budget_month_id, today)
                self.send_json(summary_to_dict(summary))
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/accounts"):
                budget_month_id = int(parsed.path.split("/")[2])
                accounts = self.repository.list_accounts(budget_month_id)
                self.send_json({"accounts": [account_to_dict(account) for account in accounts]})
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Route not found")
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/households":
                household_id = self.repository.create_household(
                    payload["name"],
                    spouses=payload.get("spouses", ()),
                )
                self.send_json({"id": household_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/budget-months":
                budget_month_id = self.repository.create_budget_month(
                    household_id=int(payload["household_id"]),
                    month=payload["month"],
                    included_account_balance_cents=int(payload.get("included_account_balance_cents", 0)),
                    low_cushion_daily_cents=int(payload.get("low_cushion_daily_cents", 5_000)),
                )
                self.send_json({"id": budget_month_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/income":
                income_id = self.repository.add_income(
                    budget_month_id=int(payload["budget_month_id"]),
                    name=payload["name"],
                    kind=payload["kind"],
                    planned_cents=int(payload.get("planned_cents", 0)),
                    received_cents=int(payload.get("received_cents", 0)),
                )
                self.send_json({"id": income_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/budget-groups":
                group_id = self.repository.add_budget_group(
                    budget_month_id=int(payload["budget_month_id"]),
                    name=payload["name"],
                    display_order=int(payload.get("display_order", 0)),
                )
                self.send_json({"id": group_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/categories":
                category_id = self.repository.add_category(
                    budget_group_id=int(payload["budget_group_id"]),
                    name=payload["name"],
                    planned_cents=int(payload.get("planned_cents", 0)),
                    display_order=int(payload.get("display_order", 0)),
                )
                self.send_json({"id": category_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/spending":
                spending_id = self.repository.record_spending(
                    category_id=int(payload["category_id"]),
                    amount_cents=int(payload["amount_cents"]),
                    occurred_on=parse_date(payload["occurred_on"]),
                    note=payload.get("note"),
                )
                self.send_json({"id": spending_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/expected-bills":
                bill_id = self.repository.add_expected_bill(
                    budget_month_id=int(payload["budget_month_id"]),
                    name=payload["name"],
                    amount_cents=int(payload["amount_cents"]),
                    due_on=parse_date(payload["due_on"]),
                    paid=bool(payload.get("paid", False)),
                )
                self.send_json({"id": bill_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/paydays":
                payday_id = self.repository.add_payday(
                    household_id=int(payload["household_id"]),
                    payday_date=parse_date(payload["payday_date"]),
                )
                self.send_json({"id": payday_id}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/safe-to-spend":
                result = self.repository.safe_to_spend(
                    budget_month_id=int(payload["budget_month_id"]),
                    category_id=int(payload["category_id"]),
                    purchase_amount_cents=int(payload["purchase_amount_cents"]),
                    today=parse_date(payload.get("today", date.today().isoformat())),
                    urgency=payload.get("urgency", "planned_want"),
                )
                self.send_json(safe_to_spend_to_dict(result))
                return
            if parsed.path == "/plaid/link-token":
                link_token = self.plaid_service.create_link_token(
                    household_id=int(payload["household_id"]),
                )
                self.send_json(link_token_to_dict(link_token), status=HTTPStatus.CREATED)
                return
            if parsed.path == "/plaid/exchange-public-token":
                result = self.plaid_service.exchange_public_token(
                    household_id=int(payload["household_id"]),
                    budget_month_id=int(payload["budget_month_id"]),
                    public_token=payload["public_token"],
                )
                self.send_json(plaid_connection_result_to_dict(result), status=HTTPStatus.CREATED)
                return
            if parsed.path == "/plaid/sync":
                sync_type = payload["sync_type"]
                plaid_item_id = int(payload["plaid_item_id"])
                if sync_type == "balance":
                    outcome = self.plaid_service.sync_balances(plaid_item_id)
                elif sync_type == "transaction":
                    outcome = self.plaid_service.sync_transactions(plaid_item_id)
                else:
                    raise ValueError("sync_type must be 'balance' or 'transaction'")
                self.send_json(plaid_sync_outcome_to_dict(outcome))
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Route not found")
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path.startswith("/categories/"):
                category_id = int(parsed.path.split("/")[2])
                self.repository.update_category(
                    category_id=category_id,
                    name=payload.get("name"),
                    planned_cents=payload.get("planned_cents"),
                    archived=payload.get("archived"),
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/budget-months/") and parsed.path.endswith("/account-balance"):
                budget_month_id = int(parsed.path.split("/")[2])
                self.repository.update_account_balance(
                    budget_month_id,
                    int(payload["included_account_balance_cents"]),
                )
                self.send_json({"ok": True})
                return
            if parsed.path.startswith("/accounts/"):
                account_id = int(parsed.path.split("/")[2])
                if "included_in_cash_reality" in payload:
                    self.repository.set_account_included(
                        account_id=account_id,
                        included_in_cash_reality=bool(payload["included_in_cash_reality"]),
                    )
                self.send_json({"ok": True})
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Route not found")
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

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


def build_server(db_path: Path, host: str, port: int) -> ThreadingHTTPServer:
    repository = BudgetRepository(db_path)
    repository.initialize()
    ApiHandler.repository = repository
    ApiHandler.plaid_service = PlaidConnectionService(repository)
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
