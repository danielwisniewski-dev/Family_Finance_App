"""Repeatable HTTP/persistence smoke using only disposable synthetic local data.

Run from the repository root: python -m backend.smoke_review
"""
from __future__ import annotations

import json
import tempfile
import threading
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from backend.app.api import build_server
from backend.app.db import BudgetRepository
from backend.app.demo_seed import seed_demo


@contextmanager
def local_server(path):
    # Never inherit configured live providers or send localhost through a proxy.
    with patch.dict("os.environ", {"COACH_PROVIDER": "mock", "PLAID_ENV": "sandbox",
                                  "PLAID_CLIENT_ID": "", "PLAID_SECRET": "", "OPENAI_API_KEY": ""}):
        server = build_server(path, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def main():
    opener = build_opener(ProxyHandler({}))
    token = None

    def call(method, path, payload=None, status=200, auth=True):
        headers = {"Content-Type": "application/json"}
        if auth and token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(base + path, headers=headers, method=method,
                          data=json.dumps(payload).encode() if payload is not None else None)
        try:
            response = opener.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            assert response.status == status, (method, path, response.status, status)
            assert response.headers["Cache-Control"] == "no-store"
            return json.loads(response.read())

    def summary():
        return call("GET", f"/budget-months/{month}/summary?today={today}")

    def spent():
        return {c["name"]: c["spent_cents"] for c in summary()["categories"]}

    with tempfile.TemporaryDirectory(prefix="family-finance-smoke-") as temporary:
        path = Path(temporary) / "synthetic.sqlite"
        today = date.today()
        seeded = seed_demo(path, today)
        month = seeded["budget_month_id"]
        with local_server(path) as base:
            call("GET", f"/budget-months/{month}/summary", status=401, auth=False)
            call("POST", "/auth/login", {"username": "daniel", "password": "incorrect"}, status=401, auth=False)
            token = call("POST", "/auth/login", {"username": "daniel", "password": "daniel-local-demo-only"}, auth=False)["token"]
            before = summary()
            assert before["included_account_balance_cents"] == 103500
            assert before["bills_before_payday_cents"] == 26500
            assert before["cash_after_bills_cents"] == 77000
            assert before["total_spent_cents"] == 22082
            categories = {c["name"]: c["id"] for c in before["categories"]}
            detail = call("GET", f"/budget-months/{month}/budget-detail?today={today}")
            assert detail["total_spent_cents"] == before["total_spent_cents"]
            transactions = call("GET", f"/budget-months/{month}/transactions")["transactions"]
            transaction = next(t["transaction"]["id"] for t in transactions if t["transaction"]["name"] == "Corner Store")
            call("PATCH", f"/transactions/{transaction}/category", {"category_id": categories["Groceries"], "reviewed": True})
            assert spent()["Groceries"] == 10579
            splits = [{"category_id": categories["Groceries"], "amount_cents": 1000},
                      {"category_id": categories["Household Supplies"], "amount_cents": 1147}]
            call("PATCH", f"/transactions/{transaction}/split", {"splits": splits, "reviewed": True})
            assert spent()["Groceries"] == 9432
            assert spent()["Household Supplies"] == 1147
            call("PATCH", f"/transactions/{transaction}/split", {"splits": splits[:1]}, status=400)
            assert spent()["Household Supplies"] == 1147
            call("PATCH", f"/transactions/{transaction}/ignore", {"ignored": True})
            assert summary()["total_spent_cents"] == 22082
            call("PATCH", f"/transactions/{transaction}/ignore", {"ignored": False})
            assert call("GET", f"/transactions/{transaction}")["assignments"] == []
            call("PATCH", f"/transactions/{transaction}/category", {"category_id": categories["Groceries"], "reviewed": True})
            request = {"budget_month_id": month, "category_id": categories["Eating Out"],
                       "purchase_amount_cents": 3000, "today": str(today)}
            result = call("POST", "/safe-to-spend", request)
            assert result["cash_after_purchase_and_bills_cents"] == 74000
            assert result["category_remaining_after_cents"] == 3400
            assert "$740.00 left for 6 days until payday." in result["required_phrase"]
            call("POST", "/safe-to-spend", request | {"purchase_amount_cents": 0.5}, status=400)
            archived = call("POST", "/categories", {"budget_group_id": detail["groups"][0]["id"],
                                                     "name": "Archive check", "planned_cents": 1000}, status=201)["id"]
            call("PATCH", f"/categories/{archived}", {"archived": True})
            call("PATCH", f"/transactions/{transaction}/category", {"category_id": archived}, status=400)
            call("POST", "/safe-to-spend", request | {"category_id": archived}, status=400)
            expired = today + timedelta(days=7)
            missing = call("GET", f"/budget-months/{month}/summary?today={expired}")
            assert missing["forecast_available"] is False and missing["cash_after_bills_cents"] is None
            call("POST", "/safe-to-spend", request | {"today": str(expired)}, status=400)
            call("GET", "/app/diagnostics")
            snapshot = summary()
        # A new repository/server must return the saved state and session, not an in-memory cache.
        with local_server(path) as base:
            assert summary() == snapshot
            saved = call("GET", f"/transactions/{transaction}")
            assert saved["assignments"][0]["amount_cents"] == 2147
            assert saved["transaction"]["reviewed"] is True
            repo = BudgetRepository(path)
            foreign = repo.create_household("Other synthetic household")
            foreign_month = repo.create_budget_month(household_id=foreign, month=today.strftime("%Y-%m"))
            call("GET", f"/budget-months/{foreign_month}/summary", status=403)
    print("PASS: synthetic login, authorization, summaries, categorize/split/ignore, invalid inputs,")
    print("      archived category guards, safe-to-spend, missing forecast, diagnostics, and server-restart persistence.")
    print("      Temporary database removed; no live integrations called.")


if __name__ == "__main__":
    main()
