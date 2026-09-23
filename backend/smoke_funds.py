"""Practical two-spouse provision flow over HTTP, with disposable synthetic data."""
import json
import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from urllib.request import Request, urlopen

from backend.app.api import build_server
from backend.app.dates import household_today
from backend.app.db import BudgetRepository


def main():
    today = household_today()
    with tempfile.TemporaryDirectory(prefix="synthetic-provision-smoke-") as temporary:
        path = Path(temporary) / "synthetic.sqlite"
        server = build_server(path, "127.0.0.1", 0)
        server.RequestHandlerClass.log_message = lambda *args: None
        repo = server.RequestHandlerClass.repository
        household = repo.create_household("Synthetic smoke", spouses=[
            {"name": "One", "username": "smoke-one", "password": "synthetic-password-one"},
            {"name": "Two", "username": "smoke-two", "password": "synthetic-password-two"}])
        month = repo.create_budget_month(household_id=household, month=today.strftime("%Y-%m"), low_cushion_daily_cents=0)
        repo.add_payday(household_id=household, payday_date=today + timedelta(days=7))
        account = repo.add_cash_account(budget_month_id=month, name="Synthetic checking", account_type="checking", balance_cents=20000)
        group = repo.add_budget_group(budget_month_id=month, name="Everyday")
        category = repo.add_category(budget_group_id=group, name="Synthetic ordinary", planned_cents=50000)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def request(method, route, payload=None, token=None):
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            data = None if payload is None else json.dumps(payload).encode()
            with urlopen(Request(base + route, data=data, method=method, headers=headers), timeout=10) as response:
                return json.load(response)

        try:
            one = request("POST", "/auth/login", {"username": "smoke-one", "password": "synthetic-password-one"})["token"]
            two = request("POST", "/auth/login", {"username": "smoke-two", "password": "synthetic-password-two"})["token"]
            fund = request("POST", f"/budget-months/{month}/funds", {
                "name": "Synthetic repair reserve", "backing_account_id": account,
                "monthly_plan_cents": 10000, "annual_target_cents": 120000}, one)
            assert fund["balance_cents"] == 0
            entry = {"budget_month_id": month, "kind": "contribution", "amount_cents": 5000,
                "occurred_on": today.isoformat(), "idempotency_key": "smoke-contribution"}
            request("POST", f"/funds/{fund['id']}/entries", entry, one)
            request("POST", f"/funds/{fund['id']}/entries", entry, one)
            assert request("GET", f"/budget-months/{month}/funds", token=two)["total_balance_cents"] == 5000
            transaction = repo.upsert_plaid_transaction(cash_account_id=account,
                plaid_transaction_id="synthetic-smoke-purchase", amount_cents=-3000,
                occurred_on=today, name="Synthetic repair")
            request("PATCH", f"/transactions/{transaction.transaction_id}/category", {
                "category_id": fund["category_id"], "reviewed": True}, two)
            # Simulate the corresponding saved bank balance after the real expense.
            repo.update_cash_account(account_id=account, balance_cents=17000)
            overview = request("GET", f"/budget-months/{month}/funds", token=one)
            assert overview["total_balance_cents"] == 2000
            assert overview["total_contributed_cents"] == 5000
            assert overview["total_spent_cents"] == 3000
            assert overview["total_shortfall_cents"] == 5000
            summary = request("GET", f"/budget-months/{month}/summary", token=two)
            assert summary["cash_after_bills_cents"] == 15000
            purchase = request("POST", "/safe-to-spend", {"budget_month_id": month,
                "category_id": category, "purchase_amount_cents": 16000, "today": today.isoformat()}, one)
            assert purchase["warning_level"] == "no"
            next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m")
            copied = request("POST", "/budget-months", {"household_id": household,
                "month": next_month, "copy_from_budget_month_id": month}, one)
            carried = request("GET", f"/budget-months/{copied['id']}/funds", token=two)
            assert carried["total_balance_cents"] == 2000
            assert carried["total_contributed_cents"] == 0
            assert carried["total_planned_cents"] == 10000
            reopened = BudgetRepository(path)
            reopened.initialize()
            assert reopened.get_funds(month)["total_balance_cents"] == 2000
            print(json.dumps({"smoke": "passed", "flow": ["authenticated two-spouse reads", "zero opening",
                "partial funding", "safe retry", "categorized purchase", "protected cash",
                "month carryover", "persistence"], "real_bank_calls": 0}))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
