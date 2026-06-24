from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend.app.db import BudgetRepository


class TransactionCategorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = BudgetRepository(Path(self.temp_dir.name) / "test.sqlite")
        self.repository.initialize()

        self.household_id = self.repository.create_household("Milestone 3 Household")
        self.budget_month_id = self.repository.create_budget_month(
            household_id=self.household_id,
            month="2026-06",
            included_account_balance_cents=100_000,
        )
        self.repository.add_payday(
            household_id=self.household_id,
            payday_date=date(2026, 6, 28),
        )
        group_id = self.repository.add_budget_group(
            budget_month_id=self.budget_month_id,
            name="Everyday",
        )
        self.groceries_id = self.repository.add_category(
            budget_group_id=group_id,
            name="Groceries",
            planned_cents=50_000,
        )
        self.dining_id = self.repository.add_category(
            budget_group_id=group_id,
            name="Dining",
            planned_cents=20_000,
        )
        self.gas_id = self.repository.add_category(
            budget_group_id=group_id,
            name="Gas",
            planned_cents=15_000,
        )
        self.account_id = self.repository.add_cash_account(
            budget_month_id=self.budget_month_id,
            name="Main Checking",
            account_type="checking",
            balance_cents=100_000,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def import_transaction(
        self,
        *,
        plaid_transaction_id: str = "txn-1",
        amount_cents: int = -2_500,
        name: str = "Fresh Market",
        merchant_name: str | None = "Fresh Market",
        category_hint: str | None = None,
    ) -> int:
        return self.repository.upsert_plaid_transaction(
            cash_account_id=self.account_id,
            plaid_transaction_id=plaid_transaction_id,
            amount_cents=amount_cents,
            occurred_on=date(2026, 6, 21),
            name=name,
            merchant_name=merchant_name,
            category_hint=category_hint,
        ).transaction_id

    def category_totals(self) -> dict[int, tuple[int, int]]:
        summary = self.repository.get_summary(self.budget_month_id, today=date(2026, 6, 21))
        return {
            category.id: (category.spent_cents, category.remaining_cents)
            for category in summary.categories
        }

    def test_uncategorized_transactions_appear_in_review_queue(self) -> None:
        transaction_id = self.import_transaction()

        queue = self.repository.list_transaction_review_queue(self.budget_month_id)

        self.assertEqual([item.transaction.id for item in queue], [transaction_id])
        self.assertEqual(queue[0].categorization_status, "uncategorized")
        self.assertTrue(queue[0].needs_review)

    def test_assigning_category_updates_spent_and_remaining(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-4_200)

        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )

        totals = self.category_totals()
        self.assertEqual(totals[self.groceries_id], (4_200, 45_800))

    def test_archived_categories_are_rejected_for_categorization(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-4_200)
        self.repository.update_category(category_id=self.groceries_id, archived=True)

        with self.assertRaisesRegex(ValueError, "active"):
            self.repository.assign_transaction_category(
                transaction_id=transaction_id,
                category_id=self.groceries_id,
            )

        self.assertEqual(self.category_totals().get(self.groceries_id), None)

    def test_recategorizing_moves_spending_between_categories(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-3_100)

        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.dining_id,
        )

        totals = self.category_totals()
        self.assertEqual(totals[self.groceries_id], (0, 50_000))
        self.assertEqual(totals[self.dining_id], (3_100, 16_900))

    def test_removing_category_assignment_clears_spending_and_returns_to_queue(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-3_300)
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )

        self.repository.remove_transaction_category(transaction_id)

        detail = self.repository.get_transaction_detail(transaction_id)
        queue = self.repository.list_transaction_review_queue(self.budget_month_id)
        totals = self.category_totals()
        self.assertEqual(detail.categorization_status, "uncategorized")
        self.assertEqual(detail.assignments, ())
        self.assertEqual(totals[self.groceries_id], (0, 50_000))
        self.assertEqual([item.transaction.id for item in queue], [transaction_id])

    def test_merchant_rules_categorize_future_matching_transactions(self) -> None:
        self.repository.create_merchant_rule(
            household_id=self.household_id,
            merchant_match_text="fresh",
            category_id=self.dining_id,
            priority=20,
        )
        self.repository.create_merchant_rule(
            household_id=self.household_id,
            merchant_match_text="fresh market",
            category_id=self.groceries_id,
            priority=10,
        )

        transaction_id = self.import_transaction(
            plaid_transaction_id="txn-rule",
            amount_cents=-5_500,
            merchant_name="Fresh Market #42",
        )

        detail = self.repository.get_transaction_detail(transaction_id)
        totals = self.category_totals()
        self.assertEqual(detail.categorization_status, "rule")
        self.assertEqual(detail.final_category_id, self.groceries_id)
        self.assertEqual(totals[self.groceries_id], (5_500, 44_500))
        self.assertEqual(totals[self.dining_id], (0, 20_000))

    def test_merchant_rule_overrides_plaid_category_hint(self) -> None:
        self.repository.create_merchant_rule(
            household_id=self.household_id,
            merchant_match_text="fuel stop",
            category_id=self.gas_id,
            priority=10,
        )

        transaction_id = self.import_transaction(
            plaid_transaction_id="txn-rule-hint",
            amount_cents=-4_400,
            name="Fuel Stop",
            merchant_name="Fuel Stop",
            category_hint="Food and Drink",
        )

        detail = self.repository.get_transaction_detail(transaction_id)
        totals = self.category_totals()
        self.assertEqual(detail.transaction.category_hint, "Food and Drink")
        self.assertEqual(detail.categorization_status, "rule")
        self.assertEqual(detail.final_category_id, self.gas_id)
        self.assertEqual(totals[self.gas_id], (4_400, 10_600))

    def test_manual_category_choice_overrides_plaid_category_hint(self) -> None:
        transaction_id = self.import_transaction(
            amount_cents=-1_800,
            category_hint="Food and Drink",
        )

        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.dining_id,
        )

        detail = self.repository.get_transaction_detail(transaction_id)
        totals = self.category_totals()
        self.assertEqual(detail.transaction.category_hint, "Food and Drink")
        self.assertEqual(detail.assignments[0].source, "manual")
        self.assertEqual(detail.final_category_id, self.dining_id)
        self.assertEqual(totals[self.dining_id], (1_800, 18_200))

    def test_split_transactions_update_multiple_category_totals(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-6_000)

        self.repository.split_transaction(
            transaction_id=transaction_id,
            splits=(
                {"category_id": self.groceries_id, "amount_cents": 4_000},
                {"category_id": self.dining_id, "amount_cents": 2_000},
            ),
        )

        totals = self.category_totals()
        detail = self.repository.get_transaction_detail(transaction_id)
        self.assertEqual(detail.categorization_status, "split")
        self.assertEqual(totals[self.groceries_id], (4_000, 46_000))
        self.assertEqual(totals[self.dining_id], (2_000, 18_000))

    def test_split_parent_is_not_double_counted_and_can_be_removed(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-6_000)
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )

        self.repository.split_transaction(
            transaction_id=transaction_id,
            splits=(
                {"category_id": self.groceries_id, "amount_cents": 4_000},
                {"category_id": self.dining_id, "amount_cents": 2_000},
            ),
        )

        totals = self.category_totals()
        self.assertEqual(totals[self.groceries_id], (4_000, 46_000))
        self.assertEqual(totals[self.dining_id], (2_000, 18_000))

        self.repository.remove_transaction_split(transaction_id)

        detail = self.repository.get_transaction_detail(transaction_id)
        totals = self.category_totals()
        self.assertEqual(detail.categorization_status, "uncategorized")
        self.assertEqual(totals[self.groceries_id], (0, 50_000))
        self.assertEqual(totals[self.dining_id], (0, 20_000))

    def test_split_amounts_must_equal_original_transaction_amount(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-6_000)

        with self.assertRaisesRegex(ValueError, "Split amounts must equal"):
            self.repository.split_transaction(
                transaction_id=transaction_id,
                splits=(
                    {"category_id": self.groceries_id, "amount_cents": 4_000},
                    {"category_id": self.dining_id, "amount_cents": 1_500},
                ),
            )

        self.assertEqual(self.category_totals()[self.groceries_id], (0, 50_000))

    def test_archived_categories_are_rejected_in_split_lines(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-6_000)
        self.repository.update_category(category_id=self.dining_id, archived=True)

        with self.assertRaisesRegex(ValueError, "active"):
            self.repository.split_transaction(
                transaction_id=transaction_id,
                splits=(
                    {"category_id": self.groceries_id, "amount_cents": 4_000},
                    {"category_id": self.dining_id, "amount_cents": 2_000},
                ),
            )

        self.assertEqual(self.category_totals()[self.groceries_id], (0, 50_000))

    def test_ignored_transactions_do_not_affect_budget_spending(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-2_200)
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.gas_id,
        )

        self.repository.set_transaction_ignored(
            transaction_id=transaction_id,
            ignored=True,
            reason="Transfer",
        )

        detail = self.repository.get_transaction_detail(transaction_id)
        totals = self.category_totals()
        self.assertTrue(detail.transaction.ignored)
        self.assertEqual(detail.transaction.ignored_reason, "Transfer")
        self.assertEqual(detail.categorization_status, "ignored")
        self.assertEqual(totals[self.gas_id], (0, 15_000))

    def test_review_queue_filters_reviewed_ignored_and_uncategorized(self) -> None:
        uncategorized = self.import_transaction(plaid_transaction_id="filter-uncat")
        reviewed = self.import_transaction(plaid_transaction_id="filter-reviewed")
        ignored = self.import_transaction(plaid_transaction_id="filter-ignored")
        self.repository.mark_transaction_reviewed(reviewed, reviewed=True)
        self.repository.set_transaction_ignored(transaction_id=ignored, ignored=True, reason="Transfer")

        uncategorized_rows = self.repository.list_review_transactions(self.budget_month_id, status="uncategorized")
        reviewed_rows = self.repository.list_review_transactions(self.budget_month_id, status="reviewed")
        ignored_rows = self.repository.list_review_transactions(self.budget_month_id, status="ignored")

        self.assertEqual([item.transaction.id for item in uncategorized_rows], [uncategorized, reviewed])
        self.assertEqual([item.transaction.id for item in reviewed_rows], [reviewed])
        self.assertEqual([item.transaction.id for item in ignored_rows], [ignored])

    def test_unignored_transactions_do_not_restore_stale_category_assignments(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-2_200)
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.gas_id,
        )
        self.repository.set_transaction_ignored(
            transaction_id=transaction_id,
            ignored=True,
            reason="Transfer",
        )

        self.repository.set_transaction_ignored(transaction_id=transaction_id, ignored=False)

        detail = self.repository.get_transaction_detail(transaction_id)
        queue = self.repository.list_transaction_review_queue(self.budget_month_id)
        totals = self.category_totals()
        self.assertFalse(detail.transaction.ignored)
        self.assertFalse(detail.transaction.reviewed)
        self.assertIsNone(detail.transaction.ignored_reason)
        self.assertEqual(detail.categorization_status, "uncategorized")
        self.assertEqual(detail.assignments, ())
        self.assertEqual(totals[self.gas_id], (0, 15_000))
        self.assertEqual([item.transaction.id for item in queue], [transaction_id])

    def test_manual_spending_and_transaction_assignments_do_not_double_count(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-2_500)
        self.repository.record_spending(
            category_id=self.groceries_id,
            amount_cents=1_000,
            occurred_on=date(2026, 6, 20),
            note="Cash groceries",
        )

        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )

        self.assertEqual(self.category_totals()[self.groceries_id], (3_500, 46_500))

    def test_transaction_audit_metadata_is_preserved(self) -> None:
        transaction_id = self.import_transaction(
            amount_cents=-2_700,
            category_hint="Shops",
        )

        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.dining_id,
        )
        self.repository.mark_transaction_reviewed(transaction_id, reviewed=False)

        detail = self.repository.get_transaction_detail(transaction_id)
        event_types = [event["event_type"] for event in detail.audit_events]
        self.assertIn("imported", event_types)
        self.assertEqual(event_types.count("category_assigned"), 2)
        self.assertIn("marked_unreviewed", event_types)
        self.assertEqual(detail.transaction.category_hint, "Shops")
        self.assertEqual(detail.transaction.plaid_transaction_id, "txn-1")
        self.assertEqual(detail.assignments[0].source, "manual")
        self.assertEqual(detail.final_category_id, self.dining_id)

    def test_merchant_rule_can_be_updated_and_archived_without_losing_history(self) -> None:
        rule_id = self.repository.create_merchant_rule(
            household_id=self.household_id,
            merchant_match_text="fresh",
            category_id=self.groceries_id,
            priority=20,
        )

        self.repository.update_merchant_rule(
            rule_id=rule_id,
            merchant_match_text="fresh market",
            category_id=self.dining_id,
            priority=5,
            active=False,
        )

        inactive_rules = self.repository.list_merchant_rules(self.household_id, include_inactive=True)
        active_rules = self.repository.list_merchant_rules(self.household_id)
        self.assertEqual(inactive_rules[0].merchant_match_text, "fresh market")
        self.assertEqual(inactive_rules[0].category_id, self.dining_id)
        self.assertFalse(inactive_rules[0].active)
        self.assertEqual(active_rules, [])

        self.repository.delete_merchant_rule(rule_id=rule_id)

        inactive_rules = self.repository.list_merchant_rules(self.household_id, include_inactive=True)
        active_rules = self.repository.list_merchant_rules(self.household_id)
        self.assertEqual(len(inactive_rules), 1)
        self.assertEqual(inactive_rules[0].id, rule_id)
        self.assertFalse(inactive_rules[0].active)
        self.assertEqual(active_rules, [])

        events = self.repository.list_notification_events(household_id=self.household_id)
        event_types = [event.event_type for event in events]
        self.assertIn("merchant_rule_archived", event_types)

    def test_archived_merchant_rule_can_be_reactivated_without_bulk_apply(self) -> None:
        transaction_id = self.import_transaction(
            plaid_transaction_id="archived-rule-match",
            amount_cents=-2_147,
            merchant_name="Corner Store",
        )
        rule_id = self.repository.create_merchant_rule(
            household_id=self.household_id,
            merchant_match_text="corner store",
            category_id=self.groceries_id,
        )
        self.repository.update_merchant_rule(rule_id=rule_id, active=False)

        recreated_rule_id = self.repository.create_merchant_rule(
            household_id=self.household_id,
            merchant_match_text="Corner Store",
            category_id=self.groceries_id,
            priority=10,
        )

        self.assertEqual(recreated_rule_id, rule_id)
        rules = self.repository.list_merchant_rules(self.household_id)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, rule_id)
        self.assertEqual(rules[0].priority, 10)
        detail = self.repository.get_transaction_detail(transaction_id)
        self.assertEqual(detail.categorization_status, "uncategorized")
        self.assertIsNone(detail.final_category_id)
        self.assertEqual(detail.suggestion_source, "rule")

    def test_merchant_rule_cannot_target_archived_category(self) -> None:
        self.repository.update_category(category_id=self.groceries_id, archived=True)

        with self.assertRaisesRegex(ValueError, "active"):
            self.repository.create_merchant_rule(
                household_id=self.household_id,
                merchant_match_text="fresh",
                category_id=self.groceries_id,
            )

    def test_merchant_rule_can_explicitly_apply_to_current_unreviewed_matches(self) -> None:
        transaction_id = self.import_transaction(
            plaid_transaction_id="existing-rule-match",
            amount_cents=-5_500,
            merchant_name="Fresh Market #42",
        )

        self.repository.create_merchant_rule(
            household_id=self.household_id,
            merchant_match_text="fresh market",
            category_id=self.groceries_id,
            apply_to_existing_unreviewed=True,
        )

        detail = self.repository.get_transaction_detail(transaction_id)
        self.assertEqual(detail.categorization_status, "rule")
        self.assertEqual(detail.final_category_id, self.groceries_id)

    def test_transaction_actions_emit_sanitized_notification_events(self) -> None:
        transaction_id = self.import_transaction(amount_cents=-6_000)

        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.dining_id,
        )
        self.repository.split_transaction(
            transaction_id=transaction_id,
            splits=(
                {"category_id": self.groceries_id, "amount_cents": 4_000},
                {"category_id": self.dining_id, "amount_cents": 2_000},
            ),
        )
        self.repository.set_transaction_ignored(transaction_id=transaction_id, ignored=True, reason="Transfer")
        self.repository.set_transaction_ignored(transaction_id=transaction_id, ignored=False)
        self.repository.create_merchant_rule(
            household_id=self.household_id,
            merchant_match_text="fresh",
            category_id=self.groceries_id,
        )

        events = self.repository.list_notification_events(household_id=self.household_id)
        event_types = [event.event_type for event in events]
        serialized = "\n".join(str(event.metadata) for event in events)
        self.assertIn("transaction_category_assigned", event_types)
        self.assertIn("transaction_recategorized", event_types)
        self.assertIn("transaction_split", event_types)
        self.assertIn("transaction_ignored", event_types)
        self.assertIn("transaction_unignored", event_types)
        self.assertIn("merchant_rule_created", event_types)
        self.assertNotIn("access_token", serialized)
        self.assertNotIn("token_ref", serialized)


if __name__ == "__main__":
    unittest.main()
