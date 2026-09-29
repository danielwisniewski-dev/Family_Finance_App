"""Demo fixtures must continue to obey real bank, budget and reserve rules."""
import os
import shutil
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from backend.app.bank_data import bank_status, reconcile_bank
from backend.app.dates import household_today
from backend.app.demo_data import create_demo_context
from backend.app.db import BudgetRepository
from backend.app.demo_bank import DemoBankClient
from backend.app.live_plaid import LivePlaidService


class DemoDataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "demo.sqlite"
        self.context = create_demo_context(self.path)
        self.repository = self.context.repository
        self.month = self.context.budget_month_id
        self.today = household_today()
        self.service = self.context.plaid_service
        self.item = self.repository.list_plaid_items(self.context.household_id)[0].id

    def category(self, name):
        return next(c.id for c in self.repository.get_summary(self.month, self.today).categories if c.name == name)

    def test_seed_is_ready_zero_based_and_fictional(self):
        self.assertTrue(self.repository.settings.hosted)
        self.assertTrue(self.repository.settings.plaid_enabled)
        self.assertEqual(self.repository.settings.session_seconds, 8 * 60 * 60)
        self.assertTrue(bank_status(self.repository, self.month)["ready"])
        self.assertEqual(self.repository.list_transaction_review_queue(self.month), [])
        self.assertEqual(self.repository.auth_context_for_token(self.context.login["token"])["user_id"], self.context.user_id)
        self.assertEqual(self.context.login["user"]["name"], "Alex Morgan")
        for month in self.repository.list_budget_months(self.context.household_id):
            self.assertEqual(self.repository.get_summary(month["id"], self.today).unassigned_cents, 0)
        accounts = self.repository.list_accounts(self.month)
        self.assertEqual([a.account_type for a in accounts], ["checking", "checking", "savings"])
        self.assertEqual(sum(a.balance_cents for a in accounts if a.included_in_cash_reality), 350_000)
        self.assertFalse(accounts[-1].included_in_cash_reality)

    def test_shared_math_handles_split_ignored_refund_and_fund_history(self):
        summary = self.repository.get_summary(self.month, self.today)
        categories = {c.name: c for c in summary.categories}
        self.assertEqual(categories["Groceries"].spent_cents, 12_432)
        self.assertEqual(categories["Household Supplies"].spent_cents, 2_200)
        self.assertEqual(categories["Car Repairs"].spent_cents, 16_000)
        self.assertEqual(summary.reserved_cash_cents, 181_500)
        funds = {f["name"]: f for f in self.repository.get_funds(self.month)["funds"]}
        self.assertEqual({name: f["balance_cents"] for name, f in funds.items()},
                         {"Car Repairs": 59_000, "Annual Insurance": 90_000, "Gifts": 32_500})
        kinds = {entry["kind"] for f in funds.values() for entry in f["entries"]}
        self.assertTrue({"contribution", "release", "transfer_in", "transfer_out", "expense", "refund"} <= kinds)
        self.assertEqual(summary.reserve_covered_bills_cents, 80_000)
        self.assertEqual(summary.cash_after_bills_cents, 142_000)
        self.assertTrue(self.repository.list_merchant_rules(self.context.household_id))
        self.assertTrue(self.repository.list_notification_events(household_id=self.context.household_id, user_id=self.context.user_id))

    def test_ready_spending_check_can_show_safe_caution_and_no(self):
        for category, amount, expected in (("Groceries", 2_500, "safe"), ("Rent", 120_000, "caution"), ("Dining Out", 10_000, "no")):
            with self.subTest(expected=expected):
                result = self.repository.safe_to_spend(budget_month_id=self.month, category_id=self.category(category),
                    purchase_amount_cents=amount, today=self.today)
                self.assertEqual(result.warning_level.value, expected)
                self.assertIn("After upcoming bills, you would have about $", result.required_phrase)
                self.assertIn("6 days until payday.", result.required_phrase)

    def test_sync_imports_once_and_preserves_production_review_rules(self):
        old_balance = self.repository.list_accounts(self.month)[0].balance_cents
        self.assertTrue(self.service.sync_balances(self.item).success)
        outcome = self.service.sync_transactions(self.item)
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.inserted_transactions, 2)
        self.assertEqual(self.repository.list_accounts(self.month)[0].balance_cents, old_balance - 10_039)
        status = bank_status(self.repository, self.month)
        self.assertFalse(status["ready"])
        self.assertEqual(status["unreviewed_spending"], 2)
        self.assertFalse(status["sync_required"])
        with self.assertRaisesRegex(ValueError, "Review imported"):
            self.repository.safe_to_spend(budget_month_id=self.month, category_id=self.category("Groceries"), purchase_amount_cents=100, today=self.today)
        # Earmarking remains usable with the ordinary unreviewed-spending rule.
        fund = self.repository.get_funds(self.month)["funds"][0]
        self.repository.add_fund_entry(fund_id=fund["id"], budget_month_id=self.month, kind="contribution",
            amount_cents=1_000, occurred_on=self.today, idempotency_key="demo-parity-contribution")
        for transaction in self.repository.list_transaction_review_queue(self.month):
            category = "Groceries" if transaction.transaction.merchant_name == "Maple Market" else "Household Supplies"
            self.repository.assign_transaction_category(transaction_id=transaction.transaction.id,
                category_id=self.category(category), reviewed=True)
        reconcile_bank(self.repository, self.month, bank_status(self.repository, self.month)["revision"])
        self.assertTrue(bank_status(self.repository, self.month)["ready"])
        self.assertTrue(self.service.sync_balances(self.item).success)
        repeated = self.service.sync_transactions(self.item)
        self.assertEqual(repeated.inserted_transactions, 0)
        self.assertEqual(repeated.updated_transactions, 0)
        self.assertTrue(bank_status(self.repository, self.month)["ready"])

    def test_refresh_and_reconnect_are_simulated_with_real_refresh_claims(self):
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Demo must not use network")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("Demo must not use network")):
            link = self.service.create_link_token(self.context.household_id)
            self.assertEqual(link.link_token, "demo-bank-link")
            result = self.service.exchange_public_token(household_id=self.context.household_id, budget_month_id=self.month,
                                                       public_token="demo-bank-confirmed")
            self.assertEqual(len(result.accounts), 3)
            refresh = self.service.request_fresh_data(self.item)
            self.assertTrue(refresh["request_sent"])
            self.assertEqual(refresh["refresh"]["state"], "pending")
            self.assertFalse(self.service.request_fresh_data(self.item)["request_sent"])
            self.assertTrue(self.service.sync_transactions(self.item).success)
            self.assertEqual(bank_status(self.repository, self.month)["refresh"]["state"], "checked")

    def test_existing_database_is_never_overwritten(self):
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            create_demo_context(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_simulated_balance_sync_matches_shared_live_service_semantics(self):
        # The live balance wrapper identifies a configured real institution, while
        # demo must never consult that setting. Compare the wrappers on identical
        # fictional repositories so future live changes cannot silently drift.
        copied = Path(self.directory.name) / "equivalent.sqlite"
        shutil.copyfile(self.path, copied)
        equivalent = BudgetRepository(copied, self.repository.settings)
        client = DemoBankClient(self.service.client.transactions, self.service.client.new_transactions)
        client.new_activity_available = True
        normal_service = LivePlaidService(equivalent, client)
        for repository in (self.repository, equivalent):
            account = repository.list_accounts(self.month)[0]
            repository.set_account_included(account.id, False)
        with patch.dict(os.environ, {"PLAID_USAA_INSTITUTION_ID": "test-only-fictional-institution"}), \
             patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("No demo network")):
            self.assertEqual(self.service.sync_balances(self.item), normal_service.sync_balances(self.item))
            self.assertEqual(self.service.sync_transactions(self.item), normal_service.sync_transactions(self.item))
            def account_values(repository):
                return [(a.id, a.balance_cents, a.available_balance_cents, a.current_balance_cents,
                         a.included_in_cash_reality, a.plaid_account_id) for a in repository.list_accounts(self.month)]
            self.assertEqual(account_values(self.repository), account_values(equivalent))
            for field in ("ready", "unreviewed_spending", "sync_required", "history_complete", "funding_issues"):
                self.assertEqual(bank_status(self.repository, self.month)[field], bank_status(equivalent, self.month)[field])
            # A disappeared account must lose its freshness in either wrapper.
            original = self.service.client.accounts(None, fresh=True)
            with patch.object(self.service.client, "accounts", return_value=original[:2]), \
                 patch.object(client, "accounts", return_value=original[:2]):
                self.assertEqual(self.service.sync_balances(self.item), normal_service.sync_balances(self.item))
            self.assertEqual(account_values(self.repository), account_values(equivalent))
            self.assertIsNone(self.repository.list_accounts(self.month)[2].last_balance_synced_at)
            self.assertIsNone(equivalent.list_accounts(self.month)[2].last_balance_synced_at)


