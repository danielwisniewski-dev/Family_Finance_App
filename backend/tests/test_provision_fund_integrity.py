"""Independent fund accounting regressions using disposable, synthetic household data."""
from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from backend.app.db import BudgetRepository
from backend.app.plaid import PlaidTransactionSnapshot


class ProvisionFundIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = BudgetRepository(Path(self.temp.name) / "synthetic-funds.sqlite")
        self.repo.initialize()
        self.today = date(2026, 1, 25)
        for target in ("backend.app.db.household_today", "backend.app.funds.household_today"):
            clock = patch(target, return_value=self.today)
            clock.start()
            self.addCleanup(clock.stop)
        self.household = self.repo.create_household("Synthetic fund household")
        self.month = self.repo.create_budget_month(
            household_id=self.household, month=self.today.strftime("%Y-%m"),
            low_cushion_daily_cents=0,
        )
        self.group = self.repo.add_budget_group(budget_month_id=self.month, name="Everyday")
        self.ordinary = self.repo.add_category(
            budget_group_id=self.group, name="Ordinary spending", planned_cents=100_000,
        )
        self.repo.add_payday(household_id=self.household, payday_date=self.today + timedelta(days=10))
        self.item = self.repo.create_plaid_item(
            household_id=self.household, plaid_item_id="synthetic-fund-item",
            access_token_ref="synthetic-fund-reference",
        )
        self.account = self.account_snapshot(100_000)
        self._entry_number = 0

    def account_snapshot(self, balance, *, included=True, account_key="synthetic-fund-checking"):
        return self.repo.upsert_connected_account(
            budget_month_id=self.month, plaid_item_id=self.item, plaid_account_id=account_key,
            name="Synthetic checking", account_type="checking", balance_cents=balance,
            available_balance_cents=balance, current_balance_cents=balance,
            included_in_cash_reality=included,
        )

    def fund(self, name="Home provision", *, account_id=None, plan=5_000):
        return self.repo.create_fund(
            budget_month_id=self.month, name=name, backing_account_id=account_id or self.account,
            monthly_plan_cents=plan,
        )

    def contribute(self, fund, amount, *, key=None, kind="contribution", repo=None):
        self._entry_number += 1
        return (repo or self.repo).add_fund_entry(
            fund_id=fund["id"], budget_month_id=self.month, kind=kind,
            amount_cents=amount, occurred_on=self.today,
            idempotency_key=key or f"synthetic-entry-{self._entry_number}",
        )

    def state(self, fund, *, month=None):
        return next(row for row in self.repo.get_funds(month or self.month, self.today)["funds"]
                    if row["id"] == fund["id"])

    def transaction(self, key="synthetic-purchase", amount=-3_000, **changes):
        snapshot = PlaidTransactionSnapshot(**({
            "plaid_transaction_id": key, "plaid_account_id": "synthetic-fund-checking",
            "amount_cents": amount, "occurred_on": self.today, "name": "Synthetic store",
        } | changes))
        fields = asdict(snapshot)
        fields.pop("plaid_account_id")
        return self.repo.upsert_plaid_transaction(cash_account_id=self.account, **fields).transaction_id

    def category(self, category_id, *, month=None):
        return next(row for row in self.repo.get_summary(month or self.month, self.today).categories
                    if row.id == category_id)

    def ordinary_spending_check(self, amount=100):
        return self.repo.safe_to_spend(
            budget_month_id=self.month, category_id=self.ordinary,
            purchase_amount_cents=amount, today=self.today,
        )

    def next_month(self):
        following = (self.today.replace(day=28) + timedelta(days=4)).replace(day=1)
        return self.repo.create_budget_month(
            household_id=self.household, month=following.strftime("%Y-%m"),
            copy_from_budget_month_id=self.month,
        ), following

    def test_monthly_plan_starts_at_zero_and_actual_contribution_is_not_an_expense(self):
        before = self.repo.get_summary(self.month, self.today)
        fund = self.fund(plan=5_000)
        self.assertEqual(self.state(fund)["balance_cents"], 0)
        planned = self.repo.get_summary(self.month, self.today)
        self.assertEqual(planned.planned_cents - before.planned_cents, 5_000)
        self.assertEqual(planned.included_account_balance_cents, before.included_account_balance_cents)
        self.contribute(fund, 12_000)
        self.assertEqual(self.state(fund)["balance_cents"], 12_000)
        self.assertEqual(self.state(fund)["contributed_this_month_cents"], 12_000)
        self.assertEqual(self.category(fund["category_id"]).spent_cents, 0)
        self.assertEqual(self.category(fund["category_id"]).remaining_cents, 12_000)
        self.assertEqual(self.repo.get_summary(self.month, self.today).planned_cents, planned.planned_cents)

    def test_setup_replaces_one_plan_without_moving_old_expenses_into_new_funds(self):
        self.repo.update_category(category_id=self.ordinary, planned_cents=7_000)
        transaction = self.transaction(amount=-2_000)
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=self.ordinary, reviewed=True)
        overview = self.repo.setup_funds(
            budget_month_id=self.month, backing_account_id=self.account,
            replace_category_id=self.ordinary, funds=[
                {"name": "First provision", "monthly_plan_cents": 2_000},
                {"name": "Second provision", "monthly_plan_cents": 5_000},
            ],
        )
        self.assertEqual(self.repo.get_summary(self.month, self.today).planned_cents, 7_000)
        self.assertEqual(self.category(self.ordinary).planned_cents, 0)
        self.assertEqual(self.category(self.ordinary).spent_cents, 2_000)
        self.assertEqual(self.repo.get_transaction_detail(transaction).final_category_id, self.ordinary)
        self.assertEqual([fund["balance_cents"] for fund in overview["funds"]], [0, 0])

    def test_invalid_setup_rolls_back_replaced_plan_and_all_partial_funds(self):
        with self.assertRaises(ValueError):
            self.repo.setup_funds(
                budget_month_id=self.month, backing_account_id=self.account,
                replace_category_id=self.ordinary, funds=[
                    {"name": "Valid first provision", "monthly_plan_cents": 2_000},
                    {"name": "Invalid provision", "monthly_plan_cents": -100},
                ],
            )
        self.assertEqual(self.category(self.ordinary).planned_cents, 100_000)
        self.assertEqual(self.repo.get_funds(self.month, self.today)["funds"], [])

    def test_replaying_contribution_is_once_and_changed_payload_is_rejected(self):
        fund = self.fund()
        self.contribute(fund, 5_000, key="synthetic-retry")
        self.contribute(fund, 5_000, key="synthetic-retry")
        with self.assertRaises((ValueError, PermissionError)):
            self.contribute(fund, 6_000, key="synthetic-retry")
        with self.assertRaises((ValueError, PermissionError)):
            self.contribute(fund, 5_000, key="synthetic-retry", kind="release")
        self.assertEqual(self.state(fund)["balance_cents"], 5_000)

    def test_replay_after_cash_drop_does_not_attempt_to_reserve_money_again(self):
        fund = self.fund()
        self.contribute(fund, 5_000, key="synthetic-completed-before-drop")
        self.account_snapshot(1_000)
        self.contribute(fund, 5_000, key="synthetic-completed-before-drop")
        self.assertEqual(self.state(fund)["balance_cents"], 5_000)
        self.assertEqual(self.state(fund)["contributed_this_month_cents"], 5_000)

    def test_invalid_contributions_cannot_manufacture_funds(self):
        fund = self.fund()
        for invalid in (0, -100, True, 1.5, "100"):
            with self.subTest(amount=invalid), self.assertRaises((ValueError, TypeError)):
                self.contribute(fund, invalid)
        with self.assertRaises(ValueError):
            self.repo.add_fund_entry(
                fund_id=fund["id"], budget_month_id=self.month, kind="contribution",
                amount_cents=100, occurred_on=self.today + timedelta(days=1),
                idempotency_key="synthetic-future-entry",
            )
        with self.assertRaises(ValueError):
            self.contribute(fund, 100, kind="transfer_in")
        self.assertEqual(self.state(fund)["balance_cents"], 0)

    def test_plan_edit_updates_one_allocation_and_cannot_create_real_spending(self):
        fund = self.fund()
        self.contribute(fund, 8_000)
        self.repo.update_fund(fund_id=fund["id"], budget_month_id=self.month, monthly_plan_cents=7_000)
        self.assertEqual(self.repo.get_summary(self.month, self.today).planned_cents, 107_000)
        self.assertEqual(self.category(fund["category_id"]).planned_cents, 7_000)
        self.assertEqual(self.state(fund)["balance_cents"], 8_000)
        with self.assertRaises(ValueError):
            self.repo.record_spending(category_id=fund["category_id"], amount_cents=100, occurred_on=self.today)
        self.assertEqual(self.state(fund)["balance_cents"], 8_000)

    def test_parallel_replays_commit_a_single_contribution(self):
        fund = self.fund()
        start = threading.Barrier(4)

        def save(_):
            repository = BudgetRepository(self.repo.db_path)
            start.wait(timeout=5)
            return repository.add_fund_entry(
                fund_id=fund["id"], budget_month_id=self.month, kind="contribution",
                amount_cents=5_000, occurred_on=self.today, idempotency_key="synthetic-parallel-retry",
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(save, range(4)))
        self.assertEqual(self.state(fund)["balance_cents"], 5_000)
        self.assertEqual(self.state(fund)["contributed_this_month_cents"], 5_000)

    def test_parallel_conflicting_replay_has_exactly_one_winner(self):
        fund = self.fund()
        start = threading.Barrier(2)

        def save(amount):
            repository = BudgetRepository(self.repo.db_path)
            start.wait(timeout=5)
            try:
                repository.add_fund_entry(
                    fund_id=fund["id"], budget_month_id=self.month, kind="contribution",
                    amount_cents=amount, occurred_on=self.today, idempotency_key="synthetic-conflict",
                )
                return amount
            except (ValueError, PermissionError):
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, (5_000, 7_000)))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.state(fund)["balance_cents"], winners[0])

    def test_parallel_contributions_cannot_spend_the_same_backing_cash(self):
        self.account_snapshot(10_000)
        first, second = self.fund("First"), self.fund("Second")
        start = threading.Barrier(2)

        def save(fund):
            repository = BudgetRepository(self.repo.db_path)
            start.wait(timeout=5)
            try:
                repository.add_fund_entry(
                    fund_id=fund["id"], budget_month_id=self.month, kind="contribution",
                    amount_cents=7_000, occurred_on=self.today,
                    idempotency_key=f"synthetic-cash-race-{fund['id']}",
                )
                return True
            except (ValueError, PermissionError):
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, (first, second)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.state(first)["balance_cents"] + self.state(second)["balance_cents"], 7_000)

    def test_split_reassignment_and_ignore_recompute_one_real_expense(self):
        fund = self.fund()
        self.contribute(fund, 10_000)
        transaction = self.transaction()
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=fund["category_id"], reviewed=True)
        self.assertEqual(self.state(fund)["balance_cents"], 7_000)
        self.repo.split_transaction(transaction_id=transaction, splits=[
            {"category_id": fund["category_id"], "amount_cents": 1_000},
            {"category_id": self.ordinary, "amount_cents": 2_000},
        ], reviewed=True)
        self.assertEqual(self.state(fund)["balance_cents"], 9_000)
        self.assertEqual(self.state(fund)["spent_this_month_cents"], 1_000)
        self.assertEqual(self.category(fund["category_id"]).spent_cents + self.category(self.ordinary).spent_cents, 3_000)
        self.repo.set_transaction_ignored(transaction_id=transaction, ignored=True)
        self.assertEqual(self.state(fund)["balance_cents"], 10_000)
        self.repo.set_transaction_ignored(transaction_id=transaction, ignored=False)
        self.assertEqual(self.state(fund)["balance_cents"], 10_000)
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=fund["category_id"], reviewed=True)
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=self.ordinary, reviewed=True)
        self.assertEqual(self.state(fund)["balance_cents"], 10_000)

    def test_modified_split_returns_reserve_until_person_recategorizes(self):
        fund = self.fund()
        self.contribute(fund, 10_000)
        transaction = self.transaction()
        self.repo.split_transaction(transaction_id=transaction, splits=[
            {"category_id": fund["category_id"], "amount_cents": 1_000},
            {"category_id": self.ordinary, "amount_cents": 2_000},
        ], reviewed=True)
        self.transaction(amount=-4_000)
        self.assertTrue(self.repo.get_transaction_detail(transaction).needs_review)
        self.assertEqual(self.state(fund)["balance_cents"], 10_000)
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=fund["category_id"], reviewed=True)
        self.assertEqual(self.state(fund)["balance_cents"], 6_000)
        self.transaction(amount=-4_500)
        self.assertEqual(self.state(fund)["balance_cents"], 5_500)
        self.transaction(amount=4_500)
        self.assertEqual(self.state(fund)["balance_cents"], 10_000)

    def test_pending_posted_replacement_and_removal_count_once(self):
        fund = self.fund()
        self.contribute(fund, 10_000)
        transaction = self.transaction("synthetic-pending", amount=-3_000, pending=True)
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=fund["category_id"], reviewed=True)
        posted = PlaidTransactionSnapshot(
            plaid_transaction_id="synthetic-posted", plaid_account_id="synthetic-fund-checking",
            amount_cents=-3_500, occurred_on=self.today, name="Synthetic store",
            pending_transaction_id="synthetic-pending",
        )
        self.repo.apply_plaid_transaction_sync(
            plaid_item_id=self.item, expected_cursor=None, next_cursor="synthetic-posted-cursor",
            transactions=[asdict(posted)], removed_transaction_ids=["synthetic-pending"],
        )
        self.assertEqual(len(self.repo.list_transactions(self.account)), 1)
        self.assertEqual(self.state(fund)["balance_cents"], 6_500)
        self.repo.apply_plaid_transaction_sync(
            plaid_item_id=self.item, expected_cursor="synthetic-posted-cursor", next_cursor="synthetic-removed-cursor",
            transactions=[], removed_transaction_ids=["synthetic-posted"],
        )
        self.assertEqual(self.state(fund)["balance_cents"], 10_000)

    def test_refund_counts_once_and_ignore_or_bank_amount_change_removes_credit(self):
        fund = self.fund()
        self.contribute(fund, 10_000)
        purchase = self.transaction()
        self.repo.assign_transaction_category(transaction_id=purchase, category_id=fund["category_id"], reviewed=True)
        refund = self.transaction("synthetic-refund", amount=1_000)
        self.repo.assign_transaction_refund(refund, fund["category_id"])
        self.repo.assign_transaction_refund(refund, fund["category_id"])
        self.assertEqual(self.state(fund)["balance_cents"], 8_000)
        self.transaction("synthetic-refund", amount=1_200)
        self.assertEqual(self.state(fund)["balance_cents"], 7_000)
        self.repo.assign_transaction_refund(refund, fund["category_id"])
        self.assertEqual(self.state(fund)["balance_cents"], 8_200)
        self.repo.set_transaction_ignored(transaction_id=refund, ignored=True)
        self.assertEqual(self.state(fund)["balance_cents"], 7_000)

    def test_month_copy_keeps_carryover_and_plan_without_repeating_contribution(self):
        fund = self.fund(plan=5_000)
        self.contribute(fund, 12_000)
        transaction = self.transaction()
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=fund["category_id"], reviewed=True)
        copied, _ = self.next_month()
        carried = self.state(fund, month=copied)
        self.assertEqual(carried["balance_cents"], 9_000)
        self.assertEqual(carried["monthly_plan_cents"], 5_000)
        self.assertEqual(carried["contributed_this_month_cents"], 0)
        self.assertEqual(carried["spent_this_month_cents"], 0)
        self.assertNotEqual(carried["category_id"], fund["category_id"])
        self.assertEqual(self.category(carried["category_id"], month=copied).remaining_cents, 9_000)
        self.assertEqual(self.repo.get_summary(copied, self.today).planned_cents, 105_000)

    def test_posting_across_month_clears_old_allocation_before_new_fund_assignment(self):
        fund = self.fund()
        self.contribute(fund, 10_000)
        transaction = self.transaction()
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=fund["category_id"], reviewed=True)
        copied, following = self.next_month()
        self.transaction(occurred_on=following)
        self.assertEqual(self.state(fund)["balance_cents"], 10_000)
        target = self.state(fund, month=copied)
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=target["category_id"], reviewed=True)
        self.assertEqual(self.state(fund)["balance_cents"], 7_000)
        self.assertEqual(self.state(fund, month=copied)["spent_this_month_cents"], 3_000)
        self.assertEqual(self.state(fund)["spent_this_month_cents"], 0)

    def test_archived_fund_preserves_reserve_and_historical_expense(self):
        fund = self.fund()
        self.contribute(fund, 10_000)
        transaction = self.transaction()
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=fund["category_id"], reviewed=True)
        self.repo.update_fund(fund_id=fund["id"], budget_month_id=self.month, archived=True)
        self.assertEqual(self.state(fund)["balance_cents"], 7_000)
        self.assertEqual(self.repo.get_funds(self.month, self.today)["reserved_included_cents"], 7_000)
        with self.assertRaises((ValueError, PermissionError)):
            self.contribute(fund, 100)
        new_transaction = self.transaction("synthetic-after-archive", amount=-100)
        with self.assertRaises(ValueError):
            self.repo.assign_transaction_category(transaction_id=new_transaction, category_id=fund["category_id"])

    def test_archive_cannot_be_bypassed_by_a_copied_or_restored_budget_category(self):
        fund = self.fund()
        self.contribute(fund, 10_000)
        copied, _ = self.next_month()
        copied_category = self.state(fund, month=copied)["category_id"]
        self.repo.update_fund(fund_id=fund["id"], budget_month_id=self.month, archived=True)
        with self.assertRaises((ValueError, LookupError)):
            self.repo.safe_to_spend(
                budget_month_id=copied, category_id=copied_category,
                purchase_amount_cents=100, today=self.today,
            )
        # A generic category editor must not bypass the fund's archived state.
        try:
            self.repo.update_category(category_id=fund["category_id"], archived=False)
        except ValueError:
            pass
        with self.assertRaises((ValueError, LookupError)):
            self.repo.safe_to_spend(
                budget_month_id=self.month, category_id=fund["category_id"],
                purchase_amount_cents=100, today=self.today,
            )
        self.assertEqual(self.state(fund)["balance_cents"], 10_000)

    def test_positive_reserves_are_not_cancelled_by_an_overspent_fund(self):
        first, second = self.fund("First"), self.fund("Second")
        self.contribute(first, 5_000)
        self.contribute(second, 10_000)
        transaction = self.transaction(amount=-8_000)
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=first["category_id"], reviewed=True)
        self.assertEqual(self.state(first)["balance_cents"], -3_000)
        self.assertEqual(self.repo.get_funds(self.month, self.today)["reserved_included_cents"], 10_000)
        with self.assertRaises(ValueError):
            self.ordinary_spending_check()

    def test_ordinary_spending_protects_reserves_and_fund_purchase_can_use_its_own(self):
        first, second = self.fund("First"), self.fund("Second")
        self.contribute(first, 20_000)
        self.contribute(second, 30_000)
        ordinary = self.ordinary_spending_check(5_000)
        self.assertEqual(ordinary.cash_after_purchase_and_bills_cents, 45_000)
        own = self.repo.safe_to_spend(
            budget_month_id=self.month, category_id=first["category_id"],
            purchase_amount_cents=5_000, today=self.today,
        )
        self.assertTrue(own.budget_line_fits)
        self.assertEqual(own.category_remaining_after_cents, 15_000)
        self.assertEqual(own.cash_after_purchase_and_bills_cents, 50_000)
        self.assertIn("After upcoming bills, you would have about", own.required_phrase)

    def test_cash_drop_blocks_spending_without_rewriting_saved_fund_balance(self):
        fund = self.fund()
        self.contribute(fund, 40_000)
        self.account_snapshot(20_000)
        self.assertEqual(self.state(fund)["balance_cents"], 40_000)
        self.assertTrue(self.repo.get_funds(self.month, self.today)["issues"])
        with self.assertRaises(ValueError):
            self.ordinary_spending_check()
        with self.assertRaises((ValueError, PermissionError)):
            self.contribute(fund, 100)

    def test_excluded_backing_cash_is_not_subtracted_twice(self):
        separate = self.account_snapshot(20_000, included=False, account_key="synthetic-separate-checking")
        fund = self.fund(account_id=separate)
        self.contribute(fund, 10_000)
        self.assertEqual(self.repo.get_funds(self.month, self.today)["reserved_included_cents"], 0)
        self.assertEqual(self.ordinary_spending_check(1_000).cash_after_purchase_and_bills_cents, 99_000)
        self.repo.set_account_included(separate, True)
        self.assertEqual(self.repo.get_funds(self.month, self.today)["reserved_included_cents"], 10_000)
        self.assertEqual(self.ordinary_spending_check(1_000).cash_after_purchase_and_bills_cents, 109_000)

    def test_funded_upcoming_bill_is_not_reserved_again(self):
        fund = self.fund()
        self.contribute(fund, 20_000)
        self.repo.add_expected_bill(
            budget_month_id=self.month, name="Synthetic fund bill", amount_cents=6_000,
            due_on=self.today + timedelta(days=1), reserve_fund_id=fund["id"],
        )
        self.assertEqual(self.ordinary_spending_check(1_000).cash_after_purchase_and_bills_cents, 79_000)
        self.repo.add_expected_bill(
            budget_month_id=self.month, name="Synthetic ordinary bill", amount_cents=4_000,
            due_on=self.today + timedelta(days=2),
        )
        self.assertEqual(self.ordinary_spending_check(1_000).cash_after_purchase_and_bills_cents, 75_000)

    def test_multiple_bills_share_fund_coverage_once_and_reserve_the_unfunded_remainder(self):
        fund = self.fund()
        self.contribute(fund, 10_000)
        for offset in (1, 2):
            self.repo.add_expected_bill(
                budget_month_id=self.month, name=f"Synthetic funded bill {offset}", amount_cents=8_000,
                due_on=self.today + timedelta(days=offset), reserve_fund_id=fund["id"],
            )
        self.assertEqual(self.ordinary_spending_check(1_000).cash_after_purchase_and_bills_cents, 83_000)

    def test_transfer_and_release_preserve_total_reserve_without_creating_expenses(self):
        first, second = self.fund("First"), self.fund("Second")
        self.contribute(first, 10_000)
        payload = dict(
            source_fund_id=first["id"], target_fund_id=second["id"], budget_month_id=self.month,
            amount_cents=3_000, occurred_on=self.today, idempotency_key="synthetic-transfer",
        )
        self.repo.transfer_funds(**payload)
        self.repo.transfer_funds(**payload)
        self.assertEqual(self.state(first)["balance_cents"], 7_000)
        self.assertEqual(self.state(second)["balance_cents"], 3_000)
        self.contribute(second, 1_000, kind="release")
        self.assertEqual(self.repo.get_funds(self.month, self.today)["reserved_included_cents"], 9_000)
        self.assertEqual(self.category(first["category_id"]).spent_cents, 0)
        self.assertEqual(self.category(second["category_id"]).spent_cents, 0)

    def test_foreign_fund_account_month_and_transfer_are_rejected_without_changes(self):
        own = self.fund()
        self.contribute(own, 10_000)
        other_household = self.repo.create_household("Other synthetic household")
        other_month = self.repo.create_budget_month(household_id=other_household, month=self.today.strftime("%Y-%m"))
        other_account = self.repo.add_cash_account(
            budget_month_id=other_month, name="Other checking", account_type="checking", balance_cents=50_000,
        )
        foreign = self.repo.create_fund(
            budget_month_id=other_month, name="Foreign fund", backing_account_id=other_account,
            monthly_plan_cents=5_000,
        )
        actions = [
            lambda: self.repo.create_fund(budget_month_id=self.month, name="Invalid", backing_account_id=other_account, monthly_plan_cents=0),
            lambda: self.repo.update_fund(fund_id=own["id"], budget_month_id=other_month, name="Invalid"),
            lambda: self.repo.update_fund(fund_id=foreign["id"], budget_month_id=self.month, name="Invalid"),
            lambda: self.repo.add_fund_entry(fund_id=foreign["id"], budget_month_id=self.month, kind="contribution", amount_cents=100, occurred_on=self.today, idempotency_key="synthetic-foreign-entry"),
            lambda: self.repo.transfer_funds(source_fund_id=own["id"], target_fund_id=foreign["id"], budget_month_id=self.month, amount_cents=100, occurred_on=self.today, idempotency_key="synthetic-foreign-transfer"),
            lambda: self.repo.add_expected_bill(budget_month_id=self.month, name="Invalid bill", amount_cents=100, due_on=self.today, reserve_fund_id=foreign["id"]),
        ]
        for action in actions:
            with self.subTest(action=actions.index(action)), self.assertRaises((ValueError, PermissionError, LookupError)):
                action()
        self.assertEqual(self.state(own)["balance_cents"], 10_000)
        self.assertEqual(self.state(foreign, month=other_month)["balance_cents"], 0)
        self.assertEqual(len(self.repo.get_funds(self.month, self.today)["funds"]), 1)

    def test_foreign_actor_cannot_be_attributed_to_any_provision_mutation(self):
        first, second = self.fund("First"), self.fund("Second")
        self.contribute(first, 10_000)
        other_household = self.repo.create_household("Foreign synthetic actors")
        foreign_actor = self.repo.create_local_user(
            household_id=other_household, name="Foreign actor", username="synthetic-foreign-actor",
            email=None, password="synthetic-password",
        )
        actions = [
            lambda: self.repo.create_fund(budget_month_id=self.month, name="Invalid", backing_account_id=self.account, monthly_plan_cents=100, actor_user_id=foreign_actor),
            lambda: self.repo.update_fund(fund_id=first["id"], budget_month_id=self.month, monthly_plan_cents=100, actor_user_id=foreign_actor),
            lambda: self.repo.add_fund_entry(fund_id=first["id"], budget_month_id=self.month, kind="contribution", amount_cents=100, occurred_on=self.today, idempotency_key="synthetic-foreign-actor-entry", actor_user_id=foreign_actor),
            lambda: self.repo.transfer_funds(source_fund_id=first["id"], target_fund_id=second["id"], budget_month_id=self.month, amount_cents=100, occurred_on=self.today, idempotency_key="synthetic-foreign-actor-transfer", actor_user_id=foreign_actor),
        ]
        for index, action in enumerate(actions):
            with self.subTest(action=index), self.assertRaises((ValueError, PermissionError, LookupError)):
                action()
        self.assertEqual(self.state(first)["balance_cents"], 10_000)
        self.assertEqual(self.state(second)["balance_cents"], 0)
        self.assertEqual(self.state(first)["monthly_plan_cents"], 5_000)


if __name__ == "__main__":
    unittest.main()
