"""Daily bank checks and streamlined earmarks, using only synthetic bank data."""
import io
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.bank_data import BankSyncRequiredError, bank_status, reconcile_bank, synced_today
from backend.app.db import BudgetRepository
from backend.app.hosted import Application
from backend.app.live_plaid import LivePlaidService
from backend.app.security import RuntimeSettings
from backend.tests.test_stage2_live_bank import FakeBank


class HouseholdSyncDateTests(unittest.TestCase):
    def test_same_household_day_not_a_rolling_24_hour_window(self):
        with patch.dict(os.environ, {"FF_TIMEZONE": "America/New_York"}):
            now = datetime.fromisoformat("2026-09-30T04:05:00+00:00")
            self.assertFalse(synced_today("2026-09-30T03:59:59Z", now=now))
            self.assertTrue(synced_today("2026-09-30T04:00:00Z", now=now))
            self.assertTrue(synced_today("2026-09-30 04:00:00", now=now))
            self.assertTrue(synced_today("2026-09-30T00:00:00-04:00", now=now))

    def test_earlier_today_remains_valid_across_utc_midnight(self):
        with patch.dict(os.environ, {"FF_TIMEZONE": "America/New_York"}):
            now = datetime.fromisoformat("2026-10-01T03:55:00+00:00")
            self.assertTrue(synced_today("2026-09-30T04:00:00Z", now=now))

    def test_future_missing_and_malformed_timestamps_are_not_today(self):
        now = datetime(2026, 9, 30, 20, tzinfo=timezone.utc)
        for value in (None, "", "invalid", 1, "2026-09-30T20:00:01Z", "99999-01-01"):
            with self.subTest(value=value):
                self.assertFalse(synced_today(value, now=now))

    def test_daylight_saving_and_hosted_default(self):
        with patch.dict(os.environ, {"FF_MODE": "hosted"}, clear=True):
            # Both instances of 01:30 on the fall-back day belong to today.
            now = datetime.fromisoformat("2026-11-01T06:45:00+00:00")
            self.assertTrue(synced_today("2026-11-01T05:30:00Z", now=now))
            self.assertTrue(synced_today("2026-11-01T06:30:00Z", now=now))
            self.assertFalse(synced_today("2026-11-01T03:59:59Z", now=now))
        with patch.dict(os.environ, {"FF_TIMEZONE": "America/Los_Angeles"}):
            now = datetime.fromisoformat("2026-09-30T07:05:00+00:00")
            self.assertFalse(synced_today("2026-09-30T06:59:59Z", now=now))
            self.assertTrue(synced_today("2026-09-30T07:00:00Z", now=now))


class DailyFundingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.today = date(2026, 9, 30)
        self.now = datetime(2026, 9, 30, 21, tzinfo=timezone.utc)
        for target in ("backend.app.dates.household_today", "backend.app.funds.household_today",
                       "backend.app.db.household_today"):
            clock = patch(target, return_value=self.today)
            clock.start()
            self.addCleanup(clock.stop)
        clock = patch("backend.app.bank_data.datetime", wraps=datetime)
        self.clock = clock.start()
        self.clock.now.return_value = self.now
        self.addCleanup(clock.stop)
        environment = patch.dict(os.environ, {"FF_TIMEZONE": "America/New_York",
                                             "PLAID_USAA_INSTITUTION_ID": "ins_test_usaa"})
        environment.start()
        self.addCleanup(environment.stop)
        self.repo = BudgetRepository(Path(temporary.name) / "synthetic.sqlite",
            RuntimeSettings(hosted=True, setup_code="s" * 40, encryption_key="k" * 40, plaid_enabled=True))
        self.repo.initialize()
        self.household = self.repo.create_household("Synthetic daily funding")
        self.month = self.repo.create_budget_month(household_id=self.household, month="2026-09")
        self.repo.add_payday(household_id=self.household, payday_date=date(2026, 10, 5))
        self.bank = FakeBank()
        self.bank.updated = "2026-09-30T12:00:00Z"
        self.bank.added = [{"transaction_id": "synthetic-unreviewed", "account_id": "synthetic-checking",
            "amount": 12, "date": self.today.isoformat(), "name": "Synthetic store",
            "pending": False, "iso_currency_code": "USD"}]
        self.service = LivePlaidService(self.repo, self.bank)
        self.service.exchange_public_token(household_id=self.household, budget_month_id=self.month,
                                          public_token="public-production-synthetic")
        self.item = self.repo.list_plaid_items(self.household)[0].id
        self.account = self.repo.list_accounts(self.month)[0].id
        self.repo.set_account_included(self.account, True)
        self.fund = self.repo.create_fund(budget_month_id=self.month, name="Synthetic irregular expenses",
                                        backing_account_id=self.account, monthly_plan_cents=5000)
        self.set_sync_at("2026-09-30T12:00:00Z")

    def set_sync_at(self, stamp):
        with self.repo.connect() as conn:
            conn.execute("UPDATE bank_sync_state SET balance_checked_at=?,transactions_checked_at=?",
                         (stamp, stamp))
            conn.execute("UPDATE cash_accounts SET last_balance_synced_at=?", (stamp,))

    def contribute(self, amount=5000, key="synthetic-contribution"):
        return self.repo.add_fund_entry(fund_id=self.fund["id"], budget_month_id=self.month,
            kind="contribution", amount_cents=amount, occurred_on=self.today, idempotency_key=key)

    def test_contribution_without_next_month_review_or_reconciliation(self):
        before = bank_status(self.repo, self.month)
        self.assertFalse(before["sync_required"])
        self.assertFalse(before["ready"])
        self.assertFalse(before["reconciled"])
        self.assertEqual(before["unreviewed_spending"], 1)
        result = self.contribute()
        self.assertEqual(result["funds"][0]["balance_cents"], 5000)
        self.assertEqual(result["funds"][0]["contributed_this_month_cents"], 5000)
        with self.repo.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM budget_months").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT reviewed FROM account_transactions").fetchone()[0], 0)
        self.assertEqual(self.repo.list_accounts(self.month)[0].balance_cents, 48000)
        self.assertFalse(bank_status(self.repo, self.month)["reconciled"])

    def test_spending_keeps_review_reconciliation_and_next_month_checks(self):
        self.contribute()
        with self.assertRaisesRegex(ValueError, "next budget month"):
            self.spending_check()
        self.repo.create_budget_month(household_id=self.household, month="2026-10")
        with self.assertRaisesRegex(ValueError, "Review imported"):
            self.spending_check()
        transaction = self.repo.list_budget_transactions(self.month)[0].transaction.id
        self.repo.assign_transaction_category(transaction_id=transaction,
                                              category_id=self.fund["category_id"], reviewed=True)
        with self.assertRaisesRegex(ValueError, "confirm reconciliation"):
            self.spending_check()
        state = bank_status(self.repo, self.month)
        reconcile_bank(self.repo, self.month, state["revision"])
        # The last sync was nine hours ago; category and cash accounting still apply.
        result = self.spending_check()
        self.assertIn("After upcoming bills", result.required_phrase)
        self.assertEqual(result.category_remaining_before_cents, 3800)

    def spending_check(self):
        return self.repo.safe_to_spend(budget_month_id=self.month, category_id=self.fund["category_id"],
                                      purchase_amount_cents=100, today=self.today)

    def test_previous_day_and_individual_stale_accounts_block_new_contributions(self):
        self.set_sync_at("2026-09-30T03:59:59Z")
        self.assertTrue(bank_status(self.repo, self.month)["sync_required"])
        with self.assertRaises(BankSyncRequiredError):
            self.contribute()
        self.set_sync_at("2026-09-30T12:00:00Z")
        # Excluded backing accounts also need their own current balance.
        other = self.repo.upsert_connected_account(budget_month_id=self.month, plaid_item_id=self.item,
            plaid_account_id="synthetic-other-checking", name="Synthetic spending account", account_type="checking",
            balance_cents=10000, available_balance_cents=10000, current_balance_cents=10000,
            included_in_cash_reality=True)
        self.repo.set_account_included(self.account, False)
        with self.repo.connect() as conn:
            conn.execute("UPDATE cash_accounts SET last_balance_synced_at='2026-09-30T12:00:00Z' WHERE id=?", (other,))
            conn.execute("UPDATE cash_accounts SET last_balance_synced_at='2000-01-01' WHERE id=?", (self.account,))
        with self.assertRaises(BankSyncRequiredError):
            self.contribute()
        self.assertEqual(self.repo.get_funds(self.month)["funds"][0]["balance_cents"], 0)

    def test_failed_incomplete_or_unknown_bank_data_still_blocks_funding(self):
        for change in ("UPDATE bank_sync_state SET balance_error=1",
                       "UPDATE bank_sync_state SET transaction_error=1",
                       "UPDATE bank_sync_state SET history_complete=0",
                       "UPDATE bank_sync_state SET transactions_updated_at='2000-01-01'",
                       "UPDATE cash_accounts SET available_balance_cents=NULL"):
            with self.subTest(change=change):
                with self.repo.connect() as conn:
                    conn.execute(change)
                with self.assertRaises(BankSyncRequiredError):
                    self.contribute()
                with self.repo.connect() as conn:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM reserve_entries").fetchone()[0], 0)
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM reserve_operations").fetchone()[0], 0)
                    conn.execute("UPDATE bank_sync_state SET balance_error=0,transaction_error=0,history_complete=1,transactions_updated_at='2026-09-30T12:00:00Z'")
                    conn.execute("UPDATE cash_accounts SET available_balance_cents=48000")

    def test_recorded_next_month_bills_and_existing_reserves_remain_protected(self):
        october = self.repo.create_budget_month(household_id=self.household, month="2026-10")
        self.repo.add_expected_bill(budget_month_id=october, name="Synthetic rent", amount_cents=40000,
                                   due_on=date(2026, 10, 1))
        self.contribute(5000)
        with self.assertRaisesRegex(ValueError, "Not enough unreserved cash"):
            self.contribute(3001, "synthetic-excess")
        self.contribute(3000, "synthetic-exact-limit")
        self.assertEqual(self.repo.get_funds(self.month)["funds"][0]["balance_cents"], 8000)

    def test_applied_request_replays_without_bank_sync_and_cannot_change_amount(self):
        self.contribute()
        self.set_sync_at("2000-01-01")
        with patch("backend.app.funds.household_today", return_value=date(2026, 10, 1)):
            self.assertEqual(self.contribute()["funds"][0]["balance_cents"], 5000)
        with self.assertRaisesRegex(ValueError, "different provision change"):
            self.contribute(5001)

    def test_authenticated_sync_rejection_then_retry_applies_exactly_once(self):
        self.repo.create_local_user(household_id=self.household, name="Synthetic user", username="synthetic",
                                   email=None, password="synthetic-password")
        token = self.repo.authenticate_local_user("synthetic", "synthetic-password")["token"]
        app = Application(self.repo)
        app.plaid = self.service
        body = json.dumps({"budget_month_id": self.month, "kind": "contribution", "amount_cents": 5000,
                           "occurred_on": self.today.isoformat(), "idempotency_key": "synthetic-http"}).encode()

        def request():
            codes = []
            response = b"".join(app({"REQUEST_METHOD": "POST", "PATH_INFO": f"/funds/{self.fund['id']}/entries",
                "QUERY_STRING": "", "wsgi.input": io.BytesIO(body), "CONTENT_LENGTH": str(len(body)),
                "CONTENT_TYPE": "application/json", "HTTP_AUTHORIZATION": "Bearer " + token},
                lambda status, headers: codes.append(int(status.split()[0]))))
            return codes[0], json.loads(response)

        self.set_sync_at("2026-09-30T03:59:59Z")
        code, error = request()
        self.assertEqual(code, 400)
        self.assertEqual(error["code"], "bank_sync_required")
        self.assertTrue(self.service.sync_balances(self.item).success)
        self.assertTrue(self.service.sync_transactions(self.item).success)
        self.set_sync_at("2026-09-30T20:00:00Z")
        for _ in range(2):
            code, result = request()
            self.assertEqual(code, 200, result)
            self.assertEqual(result["funds"][0]["balance_cents"], 5000)
        with self.repo.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM reserve_entries").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
