"""Provision metadata, cash protection and migration tests using synthetic money."""
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app import migrations
from backend.app.bank_data import bank_status
from backend.app.db import BudgetRepository
from backend.app.security import RuntimeSettings


class ProvisionFundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = BudgetRepository(Path(self.temp.name) / "synthetic.sqlite")
        self.repo.initialize()
        self.today = date(2026, 2, 8)
        clock = patch("backend.app.funds.household_today", return_value=self.today)
        clock.start()
        self.addCleanup(clock.stop)
        self.household = self.repo.create_household("Synthetic provision household", [{"name": "Member"}])
        with self.repo.connect() as connection:
            self.actor = connection.execute("SELECT id FROM users WHERE household_id=?", (self.household,)).fetchone()[0]
        self.month = self.repo.create_budget_month(household_id=self.household, month="2026-02", low_cushion_daily_cents=0)
        self.account = self.repo.add_cash_account(budget_month_id=self.month, name="Synthetic checking", account_type="checking", balance_cents=100_000)
        self.repo.add_payday(household_id=self.household, payday_date=self.today+timedelta(days=7))
        self.fund = self.repo.create_fund(budget_month_id=self.month, name="Annual costs", backing_account_id=self.account,
            monthly_plan_cents=3_500, annual_target_cents=42_000, timing_note="Several renewals",
            breakdown=[{"name": "Example subscription", "annual_cents": 12_000, "timing_note": "October"},
                       {"name": "Example annual service", "annual_cents": 30_000}], actor_user_id=self.actor)

    def contribute(self, amount=1_000, **changes):
        return self.repo.add_fund_entry(**({"fund_id": self.fund["id"], "budget_month_id": self.month,
            "kind": "contribution", "amount_cents": amount, "occurred_on": self.today,
            "idempotency_key": "synthetic-contribution", "actor_user_id": self.actor} | changes))

    def test_metadata_and_annual_breakdown_are_plans_not_cash(self):
        self.assertEqual(self.fund["balance_cents"], 0)
        self.assertEqual(self.fund["monthly_shortfall_cents"], 3_500)
        self.assertEqual(self.fund["breakdown"][0]["timing_note"], "October")
        self.assertEqual(self.fund["breakdown"][1]["timing_note"], "")
        summary = self.repo.get_summary(self.month, self.today)
        self.assertEqual(summary.reserved_cash_cents, 0)
        self.assertEqual(summary.planned_cents, 3_500)
        self.assertEqual(summary.categories[0].remaining_cents, 0)

    def test_partial_funding_release_and_plan_edits_have_distinct_history(self):
        first = self.contribute(2_000)["funds"][0]
        self.assertEqual(first["monthly_shortfall_cents"], 1_500)
        updated = self.repo.update_fund(fund_id=self.fund["id"], budget_month_id=self.month,
            monthly_plan_cents=4_000, timing_note="Renewal in October", actor_user_id=self.actor)
        self.assertEqual(updated["balance_cents"], 2_000)
        self.assertEqual(updated["monthly_shortfall_cents"], 2_000)
        released = self.contribute(500, kind="release", idempotency_key="synthetic-release")["funds"][0]
        self.assertEqual(released["contributed_this_month_cents"], 1_500)
        self.assertEqual(released["balance_cents"], 1_500)
        self.assertEqual(released["spent_this_month_cents"], 0)
        self.assertTrue(all(e["actor_name"] == "Member" for e in released["entries"]))
        with self.repo.connect() as connection:
            changes = connection.execute("SELECT metadata FROM notification_events WHERE event_type='provision_plan_changed'").fetchone()[0]
        self.assertIn('"previous_monthly_plan_cents": 3500', changes)

    def test_replay_does_not_repeat_money_or_household_notification(self):
        self.contribute()
        self.contribute()
        with self.repo.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reserve_entries").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM notification_events WHERE event_type='provision_contribution'").fetchone()[0], 1)

    def test_invalid_dates_amounts_and_breakdown_do_not_create_entries(self):
        for changes in ({"occurred_on": self.today+timedelta(days=1)}, {"occurred_on": date(2026, 1, 31)},
                        {"occurred_on": datetime(2026, 2, 8)}, {"amount_cents": True}, {"amount_cents": 1.5},
                        {"amount_cents": -1}, {"amount_cents": 0}, {"idempotency_key": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.contribute(**changes)
        with self.assertRaises(ValueError):
            self.repo.update_fund(fund_id=self.fund["id"], budget_month_id=self.month,
                                  breakdown=[{"name": "Invalid", "annual_cents": -10}])
        self.assertEqual(self.repo.get_funds(self.month)["funds"][0]["entries"], [])

    def test_funding_an_upcoming_linked_bill_does_not_reserve_the_same_cash_twice(self):
        self.repo.update_cash_account(account_id=self.account, balance_cents=10_000)
        self.repo.add_expected_bill(budget_month_id=self.month, name="Renewal", amount_cents=10_000,
            due_on=self.today+timedelta(days=1), reserve_fund_id=self.fund["id"])
        self.contribute(10_000)
        summary = self.repo.get_summary(self.month, self.today)
        self.assertEqual(summary.reserved_cash_cents, 10_000)
        self.assertEqual(summary.reserve_covered_bills_cents, 10_000)
        self.assertEqual(summary.cash_after_bills_cents, 0)

    def test_reconciliation_revision_changes_when_cash_is_earmarked(self):
        before = bank_status(self.repo, self.month)["revision"]
        self.contribute()
        self.assertNotEqual(bank_status(self.repo, self.month)["revision"], before)

    def test_correcting_expense_deficit_only_earmarks_the_positive_balance(self):
        transaction = self.repo.upsert_plaid_transaction(cash_account_id=self.account,
            plaid_transaction_id="synthetic-deficit", amount_cents=-10_000, occurred_on=self.today, name="Actual expense")
        self.repo.assign_transaction_category(transaction_id=transaction.transaction_id, category_id=self.fund["category_id"])
        self.repo.update_cash_account(account_id=self.account, balance_cents=0)
        first = self.contribute(10_000)["funds"][0]
        self.assertEqual(first["balance_cents"], 0)
        self.repo.update_cash_account(account_id=self.account, balance_cents=5_000)
        self.contribute(5_000, idempotency_key="synthetic-positive-after-deficit")
        self.assertEqual(self.repo.get_funds(self.month)["reserved_included_cents"], 5_000)

    def test_already_applied_live_request_can_replay_after_month_rollover(self):
        self.contribute()
        self.repo.settings = replace(self.repo.settings, plaid_enabled=True)
        with patch("backend.app.funds.household_today", return_value=date(2026, 3, 1)):
            self.assertEqual(self.contribute()["funds"][0]["balance_cents"], 1_000)
            with self.assertRaisesRegex(ValueError, "current budget month"):
                self.contribute(idempotency_key="new-request-in-old-month")

    def test_live_funds_cannot_earmark_a_manually_entered_account_balance(self):
        self.repo.settings = replace(self.repo.settings, plaid_enabled=True)
        with self.assertRaisesRegex(ValueError, "connected bank account"):
            self.contribute()
        with self.assertRaisesRegex(ValueError, "connected bank account"):
            self.repo.create_fund(budget_month_id=self.month, name="Unbacked live fund", backing_account_id=self.account,
                                  monthly_plan_cents=100)

    def test_restore_after_archived_copy_attaches_zero_plan_without_inventing_funding(self):
        self.contribute()
        self.repo.update_fund(fund_id=self.fund["id"], budget_month_id=self.month, archived=True)
        following = self.repo.create_budget_month(household_id=self.household, month="2026-03", copy_from_budget_month_id=self.month)
        skipped = self.repo.get_funds(following)["funds"][0]
        self.assertIsNone(skipped["category_id"])
        restored = self.repo.update_fund(fund_id=self.fund["id"], budget_month_id=following, archived=False)
        self.assertFalse(restored["archived"])
        self.assertIsNotNone(restored["category_id"])
        self.assertEqual(restored["monthly_plan_cents"], 0)
        self.assertEqual(restored["balance_cents"], 1_000)
        self.assertEqual(restored["contributed_this_month_cents"], 0)
        edited = self.repo.update_fund(fund_id=self.fund["id"], budget_month_id=following, monthly_plan_cents=4_500)
        self.assertEqual(edited["category_id"], restored["category_id"])
        self.assertEqual(edited["monthly_plan_cents"], 4_500)
        self.assertEqual(edited["balance_cents"], 1_000)

    def test_edit_plan_in_uncopied_month_attaches_active_fund_once(self):
        following = self.repo.create_budget_month(household_id=self.household, month="2026-03")
        self.assertIsNone(self.repo.get_funds(following)["funds"][0]["category_id"])
        first = self.repo.update_fund(fund_id=self.fund["id"], budget_month_id=following, monthly_plan_cents=2_300)
        second = self.repo.update_fund(fund_id=self.fund["id"], budget_month_id=following, monthly_plan_cents=2_500)
        self.assertEqual(first["category_id"], second["category_id"])
        self.assertEqual(second["monthly_plan_cents"], 2_500)
        self.assertEqual(second["balance_cents"], 0)
        self.assertEqual(self.repo.get_funds(self.month)["funds"][0]["monthly_plan_cents"], 3_500)

    def test_restore_existing_category_keeps_its_saved_plan(self):
        self.repo.update_fund(fund_id=self.fund["id"], budget_month_id=self.month, archived=True)
        restored = self.repo.update_fund(fund_id=self.fund["id"], budget_month_id=self.month, archived=False)
        self.assertEqual(restored["category_id"], self.fund["category_id"])
        self.assertEqual(restored["monthly_plan_cents"], 3_500)
        self.assertEqual(restored["balance_cents"], 0)

    def test_replacing_plan_with_active_merchant_rules_requires_review(self):
        # Another synthetic household has no funds yet.
        household = self.repo.create_household("Synthetic migration household")
        month = self.repo.create_budget_month(household_id=household, month="2026-02")
        account = self.repo.add_cash_account(budget_month_id=month, name="Other checking", account_type="checking", balance_cents=10_000)
        group = self.repo.add_budget_group(budget_month_id=month, name="Legacy")
        category = self.repo.add_category(budget_group_id=group, name="Old provision", planned_cents=5_000)
        self.repo.create_merchant_rule(household_id=household, category_id=category, merchant_match_text="Example merchant")
        with self.assertRaisesRegex(ValueError, "merchant rules"):
            self.repo.setup_funds(budget_month_id=month, backing_account_id=account, replace_category_id=category,
                funds=[{"name": "New fund", "monthly_plan_cents": 5_000}])
        self.assertEqual(self.repo.get_funds(month)["funds"], [])


class ProvisionMigrationTests(unittest.TestCase):
    def test_schema_three_upgrade_preserves_existing_money_tokens_and_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = BudgetRepository(Path(directory)/"synthetic-upgrade.sqlite",
                                    RuntimeSettings(hosted=True, setup_code="s"*40, encryption_key="k"*40))
            with patch.object(migrations, "MIGRATIONS", migrations.MIGRATIONS[:3]):
                repo.initialize()
            household = repo.create_household("Synthetic existing household", [{"name": "Existing member", "username": "fixture", "password": "synthetic-passphrase"}])
            month = repo.create_budget_month(household_id=household, month="2026-02")
            account = repo.add_cash_account(budget_month_id=month, name="Existing account", account_type="checking", balance_cents=123_456)
            group = repo.add_budget_group(budget_month_id=month, name="Existing group")
            category = repo.add_category(budget_group_id=group, name="Existing provision", planned_cents=12_300)
            auth = repo.authenticate_local_user("fixture", "synthetic-passphrase")
            repo.store_plaid_access_token("synthetic-token-reference", "synthetic-access-value")
            with repo.connect() as connection:
                connection.execute("INSERT INTO manual_spending(budget_category_id,amount_cents,occurred_on,note) VALUES (?,?,?,?)", (category, 123, "2026-02-05", "Existing synthetic expense"))
                connection.execute("INSERT INTO expected_bills(budget_month_id,name,amount_cents,due_on) VALUES (?,?,?,?)", (month, "Existing bill", 345, "2026-02-20"))
                tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_migrations'")]
                columns = {t: [r[1] for r in connection.execute('PRAGMA table_info("'+t+'")')] for t in tables}
                before = {t: [tuple(r) for r in connection.execute('SELECT * FROM "'+t+'" ORDER BY rowid')] for t in tables}
            repo.initialize()
            repo.initialize()
            with repo.connect() as connection:
                after = {t: [tuple(r) for r in connection.execute('SELECT '+','.join('"'+c+'"' for c in columns[t])+' FROM "'+t+'" ORDER BY rowid')] for t in tables}
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], migrations.LATEST_VERSION)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM reserve_funds").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM reserve_entries").fetchone()[0], 0)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(before, after)
            self.assertIsNotNone(repo.auth_context_for_token(auth["token"]))
            self.assertEqual(repo.retrieve_plaid_access_token("synthetic-token-reference"), "synthetic-access-value")
            self.assertEqual(repo.list_accounts(month)[0].id, account)


if __name__ == "__main__":
    unittest.main()
