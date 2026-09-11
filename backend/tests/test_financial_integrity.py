from __future__ import annotations

import tempfile
import sqlite3
import unittest
from dataclasses import asdict
from datetime import date
from pathlib import Path
from unittest.mock import patch

from backend.app.db import BudgetRepository, plaid_item_to_public_dict
from backend.app.plaid import (
    InMemoryPlaidTokenStore, PlaidConnectionService, PlaidTransactionSnapshot,
    PlaidTransactionSync, PlaidIntegrationError, money_cents, transaction_from_plaid_json,
)


class FinancialIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = BudgetRepository(Path(self.temp.name) / "synthetic.sqlite")
        self.repo.initialize()
        self.household = self.repo.create_household("Synthetic household")
        self.month = self.repo.create_budget_month(household_id=self.household, month="2026-01")
        self.repo.add_payday(household_id=self.household, payday_date=date(2026, 2, 15))
        self.group = self.repo.add_budget_group(budget_month_id=self.month, name="Everyday")
        self.food = self.repo.add_category(budget_group_id=self.group, name="Food", planned_cents=20_000)
        self.home = self.repo.add_category(budget_group_id=self.group, name="Home", planned_cents=10_000)
        self.tokens = InMemoryPlaidTokenStore()
        self.item = self.repo.create_plaid_item(
            household_id=self.household, plaid_item_id="synthetic-item",
            access_token_ref=self.tokens.store("synthetic-token"),
        )
        self.account = self.repo.upsert_connected_account(
            budget_month_id=self.month, plaid_item_id=self.item, plaid_account_id="synthetic-account",
            name="Synthetic checking", account_type="checking", balance_cents=100_000,
        )

    def snapshot(self, transaction_id: str = "purchase", amount: int = -1200, **changes) -> PlaidTransactionSnapshot:
        values = dict(
            plaid_transaction_id=transaction_id, plaid_account_id="synthetic-account",
            amount_cents=amount, occurred_on=date(2026, 1, 25), name="Market",
        ) | changes
        return PlaidTransactionSnapshot(**values)

    def save(self, snapshot: PlaidTransactionSnapshot) -> int:
        values = asdict(snapshot)
        values.pop("plaid_account_id")
        return self.repo.upsert_plaid_transaction(cash_account_id=self.account, **values).transaction_id

    def totals(self) -> dict[int, int]:
        summary = self.repo.get_summary(self.month, date(2026, 1, 25))
        detail = self.repo.get_budget_detail(self.month, date(2026, 1, 25))
        self.assertEqual(sum(category.spent_cents for category in summary.categories), detail["total_spent_cents"])
        return {category.id: category.spent_cents for category in summary.categories}

    def test_changed_single_assignment_reconciles_amount_and_preserves_category_history(self) -> None:
        transaction = self.save(self.snapshot())
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=self.food)
        self.save(self.snapshot(amount=-1573))
        detail = self.repo.get_transaction_detail(transaction)
        self.assertEqual(detail.final_category_id, self.food)
        self.assertEqual(detail.assignments[0].source, "manual")
        self.assertEqual(detail.assignments[0].amount_cents, 1573)
        self.assertTrue(detail.needs_review)
        self.assertEqual(self.totals()[self.food], 1573)
        with self.repo.connect() as connection:
            rows = connection.execute(
                "SELECT amount_cents, active FROM transaction_category_assignments WHERE transaction_id = ? ORDER BY id",
                (transaction,),
            ).fetchall()
        self.assertEqual([tuple(row) for row in rows], [(1200, 0), (1573, 1)])

    def test_changed_split_returns_to_review_without_guessing_allocation(self) -> None:
        transaction = self.save(self.snapshot())
        self.repo.split_transaction(transaction_id=transaction, splits=[
            {"category_id": self.food, "amount_cents": 1000},
            {"category_id": self.home, "amount_cents": 200},
        ])
        self.save(self.snapshot(amount=-1500))
        detail = self.repo.get_transaction_detail(transaction)
        self.assertEqual(detail.assignments, ())
        self.assertTrue(detail.needs_review)
        self.assertEqual(self.totals(), {self.food: 0, self.home: 0})
        with self.repo.connect() as connection:
            history = connection.execute(
                "SELECT SUM(amount_cents) FROM transaction_category_assignments WHERE transaction_id = ? AND active = 0",
                (transaction,),
            ).fetchone()[0]
        self.assertEqual(history, 1200)

    def test_same_sync_does_not_reapply_changed_rule_or_duplicate_audit(self) -> None:
        rule = self.repo.create_merchant_rule(household_id=self.household, merchant_match_text="market", category_id=self.food)
        transaction = self.save(self.snapshot())
        self.repo.mark_transaction_reviewed(transaction)
        before = self.repo.get_transaction_detail(transaction)
        self.repo.update_merchant_rule(rule_id=rule, category_id=self.home)
        self.save(self.snapshot())
        after = self.repo.get_transaction_detail(transaction)
        self.assertEqual(after.assignments, before.assignments)
        self.assertEqual(after.audit_events, before.audit_events)
        self.assertTrue(after.transaction.reviewed)
        self.assertEqual(self.totals(), {self.food: 1200, self.home: 0})

    def test_new_rule_does_not_bulk_apply_on_repeated_import(self) -> None:
        transaction = self.save(self.snapshot())
        self.repo.create_merchant_rule(household_id=self.household, merchant_match_text="market", category_id=self.food)
        self.save(self.snapshot())
        self.assertEqual(self.repo.get_transaction_detail(transaction).assignments, ())

    def test_incoming_and_zero_transactions_remain_visible_without_expense_assignments(self) -> None:
        self.repo.create_merchant_rule(household_id=self.household, merchant_match_text="market", category_id=self.food)
        for amount in (1200, 0):
            with self.subTest(amount=amount):
                transaction = self.save(self.snapshot(str(amount), amount=amount))
                self.assertEqual(self.repo.get_transaction_detail(transaction).assignments, ())
                with self.assertRaisesRegex(ValueError, "Only outgoing"):
                    self.repo.assign_transaction_category(transaction_id=transaction, category_id=self.food)
                with self.assertRaisesRegex(ValueError, "Only outgoing"):
                    self.repo.split_transaction(transaction_id=transaction, splits=[{"category_id": self.food, "amount_cents": 1200}])
        self.assertEqual(len(self.repo.list_transactions(self.account)), 2)
        self.assertEqual(self.totals(), {self.food: 0, self.home: 0})

    def test_outflow_changed_to_credit_clears_expense_and_preserves_history(self) -> None:
        transaction = self.save(self.snapshot())
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=self.food)
        self.save(self.snapshot(amount=1200))
        self.assertEqual(self.repo.get_transaction_detail(transaction).assignments, ())
        self.assertEqual(self.totals()[self.food], 0)

    def test_pending_posted_pair_preserves_manual_category_and_only_counts_once(self) -> None:
        pending = self.save(self.snapshot("pending", pending=True))
        self.repo.assign_transaction_category(transaction_id=pending, category_id=self.food)
        posted = self.snapshot("posted", amount=-1500, pending_transaction_id="pending")
        counts = self.repo.apply_plaid_transaction_sync(
            plaid_item_id=self.item, expected_cursor=None, next_cursor="posted-cursor",
            transactions=[asdict(posted)], removed_transaction_ids=["pending"],
        )
        detail = self.repo.get_transaction_detail(pending)
        self.assertEqual(detail.transaction.plaid_transaction_id, "posted")
        self.assertFalse(detail.transaction.pending)
        self.assertFalse(detail.transaction.ignored)
        self.assertEqual(detail.final_category_id, self.food)
        self.assertEqual(len(self.repo.list_transactions(self.account)), 1)
        self.assertEqual(self.totals()[self.food], 1500)
        self.assertEqual(counts["updated_transactions"], 1)
        self.assertIn("pending_posted", [event["event_type"] for event in detail.audit_events])

    def test_failed_batch_rolls_back_transactions_assignments_and_cursor(self) -> None:
        self.repo.create_merchant_rule(household_id=self.household, merchant_match_text="market", category_id=self.food)
        invalid = asdict(self.snapshot("invalid")) | {"name": None}
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.apply_plaid_transaction_sync(
                plaid_item_id=self.item, expected_cursor=None, next_cursor="bad-cursor",
                transactions=[asdict(self.snapshot()), invalid], removed_transaction_ids=[],
            )
        self.assertEqual(self.repo.list_transactions(self.account), [])
        self.assertEqual(self.totals()[self.food], 0)
        self.assertIsNone(self.repo.get_plaid_item(self.item).sync_cursor)

    def test_service_reports_rolled_back_failure_and_retry_commits_once(self) -> None:
        service = PlaidConnectionService(self.repo, token_store=self.tokens)
        invalid = self.snapshot("invalid", name=None)
        failed_batch = PlaidTransactionSync(transactions=(self.snapshot(), invalid), next_cursor="failed")
        with patch.object(service.client, "sync_transactions", return_value=failed_batch):
            failure = service.sync_transactions(self.item)
        self.assertFalse(failure.success)
        self.assertEqual(failure.error_code, "PLAID_SYNC_INVALID")
        self.assertEqual(self.repo.list_transactions(self.account), [])
        self.assertIsNone(self.repo.get_plaid_item(self.item).sync_cursor)
        retry = PlaidTransactionSync(transactions=(self.snapshot(),), next_cursor="success")
        with patch.object(service.client, "sync_transactions", return_value=retry):
            success = service.sync_transactions(self.item)
        self.assertTrue(success.success)
        self.assertEqual(len(self.repo.list_transactions(self.account)), 1)
        item = self.repo.get_plaid_item(self.item)
        self.assertEqual(item.sync_cursor, "success")
        self.assertIsNone(item.last_error_code)

    def test_unlabeled_provider_credentials_are_redacted_in_error_messages_and_codes(self) -> None:
        service = PlaidConnectionService(self.repo, token_store=self.tokens)
        sensitive = "access-sandbox-00000000-1111-2222-3333-444444444444"
        with patch.object(service.client, "sync_transactions", side_effect=PlaidIntegrationError(sensitive, sensitive)):
            failure = service.sync_transactions(self.item)
        self.assertEqual(failure.error_code, "PLAID_REQUEST_FAILED")
        self.assertNotIn(sensitive, str(asdict(failure)))
        self.assertNotIn(sensitive, str(self.repo.list_plaid_sync_errors(self.item)))
        # Already persisted provider text from an older version also stays private.
        self.repo.record_plaid_sync_error(plaid_item_id=self.item, sync_type="transaction", error_code=sensitive, error_message=sensitive)
        self.assertNotIn(sensitive, str(plaid_item_to_public_dict(self.repo.get_plaid_item(self.item))))

    def test_legacy_incoming_assignments_are_flagged_without_rewriting_history(self) -> None:
        transaction = self.save(self.snapshot(amount=1200))
        with self.repo.connect() as connection:
            connection.execute(
                """INSERT INTO transaction_category_assignments(transaction_id, budget_category_id, amount_cents, source)
                   VALUES (?, ?, 1200, 'manual')""", (transaction, self.food),
            )
        diagnostics = self.repo.app_diagnostics({"household_id": self.household, "user": {}, "household": {}})
        check = next(item for item in diagnostics["integrity"]["checks"] if item["name"] == "only_outflows_assigned")
        self.assertFalse(check["ok"])
        self.assertEqual(check["count"], 1)
        self.assertEqual(self.repo.get_transaction_detail(transaction).assignments[0].amount_cents, 1200)

    def test_archived_group_cannot_hide_new_moved_or_restored_categories(self) -> None:
        archived = self.repo.add_budget_group(budget_month_id=self.month, name="Archived")
        self.repo.update_budget_group(budget_group_id=archived, archived=True)
        with self.assertRaisesRegex(ValueError, "archived budget group"):
            self.repo.add_category(budget_group_id=archived, name="Hidden", planned_cents=1000)
        with self.assertRaisesRegex(ValueError, "archived budget group"):
            self.repo.update_category(category_id=self.food, budget_group_id=archived)
        self.repo.update_category(category_id=self.food, archived=True)
        self.repo.update_category(category_id=self.home, archived=True)
        self.repo.update_budget_group(budget_group_id=self.group, archived=True)
        with self.assertRaisesRegex(ValueError, "Restore the budget group"):
            self.repo.update_category(category_id=self.food, archived=False)

    def test_archived_category_history_is_not_a_diagnostic_integrity_error(self) -> None:
        transaction = self.save(self.snapshot())
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=self.food)
        self.repo.update_category(category_id=self.food, archived=True)
        diagnostics = self.repo.app_diagnostics({"household_id": self.household, "user": {}, "household": {}})
        check = next(item for item in diagnostics["integrity"]["checks"] if item["name"] == "archived_categories_unused")
        self.assertTrue(check["ok"])
        self.assertEqual(self.repo.get_transaction_detail(transaction).final_category_id, self.food)

    def test_legacy_users_upgrade_preserves_rows_and_creates_username_index(self) -> None:
        legacy = BudgetRepository(Path(self.temp.name) / "legacy.sqlite")
        with legacy.connect() as connection:
            connection.executescript("""
                CREATE TABLE households(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE users(id INTEGER PRIMARY KEY, household_id INTEGER, name TEXT,
                    email TEXT, role TEXT DEFAULT 'spouse', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                INSERT INTO households VALUES (1, 'Legacy synthetic household');
                INSERT INTO users(id, household_id, name, email) VALUES (1, 1, 'Synthetic user', 'synthetic@example.invalid');
            """)
        legacy.initialize()
        legacy.initialize()
        with legacy.connect() as connection:
            user = connection.execute("SELECT * FROM users WHERE id = 1").fetchone()
            index = connection.execute("SELECT name FROM sqlite_master WHERE name = 'idx_users_username'").fetchone()
        self.assertEqual(user["name"], "Synthetic user")
        self.assertIsNone(user["username"])
        self.assertIsNone(user["password_hash"])
        self.assertIsNotNone(index)

    def test_signed_cash_balances_preserve_overdraft_and_reject_fractional_cents(self) -> None:
        self.repo.update_cash_account(account_id=self.account, balance_cents=-1573)
        summary = self.repo.get_summary(self.month, date(2026, 1, 25))
        self.assertEqual(summary.included_account_balance_cents, -1573)
        result = self.repo.safe_to_spend(budget_month_id=self.month, category_id=self.food,
                                       purchase_amount_cents=1, today=date(2026, 1, 25))
        self.assertEqual(result.warning_level.value, "no")
        with self.assertRaises(ValueError):
            self.repo.update_cash_account(account_id=self.account, balance_cents=12.5)
        with self.assertRaises(ValueError):
            self.save(self.snapshot(amount=-(2**63)))

    def test_stale_sync_cannot_regress_cursor_or_overwrite_new_amount(self) -> None:
        self.repo.apply_plaid_transaction_sync(
            plaid_item_id=self.item, expected_cursor=None, next_cursor="new",
            transactions=[asdict(self.snapshot(amount=-1700))], removed_transaction_ids=[],
        )
        with self.assertRaisesRegex(ValueError, "finished first"):
            self.repo.apply_plaid_transaction_sync(
                plaid_item_id=self.item, expected_cursor=None, next_cursor="old",
                transactions=[asdict(self.snapshot())], removed_transaction_ids=[],
            )
        self.assertEqual(self.repo.list_transactions(self.account)[0].amount_cents, -1700)
        self.assertEqual(self.repo.get_plaid_item(self.item).sync_cursor, "new")

    def test_item_scoped_removal_and_account_identity_are_enforced(self) -> None:
        transaction = self.save(self.snapshot())
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=self.food)
        other_item = self.repo.create_plaid_item(household_id=self.household, plaid_item_id="other-item", access_token_ref="other-ref")
        self.assertFalse(self.repo.mark_plaid_transaction_removed("purchase", plaid_item_id=other_item))
        other_account = self.repo.add_cash_account(budget_month_id=self.month, name="Other", account_type="checking", balance_cents=1)
        values = asdict(self.snapshot())
        values.pop("plaid_account_id")
        with self.assertRaisesRegex(ValueError, "another account"):
            self.repo.upsert_plaid_transaction(cash_account_id=other_account, **values)
        self.assertEqual(self.totals()[self.food], 1200)

    def test_removed_transaction_cannot_restore_stale_assignments_when_unignored(self) -> None:
        transaction = self.save(self.snapshot())
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=self.food)
        self.repo.mark_plaid_transaction_removed("purchase", plaid_item_id=self.item)
        self.repo.set_transaction_ignored(transaction_id=transaction, ignored=False)
        self.assertEqual(self.repo.get_transaction_detail(transaction).assignments, ())
        self.assertEqual(self.totals()[self.food], 0)

    def test_copy_forward_keeps_plan_resets_received_and_clamps_bill_date(self) -> None:
        self.repo.add_income(budget_month_id=self.month, name="Salary", kind="main", planned_cents=300_000, received_cents=300_000)
        self.repo.add_income(budget_month_id=self.month, name="Extra", kind="sporadic", planned_cents=20_000, received_cents=12_345)
        self.repo.add_expected_bill(budget_month_id=self.month, name="Bill", amount_cents=7000, due_on=date(2026, 1, 31), paid=True)
        copied = self.repo.create_budget_month(household_id=self.household, month="2026-02", copy_from_budget_month_id=self.month)
        before = self.repo.get_budget_detail(self.month, date(2026, 1, 25))
        after = self.repo.get_budget_detail(copied, date(2026, 2, 1))
        self.assertEqual(before["income_available_cents"], 312_345)
        self.assertEqual(after["income_available_cents"], 300_000)
        self.assertEqual([line["received_cents"] for line in after["income"]], [0, 0])
        self.assertEqual([line["planned_cents"] for line in after["income"]], [300_000, 20_000])
        self.assertEqual(after["expected_bills"][0]["due_on"], "2026-02-28")
        self.assertFalse(after["expected_bills"][0]["paid"])

    def test_account_relink_preserves_inclusion_and_cannot_move_history(self) -> None:
        self.repo.set_account_included(self.account, False)
        values = dict(budget_month_id=self.month, plaid_item_id=self.item, plaid_account_id="synthetic-account",
                      name="Synthetic checking", account_type="checking", balance_cents=90_000)
        self.repo.upsert_connected_account(**values)
        self.assertFalse(self.repo.list_accounts(self.month)[0].included_in_cash_reality)
        next_month = self.repo.create_budget_month(household_id=self.household, month="2026-02")
        with self.assertRaisesRegex(ValueError, "history cannot be moved"):
            self.repo.upsert_connected_account(**(values | {"budget_month_id": next_month}))
        self.assertEqual(len(self.repo.list_accounts(self.month)), 1)

    def test_noncanonical_month_and_noninteger_cents_are_rejected(self) -> None:
        for month in ("2026-1", "2026-001", "26-01", "2026-13", "0000-01"):
            with self.subTest(month=month), self.assertRaises(ValueError):
                self.repo.create_budget_month(household_id=self.household, month=month)
        for amount in (True, 12.5, "12", 2**63):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.repo.add_category(budget_group_id=self.group, name="Invalid", planned_cents=amount)

    def test_plaid_money_rounding_sign_and_pending_link_are_explicit(self) -> None:
        self.assertEqual(money_cents("12.345"), 1235)
        self.assertEqual(money_cents("-12.345"), -1235)
        parsed = transaction_from_plaid_json({
            "transaction_id": "posted", "account_id": "synthetic-account", "amount": "15.73",
            "date": "2026-01-25", "pending_transaction_id": "pending", "pending": False,
        })
        self.assertEqual(parsed.amount_cents, -1573)
        self.assertEqual(parsed.pending_transaction_id, "pending")


if __name__ == "__main__":
    unittest.main()
