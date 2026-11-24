from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend.app.db import BudgetRepository


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

    def test_overspending_remains_visible_in_category_balance(self):
        self.repository.record_spending(category_id=self.category_id, amount_cents=21_000, occurred_on=date(2026,6,20))
        summary = self.repository.get_summary(self.budget_month_id, date(2026,6,21))
        self.assertEqual(summary.categories[0].remaining_cents, -1_000)
        self.assertEqual(summary.cash_after_bills_cents, 100_000)

    def test_dashboard_flags_low_cash_cushion(self) -> None:
        self.repository.update_account_balance(self.budget_month_id, included_account_balance_cents=45_000)
        self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Utilities",
            amount_cents=15_000,
            due_on=date(2026, 6, 23),
        )

        result = self.repository.get_summary(self.budget_month_id, date(2026, 6, 21))

        self.assertTrue(result.low_cushion)
        self.assertEqual(result.cash_after_bills_cents, 30_000)
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

        result = self.repository.get_summary(self.budget_month_id, date(2026, 6, 21))

        self.assertEqual(result.bills_before_payday_cents, 60_000)
        self.assertEqual(result.cash_after_bills_cents, 40_000)

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

    def test_bills_exceeding_cash_show_negative_forecast(self) -> None:
        self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Mortgage",
            amount_cents=120_000,
            due_on=date(2026, 6, 24),
        )

        result = self.repository.get_summary(self.budget_month_id, date(2026, 6, 21))

        self.assertEqual(result.cash_after_bills_cents, -20_000)

    def test_missing_payday_keeps_balances_but_does_not_invent_forecast(self):
        summary = self.repository.get_summary(self.budget_month_id, date(2026,6,29))
        self.assertFalse(summary.forecast_available)
        self.assertIsNone(summary.cash_after_bills_cents)
        self.assertEqual(summary.categories[0].remaining_cents, 20_000)

    def test_recorded_spending_can_leave_exactly_zero_in_category(self):
        self.repository.record_spending(category_id=self.category_id, amount_cents=20_000, occurred_on=date(2026,6,20))
        summary = self.repository.get_summary(self.budget_month_id, date(2026,6,21))
        self.assertEqual(summary.categories[0].remaining_cents, 0)

    def test_archived_categories_cannot_be_used_for_new_spending(self):
        self.repository.update_category(category_id=self.category_id, archived=True)
        with self.assertRaisesRegex(ValueError, "archived category"):
            self.repository.record_spending(category_id=self.category_id, amount_cents=1_000, occurred_on=date(2026,6,21))
        self.assertFalse(self.repository.get_summary(self.budget_month_id, date(2026,6,21)).categories)

    def test_editing_category_funding_updates_balance_without_changing_cash(self):
        before = self.repository.get_summary(self.budget_month_id, date(2026,6,21))
        self.repository.update_category(category_id=self.category_id, planned_cents=30_000)
        after = self.repository.get_summary(self.budget_month_id, date(2026,6,21))
        self.assertEqual(before.categories[0].remaining_cents, 20_000)
        self.assertEqual(after.categories[0].remaining_cents, 30_000)
        self.assertEqual(before.cash_after_bills_cents, after.cash_after_bills_cents)

    def test_bills_due_today_count_before_payday(self) -> None:
        self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Phone",
            amount_cents=12_500,
            due_on=date(2026, 6, 21),
        )

        result = self.repository.get_summary(self.budget_month_id, date(2026, 6, 21))

        self.assertEqual(result.bills_before_payday_cents, 12_500)
        self.assertEqual(result.cash_after_bills_cents, 87_500)

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

        excluded = self.repository.get_summary(self.budget_month_id, date(2026, 6, 21))

        self.repository.update_cash_account(
            account_id=savings_id,
            included_in_cash_reality=True,
        )

        included = self.repository.get_summary(self.budget_month_id, date(2026, 6, 21))

        self.assertEqual(excluded.included_account_balance_cents, 40_000)
        self.assertEqual(excluded.cash_after_bills_cents, 10_000)
        self.assertEqual(included.included_account_balance_cents, 90_000)
        self.assertEqual(included.cash_after_bills_cents, 60_000)


if __name__ == "__main__":
    unittest.main()
