from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

from backend.app.api import ApiHandler, build_server


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = build_server(Path(self.temp_dir.name) / "api.sqlite", "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp_dir.cleanup()

    def test_safe_to_spend_endpoint_returns_required_fields(self) -> None:
        household = self.post(
            "/households",
            {
                "name": "API Household",
                "spouses": [{"name": "A"}, {"name": "B"}],
            },
        )
        budget_month = self.post(
            "/budget-months",
            {
                "household_id": household["id"],
                "month": "2026-06",
                "included_account_balance_cents": 100_000,
            },
        )
        self.post(
            "/income",
            {
                "budget_month_id": budget_month["id"],
                "name": "Paycheck",
                "kind": "main",
                "planned_cents": 300_000,
            },
        )
        group = self.post(
            "/budget-groups",
            {
                "budget_month_id": budget_month["id"],
                "name": "Food",
            },
        )
        category = self.post(
            "/categories",
            {
                "budget_group_id": group["id"],
                "name": "Groceries",
                "planned_cents": 50_000,
            },
        )
        self.post(
            "/expected-bills",
            {
                "budget_month_id": budget_month["id"],
                "name": "Water",
                "amount_cents": 20_000,
                "due_on": "2026-06-24",
            },
        )
        self.post(
            "/paydays",
            {
                "household_id": household["id"],
                "payday_date": "2026-06-28",
            },
        )

        result = self.post(
            "/safe-to-spend",
            {
                "budget_month_id": budget_month["id"],
                "category_id": category["id"],
                "purchase_amount_cents": 7_500,
                "today": date(2026, 6, 21).isoformat(),
                "urgency": "planned_want",
            },
        )

        self.assertEqual(result["warning_level"], "safe")
        self.assertTrue(result["budget_line_fits"])
        self.assertEqual(result["bills_before_payday_cents"], 20_000)
        self.assertIn("After upcoming bills", result["required_phrase"])
        self.assertEqual(result["days_until_payday"], 7)

    def test_transaction_review_endpoints_return_sanitized_payloads(self) -> None:
        household = self.post("/households", {"name": "API Transaction Household"})
        budget_month = self.post(
            "/budget-months",
            {
                "household_id": household["id"],
                "month": "2026-06",
                "included_account_balance_cents": 100_000,
            },
        )
        group = self.post(
            "/budget-groups",
            {
                "budget_month_id": budget_month["id"],
                "name": "Everyday",
            },
        )
        category = self.post(
            "/categories",
            {
                "budget_group_id": group["id"],
                "name": "Groceries",
                "planned_cents": 50_000,
            },
        )
        account_id = ApiHandler.repository.add_cash_account(
            budget_month_id=budget_month["id"],
            name="Main Checking",
            account_type="checking",
            balance_cents=100_000,
        )
        transaction_id = ApiHandler.repository.upsert_plaid_transaction(
            cash_account_id=account_id,
            plaid_transaction_id="api-txn-1",
            amount_cents=-2_500,
            occurred_on=date(2026, 6, 21),
            name="Fresh Market",
            merchant_name="Fresh Market",
            category_hint="Shops",
        ).transaction_id

        queue = self.get(f"/budget-months/{budget_month['id']}/transaction-review-queue")
        self.patch(
            f"/transactions/{transaction_id}/category",
            {
                "category_id": category["id"],
                "reviewed": True,
            },
        )
        detail = self.get(f"/transactions/{transaction_id}")

        serialized_queue = json.dumps(queue)
        serialized_detail = json.dumps(detail)
        self.assertEqual(queue["transactions"][0]["transaction"]["id"], transaction_id)
        self.assertEqual(detail["categorization_status"], "manual")
        self.assertEqual(detail["final_category_id"], category["id"])
        self.assertNotIn("access_token", serialized_queue)
        self.assertNotIn("access_token_ref", serialized_queue)
        self.assertNotIn("access_token", serialized_detail)
        self.assertNotIn("access_token_ref", serialized_detail)

    def test_notification_routes_list_count_and_mark_read(self) -> None:
        household = self.post(
            "/households",
            {
                "name": "API Notification Household",
                "spouses": [{"name": "A"}, {"name": "B"}],
            },
        )
        with ApiHandler.repository.connect() as connection:
            user_id = int(
                connection.execute(
                    "SELECT id FROM users WHERE household_id = ? ORDER BY id LIMIT 1",
                    (household["id"],),
                ).fetchone()["id"]
            )
        budget_month = self.post(
            "/budget-months",
            {
                "household_id": household["id"],
                "month": "2026-06",
                "included_account_balance_cents": 100_000,
            },
        )
        group = self.post(
            "/budget-groups",
            {
                "budget_month_id": budget_month["id"],
                "name": "Everyday",
            },
        )
        category = self.post(
            "/categories",
            {
                "budget_group_id": group["id"],
                "name": "Groceries",
                "planned_cents": 50_000,
            },
        )
        account_id = ApiHandler.repository.add_cash_account(
            budget_month_id=budget_month["id"],
            name="Main Checking",
            account_type="checking",
            balance_cents=100_000,
        )
        transaction_id = ApiHandler.repository.upsert_plaid_transaction(
            cash_account_id=account_id,
            plaid_transaction_id="api-notification-txn",
            amount_cents=-2_500,
            occurred_on=date(2026, 6, 21),
            name="Fresh Market",
            merchant_name="Fresh Market",
        ).transaction_id
        self.patch(
            f"/transactions/{transaction_id}/category",
            {
                "category_id": category["id"],
                "reviewed": True,
            },
        )

        notifications = self.get(f"/budget-months/{budget_month['id']}/notifications?user_id={user_id}")
        count = self.get(f"/budget-months/{budget_month['id']}/notifications/unread-count?user_id={user_id}")
        assigned = [
            item
            for item in notifications["notifications"]
            if item["event_type"] == "transaction_category_assigned"
        ][0]

        self.assertGreaterEqual(count["unread_count"], 1)
        self.assertEqual(assigned["affected_entity_id"], transaction_id)
        self.assertIsNone(assigned["read_at"])

        self.patch(f"/notifications/{assigned['id']}/read", {"user_id": user_id})
        reread = self.get(f"/budget-months/{budget_month['id']}/notifications?user_id={user_id}")
        read_assigned = [
            item
            for item in reread["notifications"]
            if item["id"] == assigned["id"]
        ][0]
        self.assertIsNotNone(read_assigned["read_at"])

    def get(self, path: str) -> dict[str, object]:
        with urlopen(f"{self.base_url}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def patch(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()