class DemoCalendarTests(unittest.TestCase):
    def test_first_last_leap_and_year_boundary_seeds_follow_real_rules(self):
        for today in (date(2026, 1, 1), date(2026, 1, 31), date(2028, 2, 29), date(2026, 12, 31)):
            with self.subTest(today=today), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                # Only clocks change in the test; production fixture never patches
                # shared settings, clocks, or financial validation to seed money.
                for target in ("backend.app.demo_data.household_today", "backend.app.dates.household_today",
                               "backend.app.db.household_today", "backend.app.funds.household_today"):
                    stack.enter_context(patch(target, return_value=today))
                stack.enter_context(patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("No demo network")))
                context = create_demo_context(Path(directory) / "demo.sqlite", today)
                summary = context.repository.get_summary(context.budget_month_id, today)
                self.assertEqual(summary.month, today.strftime("%Y-%m"))
                self.assertEqual(summary.next_payday, today + timedelta(days=6))
                self.assertEqual(summary.unassigned_cents, 0)
                self.assertEqual(summary.cash_after_bills_cents, 142_000)
                self.assertTrue(bank_status(context.repository, context.budget_month_id)["ready"])
                self.assertEqual(len(context.repository.list_budget_months(context.household_id)), 3)


if __name__ == "__main__":
    unittest.main()
