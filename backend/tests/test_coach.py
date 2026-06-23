from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.app.api import ApiHandler, build_server


class CoachApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = build_server(Path(self.temp_dir.name) / "coach.sqlite", "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp_dir.cleanup()

    def test_coach_safe_to_spend_returns_deterministic_facts_and_phrase(self) -> None:
        fixture = self.seed_budget(balance_cents=100_000, grocery_planned_cents=50_000)

        result = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 7_500,
                "today": "2026-06-21",
                "urgency": "planned_want",
                "purpose": "weekly groceries",
            },
        )

        safe_to_spend = result["safe_to_spend"]
        coach = result["coach"]
        self.assertEqual(safe_to_spend["warning_level"], "safe")
        self.assertEqual(coach["warning_level"], "safe")
        self.assertEqual(safe_to_spend["cash_after_purchase_and_bills_cents"], 72_500)
        self.assertIn(
            "After upcoming bills, you would have about $725.00 left for 7 days until payday.",
            coach["summary"],
        )
        self.assertIn(safe_to_spend["required_phrase"], coach["tradeoffs"])
        self.assertIn("This uses backend-calculated budget and cash facts only.", coach["limitations"])

    def test_coach_warning_level_matches_backend_result(self) -> None:
        fixture = self.seed_budget(balance_cents=60_000, grocery_planned_cents=50_000)

        caution = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 10_000,
                "today": "2026-06-21",
            },
        )
        no = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 60_000,
                "today": "2026-06-21",
            },
        )
        discuss = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 1_000,
                "today": "2026-06-21",
                "urgency": "household_discussion",
            },
        )

        self.assertEqual(caution["safe_to_spend"]["warning_level"], "caution")
        self.assertEqual(caution["coach"]["warning_level"], "caution")
        self.assertEqual(no["safe_to_spend"]["warning_level"], "no")
        self.assertEqual(no["coach"]["warning_level"], "no")
        self.assertEqual(discuss["safe_to_spend"]["warning_level"], "discuss_with_spouse")
        self.assertEqual(discuss["coach"]["warning_level"], "discuss")

    def test_coach_endpoints_do_not_mutate_budget_category_or_transaction_data(self) -> None:
        fixture = self.seed_budget(balance_cents=100_000, grocery_planned_cents=50_000)
        account_id = ApiHandler.repository.add_cash_account(
            budget_month_id=fixture["budget_month_id"],
            name="Main Checking",
            account_type="checking",
            balance_cents=100_000,
        )
        transaction_id = ApiHandler.repository.upsert_plaid_transaction(
            cash_account_id=account_id,
            plaid_transaction_id="coach-mutation-check",
            amount_cents=-2_500,
            occurred_on=date(2026, 6, 21),
            name="Corner Store",
            merchant_name="Corner Store",
            category_hint="Shops",
        ).transaction_id
        ApiHandler.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=fixture["groceries_id"],
            reviewed=True,
        )

        summary_before = self.get(f"/budget-months/{fixture['budget_month_id']}/summary?today=2026-06-21")
        transaction_before = self.get(f"/transactions/{transaction_id}")

        self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 7_500,
                "today": "2026-06-21",
            },
        )
        proposal = self.post(
            "/coach/budget-change-suggestion",
            {
                "budget_month_id": fixture["budget_month_id"],
                "from_category_id": 999_999,
                "to_category_id": fixture["groceries_id"],
                "amount_cents": 5_000,
                "today": "2026-06-21",
            },
            expect_error=True,
        )
        self.assertIn("Category", proposal["error"])
        self.post(
            "/coach/budget-change-suggestion",
            {
                "budget_month_id": fixture["budget_month_id"],
                "from_category_id": fixture["household_supplies_id"],
                "to_category_id": fixture["groceries_id"],
                "amount_cents": 5_000,
                "today": "2026-06-21",
            },
        )

        summary_after = self.get(f"/budget-months/{fixture['budget_month_id']}/summary?today=2026-06-21")
        transaction_after = self.get(f"/transactions/{transaction_id}")
        self.assertEqual(summary_before, summary_after)
        self.assertEqual(transaction_before, transaction_after)

    def test_budget_change_suggestion_returns_proposal_only(self) -> None:
        fixture = self.seed_budget(balance_cents=100_000, grocery_planned_cents=50_000)
        before = self.get(f"/budget-months/{fixture['budget_month_id']}/summary?today=2026-06-21")

        result = self.post(
            "/coach/budget-change-suggestion",
            {
                "budget_month_id": fixture["budget_month_id"],
                "from_category_id": fixture["household_supplies_id"],
                "to_category_id": fixture["groceries_id"],
                "amount_cents": 5_000,
                "today": "2026-06-21",
                "purpose": "cover grocery overage",
            },
        )

        coach = result["coach"]
        self.assertEqual(coach["warning_level"], "discuss")
        self.assertTrue(coach["requires_spouse_discussion"])
        self.assertEqual(coach["proposed_budget_change"]["status"], "draft_only")
        self.assertEqual(coach["proposed_budget_change"]["amount_cents"], 5_000)
        self.assertIn("does not apply any budget change", " ".join(coach["limitations"]))
        after = self.get(f"/budget-months/{fixture['budget_month_id']}/summary?today=2026-06-21")
        self.assertEqual(before, after)

    def test_coach_responses_do_not_expose_plaid_token_references(self) -> None:
        fixture = self.seed_budget(balance_cents=100_000, grocery_planned_cents=50_000)
        plaid_item_id = ApiHandler.repository.create_plaid_item(
            household_id=fixture["household_id"],
            plaid_item_id="plaid-item-visible-id",
            access_token_ref="access-token-ref-secret",
        )
        ApiHandler.repository.upsert_connected_account(
            plaid_item_id=plaid_item_id,
            budget_month_id=fixture["budget_month_id"],
            plaid_account_id="plaid-account-id",
            name="Plaid Checking",
            account_type="checking",
            balance_cents=100_000,
            included_in_cash_reality=True,
        )

        safe_response = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 7_500,
                "today": "2026-06-21",
            },
        )
        suggestion_response = self.post(
            "/coach/budget-change-suggestion",
            {
                "budget_month_id": fixture["budget_month_id"],
                "from_category_id": fixture["household_supplies_id"],
                "to_category_id": fixture["groceries_id"],
                "amount_cents": 5_000,
                "today": "2026-06-21",
            },
        )

        serialized = json.dumps({"safe": safe_response, "suggestion": suggestion_response})
        self.assertNotIn("access_token", serialized)
        self.assertNotIn("access_token_ref", serialized)
        self.assertNotIn("access-token-ref-secret", serialized)
        self.assertNotIn("plaid-item-visible-id", serialized)

    def test_missing_or_invalid_inputs_return_clear_errors(self) -> None:
        fixture = self.seed_budget(balance_cents=100_000, grocery_planned_cents=50_000)

        missing_amount = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "today": "2026-06-21",
            },
            expect_error=True,
        )
        invalid_amount = self.post(
            "/coach/budget-change-suggestion",
            {
                "budget_month_id": fixture["budget_month_id"],
                "to_category_id": fixture["groceries_id"],
                "amount_cents": "five dollars",
                "today": "2026-06-21",
            },
            expect_error=True,
        )

        self.assertEqual(missing_amount["error"], "amount_cents or purchase_amount_cents is required")
        self.assertEqual(invalid_amount["error"], "amount_cents must be an integer")

    def seed_budget(self, *, balance_cents: int, grocery_planned_cents: int) -> dict[str, int]:
        household = self.post(
            "/households",
            {
                "name": "Coach Household",
                "spouses": [{"name": "A"}, {"name": "B"}],
            },
        )
        budget_month = self.post(
            "/budget-months",
            {
                "household_id": household["id"],
                "month": "2026-06",
                "included_account_balance_cents": balance_cents,
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
                "name": "Everyday",
            },
        )
        groceries = self.post(
            "/categories",
            {
                "budget_group_id": group["id"],
                "name": "Groceries",
                "planned_cents": grocery_planned_cents,
            },
        )
        household_supplies = self.post(
            "/categories",
            {
                "budget_group_id": group["id"],
                "name": "Household Supplies",
                "planned_cents": 20_000,
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
        return {
            "household_id": household["id"],
            "budget_month_id": budget_month["id"],
            "groceries_id": groceries["id"],
            "household_supplies_id": household_supplies["id"],
        }

    def get(self, path: str) -> dict[str, object]:
        with urlopen(f"{self.base_url}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def post(
        self,
        path: str,
        payload: dict[str, object],
        *,
        expect_error: bool = False,
    ) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            result = json.loads(exc.read().decode("utf-8"))
            if not expect_error:
                raise
            return result
        if expect_error:
            self.fail(f"Expected {path} to return an error")
        return result


if __name__ == "__main__":
    unittest.main()
