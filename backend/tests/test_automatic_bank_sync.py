"""Foreground sync cadence, household sharing, failure recovery and isolation."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from backend.app.automatic_bank_sync import sync_due, sync_if_due
from backend.app.bank_data import bank_status
from backend.app.plaid import PlaidIntegrationError
from backend.tests import test_bank_refresh as fixture


class AutomaticSyncPolicyTests(unittest.TestCase):
    def test_three_hours_and_household_midnight(self):
        now = datetime.fromisoformat("2026-10-08T17:00:00Z")
        row = dict(balance_error=0, transaction_error=0, history_complete=1)
        with patch.dict(os.environ, {"FF_TIMEZONE": "America/New_York"}):
            for age, due in [(0, False), (10799, False), (10800, True), (10801, True)]:
                row.update(balance_checked_at=(now-timedelta(seconds=age)).isoformat(), transactions_checked_at=now.isoformat())
                self.assertEqual(sync_due(row, now), due)
            row.update(balance_checked_at="2026-10-08T03:59:59Z", transactions_checked_at="2026-10-08T03:59:59Z")
            self.assertTrue(sync_due(row, datetime.fromisoformat("2026-10-08T04:00:01Z")))
            row.update(balance_checked_at="2026-10-08T23:30:00Z", transactions_checked_at="2026-10-08T23:30:00Z")
            self.assertFalse(sync_due(row, datetime.fromisoformat("2026-10-09T00:30:00Z")))

    def test_invalid_future_failed_or_incomplete_data_needs_sync(self):
        now = datetime.now(timezone.utc)
        row = dict(balance_error=0, transaction_error=0, history_complete=1,
                   balance_checked_at=now.isoformat(), transactions_checked_at=now.isoformat())
        for field, value in [("balance_checked_at", None), ("transactions_checked_at", "bad"),
                             ("balance_checked_at", (now+timedelta(seconds=1)).isoformat()),
                             ("balance_error", 1), ("transaction_error", 1), ("history_complete", 0)]:
            with self.subTest(field=field, value=value):
                self.assertTrue(sync_due(dict(row, **{field: value}), now))


class AutomaticSyncApiTests(unittest.TestCase):
    setUp = fixture.BankRefreshTests.setUp
    request = fixture.BankRefreshTests.request

    def sync(self, *, token=None, force=False):
        return self.request("POST", f"/budget-months/{self.month}/bank-sync", {"force": force}, token=token or self.tokens[0])

    def make_stale(self):
        stamp = (datetime.now(timezone.utc)-timedelta(hours=4)).isoformat()
        with self.repo.connect() as connection:
            connection.execute("UPDATE bank_sync_state SET balance_checked_at=?,transactions_checked_at=?,last_successful_sync_at=?,auto_sync_attempted_at=NULL", (stamp, stamp, stamp))
        self.bank.calls.clear()

    def test_due_sync_once_shared_by_both_spouses_without_forcing_bank_refresh(self):
        self.make_stale()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda token: self.sync(token=token), self.tokens))
        self.assertTrue(all(code == 200 and data["success"] for code, data in results))
        self.assertEqual(sum(data["synced"] for _, data in results), 1)
        self.assertEqual(sum(path == "/transactions/sync" for path, _ in self.bank.calls), 1)
        self.assertFalse(any(path == "/transactions/refresh" for path, _ in self.bank.calls))
        self.assertFalse(self.sync()[1]["synced"])

    def test_recent_success_skips_provider_and_explicit_retry_can_sync(self):
        self.assertFalse(self.sync()[1]["synced"])
        self.assertEqual(self.bank.calls, [])
        self.assertTrue(self.sync(force=True)[1]["synced"])

    def test_failure_keeps_last_success_and_retries_without_duplicate_transactions(self):
        self.make_stale()
        before = bank_status(self.repo, self.month)["last_successful_sync_at"]
        with patch.object(self.bank, "sync_transactions", side_effect=PlaidIntegrationError("private provider detail", "ITEM_LOGIN_REQUIRED")):
            code, failed = self.sync()
        self.assertEqual(code, 200)
        self.assertFalse(failed["success"])
        self.assertNotIn("private provider", str(failed))
        self.assertEqual(bank_status(self.repo, self.month)["last_successful_sync_at"], before)
        calls = len(self.bank.calls)
        self.assertGreater(self.sync(token=self.tokens[1])[1]["retry_after_seconds"], 0)
        self.assertEqual(len(self.bank.calls), calls)
        self.assertTrue(self.sync(force=True)[1]["success"])
        transactions = self.repo.list_transactions(self.month)
        self.assertTrue(self.sync(force=True)[1]["success"])
        self.assertEqual(self.repo.list_transactions(self.month), transactions)

    def test_authentication_ownership_and_force_type_validated_before_provider_calls(self):
        self.assertEqual(self.request("POST", f"/budget-months/{self.month}/bank-sync")[0], 401)
        other = self.repo.create_household("Other synthetic", [{"name": "Other", "username": "other-auto", "password": "synthetic-other-password"}])
        month = self.repo.create_budget_month(household_id=other, month="2026-10")
        code, _ = self.request("POST", f"/budget-months/{month}/bank-sync", token=self.tokens[0])
        self.assertIn(code, (403, 404))
        self.assertEqual(self.request("POST", f"/budget-months/{self.month}/bank-sync", {"force": "true"}, token=self.tokens[0])[0], 400)
        self.assertEqual(self.bank.calls, [])

    def test_demo_sync_is_separate_and_fresh_reentry_discards_it(self):
        self.make_stale()
        before = bank_status(self.repo, self.month)
        code, demo = self.request("POST", "/demo/start", token=self.tokens[0])
        self.assertEqual(code, 200)
        path = f"/demo/budget-months/{demo['budget_month_id']}/bank-sync"
        self.assertEqual(self.request("POST", path, token=self.tokens[0])[0], 401)
        self.assertEqual(self.request("POST", f"/budget-months/{self.month}/bank-sync", token=demo["token"])[0], 401)
        code, result = self.request("POST", path, {"force": True}, token=demo["token"])
        self.assertEqual(code, 200)
        self.assertTrue(result["success"])
        self.assertEqual(self.bank.calls, [])
        self.assertEqual(bank_status(self.repo, self.month), before)
        self.request("POST", "/demo/exit", token=demo["token"])
        self.assertEqual(self.request("POST", path, token=demo["token"])[0], 401)
        _, fresh = self.request("POST", "/demo/start", token=self.tokens[0])
        self.addCleanup(lambda: self.request("POST", "/demo/exit", token=fresh["token"]))
        self.assertNotEqual(fresh["token"], demo["token"])
        fresh_result = self.request("POST", f"/demo/budget-months/{fresh['budget_month_id']}/bank-sync", token=fresh["token"])[1]
        self.assertTrue(fresh_result["success"])
        self.assertFalse(fresh_result["synced"])
