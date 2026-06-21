from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

from backend.app.api import build_server


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

    def post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()

