from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend.app.db import BudgetRepository
from backend.app.domain import WarningLevel


class BudgetEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = BudgetRepository(Path(self.temp_dir.name) / "test.sqlite")
        self.repository.initialize()

        self.household_id = self.repository.create_household(
            "Tester Household",
            spouses=(
                {"name": "Spouse One"},
                {"name": "Spouse Two"},
            ),
        )
        self.budget_month_id = self.repository.create_budget_month(
            household_id=self.household_id,
            month="2026-06",
            included_account_balance_cents=100_000,
            low_cushion_daily_cents=5_000,
        )
        self.repository.add_income(
            budget_month_id=self.budget_month_id,
            name="Main paycheck",
            kind="main",
            planned_cents=300_000,
        )
        self.group_id = self.repository.add_budget_group(
            budget_month_id=self.budget_month_id,
            name="Food",
        )
        self.category_id = self.repository.add_category(
            budget_group_id=self.group_id,
            name="Eating Out",
            planned_cents=20_000,
        )
        self.repository.add_payday(
            household_id=self.household_id,
            payday_date=date(2026, 6, 28),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_overspending_budget_line_returns_no(self) -> None:
        self.repository.record_spending(
            category_id=self.category_id,
            amount_cents=18_000,
            occurred_on=date(2026, 6, 20),
        )

        result = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=3_000,
            today=date(2026, 6, 21),
            urgency="planned_want",
        )

        self.assertEqual(result.warning_level, WarningLevel.NO)
        self.assertFalse(result.budget_line_fits)
        self.assertEqual(result.category_remaining_after_cents, -1_000)

    def test_low_cash_cushion_returns_caution_even_when_category_fits(self) -> None:
        self.repository.update_account_balance(self.budget_month_id, included_account_balance_cents=45_000)
        self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Utilities",
            amount_cents=15_000,
            due_on=date(2026, 6, 23),
        )

        result = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=5_000,
            today=date(2026, 6, 21),
            urgency="need",
        )

        self.assertEqual(result.warning_level, WarningLevel.CAUTION)
        self.assertTrue(result.budget_line_fits)
        self.assertTrue(result.low_cushion)
        self.assertEqual(result.cash_after_purchase_and_bills_cents, 25_000)
        self.assertEqual(result.days_until_payday, 7)

    def test_upcoming_bills_before_payday_reduce_cash_reality(self) -> None:
        self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Rent",
            amount_cents=60_000,
            due_on=date(2026, 6, 24),
        )
        self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="After payday bill",
            amount_cents=25_000,
            due_on=date(2026, 6, 28),
        )

        result = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=10_000,
            today=date(2026, 6, 21),
            urgency="planned_want",
        )

        self.assertEqual(result.bills_before_payday_cents, 60_000)
        self.assertEqual(result.cash_after_bills_before_purchase_cents, 40_000)
        self.assertEqual(result.cash_after_purchase_and_bills_cents, 30_000)
        self.assertIn("After upcoming bills", result.required_phrase)

    def test_sporadic_income_only_counts_when_received(self) -> None:
        self.repository.add_income(
            budget_month_id=self.budget_month_id,
            name="Side job",
            kind="sporadic",
            planned_cents=50_000,
            received_cents=12_000,
        )

        summary = self.repository.get_summary(self.budget_month_id, today=date(2026, 6, 21))

        self.assertEqual(summary.income_available_cents, 312_000)
        self.assertEqual(summary.planned_cents, 20_000)
        self.assertEqual(summary.unassigned_cents, 292_000)

    def test_bills_exceeding_available_account_balance_returns_no(self) -> None:
        self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Mortgage",
            amount_cents=120_000,
            due_on=date(2026, 6, 24),
        )

        result = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=1_000,
            today=date(2026, 6, 21),
            urgency="need",
        )

        self.assertEqual(result.warning_level, WarningLevel.NO)
        self.assertTrue(result.budget_line_fits)
        self.assertEqual(result.cash_after_bills_before_purchase_cents, -20_000)
        self.assertEqual(result.cash_after_purchase_and_bills_cents, -21_000)

    def test_no_next_payday_exists_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "No upcoming payday configured"):
            self.repository.safe_to_spend(
                budget_month_id=self.budget_month_id,
                category_id=self.category_id,
                purchase_amount_cents=1_000,
                today=date(2026, 6, 29),
                urgency="planned_want",
            )

    def test_purchase_can_leave_exactly_zero_in_category(self) -> None:
        self.repository.record_spending(
            category_id=self.category_id,
            amount_cents=15_000,
            occurred_on=date(2026, 6, 20),
        )

        result = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=5_000,
            today=date(2026, 6, 21),
            urgency="planned_want",
        )

        self.assertEqual(result.warning_level, WarningLevel.SAFE)
        self.assertTrue(result.budget_line_fits)
        self.assertEqual(result.category_remaining_after_cents, 0)

    def test_archived_categories_cannot_be_used_for_safe_to_spend(self) -> None:
        self.repository.update_category(category_id=self.category_id, archived=True)

        with self.assertRaisesRegex(ValueError, "Cannot spend from an archived category"):
            self.repository.safe_to_spend(
                budget_month_id=self.budget_month_id,
                category_id=self.category_id,
                purchase_amount_cents=1_000,
                today=date(2026, 6, 21),
                urgency="planned_want",
            )

    def test_editing_category_funding_changes_safe_to_spend_result(self) -> None:
        before = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=25_000,
            today=date(2026, 6, 21),
            urgency="planned_want",
        )

        self.repository.update_category(category_id=self.category_id, planned_cents=30_000)

        after = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=25_000,
            today=date(2026, 6, 21),
            urgency="planned_want",
        )

        self.assertEqual(before.warning_level, WarningLevel.NO)
        self.assertFalse(before.budget_line_fits)
        self.assertEqual(after.warning_level, WarningLevel.SAFE)
        self.assertTrue(after.budget_line_fits)
        self.assertEqual(after.category_remaining_after_cents, 5_000)

    def test_bills_due_today_count_before_payday(self) -> None:
        self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Phone",
            amount_cents=12_500,
            due_on=date(2026, 6, 21),
        )

        result = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=2_500,
            today=date(2026, 6, 21),
            urgency="need",
        )

        self.assertEqual(result.bills_before_payday_cents, 12_500)
        self.assertEqual(result.cash_after_bills_before_purchase_cents, 87_500)
        self.assertEqual(result.cash_after_purchase_and_bills_cents, 85_000)

    def test_savings_account_inclusion_changes_cash_reality(self) -> None:
        savings_id = self.repository.add_cash_account(
            budget_month_id=self.budget_month_id,
            name="Emergency Savings",
            account_type="savings",
            balance_cents=50_000,
            included_in_cash_reality=False,
        )
        self.repository.add_cash_account(
            budget_month_id=self.budget_month_id,
            name="Main Checking",
            account_type="checking",
            balance_cents=40_000,
            included_in_cash_reality=True,
        )
        self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Insurance",
            amount_cents=30_000,
            due_on=date(2026, 6, 24),
        )

        excluded = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=5_000,
            today=date(2026, 6, 21),
            urgency="planned_want",
        )

        self.repository.update_cash_account(
            account_id=savings_id,
            included_in_cash_reality=True,
        )

        included = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=5_000,
            today=date(2026, 6, 21),
            urgency="planned_want",
        )

        self.assertEqual(excluded.included_account_balance_cents, 40_000)
        self.assertEqual(excluded.warning_level, WarningLevel.CAUTION)
        self.assertEqual(excluded.cash_after_purchase_and_bills_cents, 5_000)
        self.assertEqual(included.included_account_balance_cents, 90_000)
        self.assertEqual(included.warning_level, WarningLevel.SAFE)
        self.assertEqual(included.cash_after_purchase_and_bills_cents, 55_000)


if __name__ == "__main__":
    unittest.main()
