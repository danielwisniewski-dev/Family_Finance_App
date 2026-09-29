"""On-demand refresh regressions: synthetic provider responses, never live calls."""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch
from urllib.error import HTTPError

from backend.app.bank_data import bank_status
from backend.app import migrations
from backend.app.dates import household_today
from backend.app.db import BudgetRepository
from backend.app.hosted import Application
from backend.app.live_plaid import LivePlaidClient, LivePlaidService
from backend.app.plaid import PlaidIntegrationError, PlaidSettings
from backend.app.security import RuntimeSettings
from backend.tests.test_stage2_live_bank import FakeBank


class RefreshBank(FakeBank):
    def __init__(self):
        super().__init__()
        self.refresh_error = None
        self.refresh_response = {"request_id": "synthetic-provider-request-internal"}
        self.refresh_entered = None
        self.refresh_continue = None
        self.updated_during_sync = None

    def _request(self, path, payload):
        if path != "/transactions/refresh":
            response = super()._request(path, payload)
            if path == "/transactions/sync" and self.updated_during_sync is not None:
                self.updated = self.updated_during_sync
            return response
        self.calls.append((path, payload))
        if self.refresh_entered is not None:
            self.refresh_entered.set()
        if self.refresh_continue is not None and not self.refresh_continue.wait(5):
            raise AssertionError("The test did not release its simulated provider request")
        if self.refresh_error is not None:
            raise self.refresh_error
        return self.refresh_response


class BankRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {"PLAID_USAA_INSTITUTION_ID": "ins_test_usaa"})
        environment.start()
        self.addCleanup(environment.stop)
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        clock = patch("backend.app.bank_refresh.utc_now", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.repo = BudgetRepository(Path(self.temp.name)/"synthetic-refresh.sqlite",
            RuntimeSettings(hosted=True, setup_code="s"*40, encryption_key="k"*40, plaid_enabled=True))
        self.repo.initialize()
        self.household = self.repo.create_household("Synthetic refresh household", [
            {"name": "Member A", "username": "refresh-a", "password": "synthetic-refresh-password"},
            {"name": "Member B", "username": "refresh-b", "password": "synthetic-refresh-password"}])
        self.tokens = [self.repo.authenticate_local_user(login=username, password="synthetic-refresh-password")["token"]
                       for username in ("refresh-a", "refresh-b")]
        self.today = self.now.date()
        self.month = self.repo.create_budget_month(household_id=self.household, month=self.today.strftime("%Y-%m"))
        self.repo.set_active_budget_month(household_id=self.household, budget_month_id=self.month)
        self.bank = RefreshBank()
        # Accepted refresh and cached sync must not manufacture a later bank update.
        self.bank.updated = (self.now-timedelta(hours=2)).isoformat()
        self.service = LivePlaidService(self.repo, self.bank)
        self.service.exchange_public_token(household_id=self.household, budget_month_id=self.month,
                                            public_token="public-production-synthetic-refresh")
        self.item_id = self.repo.list_plaid_items(self.household)[0].id
        self.app = Application(self.repo)
        self.app.plaid = self.service
        self.bank.calls.clear()

    def request(self, method, path, payload=None, *, token=None):
        body = json.dumps(payload or {}).encode()
        status = []
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
            "wsgi.input": io.BytesIO(body), "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/json"}
        if token:
            environ["HTTP_AUTHORIZATION"] = "Bearer " + token
        response = b"".join(self.app(environ, lambda code, headers: status.append(int(code.split()[0]))))
        return status[0], json.loads(response)

    def refresh_calls(self):
        return sum(path == "/transactions/refresh" for path, _ in self.bank.calls)

    def refresh(self, *, token=None, expected=200):
        status, result = self.request("POST", "/plaid/refresh", {"plaid_item_id": self.item_id}, token=token or self.tokens[0])
        self.assertEqual(status, expected, result)
        return result

    def sync(self, *, expected_success=True):
        status, result = self.request("POST", "/plaid/sync", {"plaid_item_id": self.item_id, "sync_type": "transaction"}, token=self.tokens[0])
        self.assertEqual(status, 200, result)
        self.assertEqual(result["success"], expected_success)
        return result

    def advance_bank(self, seconds=10):
        self.now += timedelta(seconds=seconds)
        self.bank.updated = self.now.isoformat()

    def assert_sanitized(self, payload):
        encoded = json.dumps(payload)
        for forbidden in ("synthetic-bank-secret", "synthetic-provider-request-internal", "provider-private-detail",
                          "access_token", "token_ref", "password_hash", "session_token_hash"):
            self.assertNotIn(forbidden, encoded)

    def test_ordinary_sync_never_requests_on_demand_refresh(self):
        for kind in ("balance", "transaction"):
            status, result = self.request("POST", "/plaid/sync", {"plaid_item_id": self.item_id, "sync_type": kind}, token=self.tokens[0])
            self.assertEqual(status, 200, result)
            self.assertTrue(result["success"])
        self.assertEqual(self.refresh_calls(), 0)
        self.assertEqual(len(self.repo.list_plaid_items(self.household)), 1)

    def test_explicit_refresh_reuses_item_and_does_not_claim_import_or_bank_freshness(self):
        before = bank_status(self.repo, self.month)
        accounts = self.repo.list_accounts(self.month)
        result = self.refresh()
        self.assertTrue(result["success"])
        self.assertTrue(result["request_sent"])
        self.assertEqual(result["refresh"]["state"], "pending")
        self.assertIsNone(result["refresh"]["checked_at"])
        self.assertIsNotNone(result["refresh"]["requested_at"])
        self.assertFalse(result["refresh"]["can_request"])
        self.assertGreater(result["refresh"]["retry_after_seconds"], 0)
        after = bank_status(self.repo, self.month)
        self.assertEqual(after["transactions_updated_at"], before["transactions_updated_at"])
        self.assertEqual(after["balance_checked_at"], before["balance_checked_at"])
        self.assertEqual(self.repo.list_accounts(self.month), accounts)
        self.assertEqual(len(self.repo.list_plaid_items(self.household)), 1)
        self.assertEqual(self.refresh_calls(), 1)
        self.assertFalse(any(path in {"/link/token/create", "/item/public_token/exchange"} for path, _ in self.bank.calls))
        self.assert_sanitized(result)

    def test_cached_sync_keeps_request_pending(self):
        self.refresh()
        result = self.sync()
        self.assertEqual(result["refresh"]["state"], "pending")
        self.assertIsNone(result["refresh"]["checked_at"])
        self.assertEqual(bank_status(self.repo, self.month)["refresh"]["state"], "pending")
        self.assertEqual(self.refresh_calls(), 1)

    def test_completion_requires_observed_new_bank_update_and_successful_import(self):
        self.refresh()
        self.advance_bank()
        self.bank.added = [{"transaction_id": "synthetic-new-posted", "account_id": "synthetic-checking",
                            "amount": 12, "date": self.today.isoformat(), "name": "New posted purchase",
                            "pending": False, "iso_currency_code": "USD"}]
        result = self.sync()
        self.assertEqual(result["refresh"]["state"], "checked")
        self.assertIsNotNone(result["refresh"]["checked_at"])
        self.assertEqual(len(self.repo.list_budget_transactions(self.month)), 1)
        self.assertEqual(self.repo.list_budget_transactions(self.month)[0].transaction.amount_cents, -1200)
        self.assertEqual(bank_status(self.repo, self.month)["refresh"]["state"], "checked")

    def test_newer_bank_update_before_request_is_not_refresh_completion(self):
        self.refresh()
        self.bank.updated = (self.now-timedelta(seconds=1)).isoformat()
        result = self.sync()
        self.assertEqual(result["refresh"]["state"], "pending")
        self.assertIsNone(result["refresh"]["checked_at"])

    def test_timestamp_advanced_during_download_waits_for_next_observed_import(self):
        self.refresh()
        self.now += timedelta(seconds=10)
        self.bank.updated_during_sync = self.now.isoformat()
        first = self.sync()
        self.assertEqual(first["refresh"]["state"], "pending")
        self.assertIsNone(first["refresh"]["checked_at"])
        self.bank.updated_during_sync = None
        second = self.sync()
        self.assertEqual(second["refresh"]["state"], "checked")

    def test_incomplete_history_and_failed_import_cannot_claim_completion(self):
        self.refresh()
        self.advance_bank()
        self.bank.history = False
        self.assertEqual(self.sync()["refresh"]["state"], "pending")
        self.bank.history = True
        self.bank.fail_sync = True
        failed = self.sync(expected_success=False)
        self.assertEqual(failed["refresh"]["state"], "pending")
        self.assertIsNone(failed["refresh"]["checked_at"])
        self.bank.fail_sync = False
        self.assertEqual(self.sync()["refresh"]["state"], "checked")

    def test_cooldown_is_shared_between_spouses_and_survives_service_restart(self):
        from backend.app.bank_refresh import REFRESH_COOLDOWN_SECONDS
        first = self.refresh(token=self.tokens[0])
        second = self.refresh(token=self.tokens[1])
        self.assertTrue(first["request_sent"])
        self.assertFalse(second["request_sent"])
        self.assertEqual(second["refresh"]["requested_at"], first["refresh"]["requested_at"])
        self.now += timedelta(seconds=REFRESH_COOLDOWN_SECONDS-1)
        restarted_repo = BudgetRepository(self.repo.db_path, self.repo.settings)
        restarted_repo.initialize()
        self.app.plaid = LivePlaidService(restarted_repo, self.bank)
        restarted = self.refresh(token=self.tokens[1])
        self.assertFalse(restarted["request_sent"])
        self.assertGreater(restarted["refresh"]["retry_after_seconds"], 0)
        self.assertEqual(self.refresh_calls(), 1)
        self.now += timedelta(seconds=2)
        allowed = self.refresh(token=self.tokens[1])
        self.assertTrue(allowed["request_sent"])
        self.assertEqual(self.refresh_calls(), 2)
        self.assertEqual(len(self.repo.list_plaid_items(self.household)), 1)

    def test_concurrent_service_instances_claim_only_one_provider_request(self):
        entered, proceed = threading.Event(), threading.Event()
        self.bank.refresh_entered, self.bank.refresh_continue = entered, proceed
        other = LivePlaidService(BudgetRepository(self.repo.db_path, self.repo.settings), self.bank)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.service.request_fresh_data, self.item_id)
            try:
                self.assertTrue(entered.wait(2), "First refresh did not reach the synthetic provider")
                second = executor.submit(other.request_fresh_data, self.item_id)
                duplicate = second.result(timeout=2)
                self.assertFalse(duplicate["request_sent"])
                self.assertFalse(duplicate["refresh"]["can_request"])
            finally:
                proceed.set()
            self.assertTrue(first.result(timeout=5)["request_sent"])
        self.assertEqual(self.refresh_calls(), 1)

    def test_network_uncertainty_remains_visible_and_cooldown_prevents_automatic_retry(self):
        self.bank.refresh_error = PlaidIntegrationError("provider-private-detail synthetic-bank-secret", "PLAID_NETWORK_ERROR")
        first = self.refresh()
        self.assertFalse(first["success"])
        self.assertTrue(first["request_sent"])
        self.assertEqual(first["refresh"]["state"], "unknown")
        self.assertIsNone(first["refresh"]["checked_at"])
        self.assert_sanitized(first)
        second = self.refresh(token=self.tokens[1])
        self.assertFalse(second["request_sent"])
        self.assertEqual(second["refresh"]["state"], "unknown")
        self.assertEqual(self.refresh_calls(), 1)

    def test_inflight_lease_covers_timeout_and_late_response_cannot_clobber_newer_request(self):
        entered, proceed = threading.Event(), threading.Event()
        original_request = self.bank._request
        lock = threading.Lock()
        refresh_count = 0

        def delayed_first(path, payload):
            nonlocal refresh_count
            if path == "/transactions/refresh":
                with lock:
                    refresh_count += 1
                    number = refresh_count
                if number == 1:
                    self.bank.calls.append((path, payload))
                    entered.set()
                    if not proceed.wait(5):
                        raise AssertionError("Test did not release its first synthetic request")
                    raise PlaidIntegrationError("provider-private-detail late failure", "PLAID_NETWORK_ERROR")
            return original_request(path, payload)

        other = LivePlaidService(BudgetRepository(self.repo.db_path, self.repo.settings), self.bank)
        with patch.object(self.bank, "_request", side_effect=delayed_first), ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(self.service.request_fresh_data, self.item_id)
            try:
                self.assertTrue(entered.wait(2))
                self.now += timedelta(seconds=61)
                still_inflight = other.request_fresh_data(self.item_id)
                self.assertFalse(still_inflight["request_sent"])
                self.assertGreater(still_inflight["refresh"]["retry_after_seconds"], 0)
                self.now += timedelta(seconds=60)
                newer = other.request_fresh_data(self.item_id)
                self.assertTrue(newer["request_sent"])
                self.assertEqual(newer["refresh"]["state"], "pending")
            finally:
                proceed.set()
            first.result(timeout=5)
        final = bank_status(self.repo, self.month)["refresh"]
        self.assertEqual(final["state"], "pending")
        self.assertEqual(final["requested_at"], newer["refresh"]["requested_at"])
        self.assertEqual(final["retry_after_seconds"], newer["refresh"]["retry_after_seconds"])
        self.assertEqual(self.refresh_calls(), 2)

    def test_unknown_outcome_can_complete_only_when_bank_update_is_later_imported(self):
        self.bank.refresh_error = PlaidIntegrationError("provider-private-detail", "PLAID_NETWORK_ERROR")
        self.refresh()
        self.assertEqual(self.sync()["refresh"]["state"], "unknown")
        self.advance_bank()
        self.assertEqual(self.sync()["refresh"]["state"], "checked")
        self.assertEqual(self.refresh_calls(), 1)

    def test_malformed_provider_acceptance_is_unknown_and_sanitized(self):
        self.bank.refresh_response = None
        result = self.refresh()
        self.assertFalse(result["success"])
        self.assertEqual(result["refresh"]["state"], "unknown")
        self.assertIsNone(result["refresh"]["checked_at"])
        self.assert_sanitized(result)
        self.assertFalse(self.refresh()["request_sent"])
        self.assertEqual(self.refresh_calls(), 1)

    def test_provider_denial_is_failed_and_does_not_change_import_freshness(self):
        before = bank_status(self.repo, self.month)["transactions_updated_at"]
        self.bank.refresh_error = PlaidIntegrationError("provider-private-detail synthetic-bank-secret", "ITEM_LOGIN_REQUIRED")
        result = self.refresh()
        self.assertFalse(result["success"])
        self.assertEqual(result["refresh"]["state"], "failed")
        self.assertIsNone(result["refresh"]["checked_at"])
        self.assertEqual(bank_status(self.repo, self.month)["transactions_updated_at"], before)
        self.assert_sanitized(result)

    def test_refresh_requires_authentication_household_ownership_and_live_enabled(self):
        status, result = self.request("POST", "/plaid/refresh", {"plaid_item_id": self.item_id})
        self.assertEqual(status, 401, result)
        self.repo.create_household("Other synthetic household", [{"name": "Outsider", "username": "refresh-outsider", "password": "synthetic-refresh-password"}])
        foreign_token = self.repo.authenticate_local_user(login="refresh-outsider", password="synthetic-refresh-password")["token"]
        self.refresh(token=foreign_token, expected=403)
        for value in (True, "1.5", 1.5):
            status, result = self.request("POST", "/plaid/refresh", {"plaid_item_id": value}, token=self.tokens[0])
            self.assertEqual(status, 400, result)
        self.repo.settings = replace(self.repo.settings, plaid_enabled=False)
        status, result = self.request("POST", "/plaid/refresh", {"plaid_item_id": self.item_id}, token=self.tokens[0])
        self.assertEqual(status, 403, result)
        self.assertEqual(self.refresh_calls(), 0)


class LiveRefreshClientTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"SYNTHETIC_REFRESH_SECRET": "synthetic-not-a-credential"})
        environment.start()
        self.addCleanup(environment.stop)
        self.client = LivePlaidClient(PlaidSettings("synthetic-client", "SYNTHETIC_REFRESH_SECRET", "production",
                                                    ("transactions",), ("US",), None))

    def test_refresh_has_longer_timeout_without_changing_other_requests(self):
        with patch("backend.app.live_plaid.build_opener") as factory:
            opener = factory.return_value
            opener.open.return_value.__enter__.return_value.read.return_value = b'{"request_id":"synthetic-response"}'
            self.client._request("/transactions/refresh", {"access_token": "synthetic-test-token"})
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 90)
            self.client._request("/item/get", {"access_token": "synthetic-test-token"})
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 35)

    def test_actual_refresh_rate_limit_code_is_retained_without_provider_details(self):
        response = io.BytesIO(json.dumps({"error_code": "TRANSACTIONS_REFRESH_LIMIT", "error_message": "provider-private-detail"}).encode())
        error = HTTPError("https://synthetic.invalid", 429, "limited", {}, response)
        with patch("backend.app.live_plaid.build_opener") as factory:
            factory.return_value.open.side_effect = error
            with self.assertRaises(PlaidIntegrationError) as raised:
                self.client._request("/transactions/refresh", {"access_token": "synthetic-test-token"})
        self.assertEqual(raised.exception.code, "TRANSACTIONS_REFRESH_LIMIT")
        self.assertNotIn("provider-private-detail", str(raised.exception))

    def test_actual_pagination_mutation_code_restarts_from_original_cursor(self):
        changed = PlaidIntegrationError("synthetic-mutation", "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION")
        final = {"added": [], "modified": [], "removed": [], "has_more": False, "next_cursor": "new-cursor",
                 "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE"}
        with patch.object(self.client, "_request", side_effect=[changed, final]) as request:
            sync, complete = self.client.sync_transactions("synthetic-test-token", "original-cursor")
        self.assertTrue(complete)
        self.assertEqual(sync.next_cursor, "new-cursor")
        self.assertEqual([call.args[1]["cursor"] for call in request.call_args_list], ["original-cursor", "original-cursor"])


class BankRefreshMigrationTests(unittest.TestCase):
    def test_schema_four_upgrade_preserves_funds_tokens_sessions_and_bank_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = BudgetRepository(Path(directory)/"synthetic-v4.sqlite",
                RuntimeSettings(hosted=True, setup_code="s"*40, encryption_key="k"*40))
            with patch.object(migrations, "MIGRATIONS", migrations.MIGRATIONS[:4]):
                repo.initialize()
            household = repo.create_household("Synthetic existing v4 household", [
                {"name": "Existing member", "username": "existing-v4", "password": "synthetic-v4-password"}])
            today = household_today()
            month = repo.create_budget_month(household_id=household, month=today.strftime("%Y-%m"))
            repo.add_payday(household_id=household, payday_date=today+timedelta(days=7))
            item = repo.create_plaid_item(household_id=household, plaid_item_id="synthetic-existing-item",
                                           access_token_ref="synthetic-existing-reference")
            repo.store_plaid_access_token("synthetic-existing-reference", "synthetic-existing-token")
            account = repo.upsert_connected_account(budget_month_id=month, plaid_item_id=item,
                plaid_account_id="synthetic-existing-account", name="Existing checking", account_type="checking",
                balance_cents=15_000, available_balance_cents=15_000, current_balance_cents=15_000)
            fund = repo.create_fund(budget_month_id=month, name="Existing reserve", backing_account_id=account,
                                     monthly_plan_cents=1_000)
            repo.add_fund_entry(fund_id=fund["id"], budget_month_id=month, kind="contribution", amount_cents=1_000,
                               occurred_on=today, idempotency_key="synthetic-existing-contribution")
            auth = repo.authenticate_local_user(login="existing-v4", password="synthetic-v4-password")
            with repo.connect() as connection:
                connection.execute("""INSERT INTO bank_sync_state(plaid_item_id,environment,balance_checked_at,
                    transactions_checked_at,transactions_updated_at,history_complete,balance_error,transaction_error)
                    VALUES (?,'production','2026-01-01T01:00:00Z','2026-01-01T01:01:00Z','2026-01-01T00:00:00Z',1,0,0)""", (item,))
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
                tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_migrations'")]
                columns = {table: [r[1] for r in connection.execute('PRAGMA table_info("'+table+'")')] for table in tables}
                before = {table: [tuple(r) for r in connection.execute('SELECT * FROM "'+table+'" ORDER BY rowid')] for table in tables}
            repo.initialize()
            repo.initialize()
            with repo.connect() as connection:
                after = {table: [tuple(r) for r in connection.execute('SELECT '+','.join('"'+col+'"' for col in columns[table])+' FROM "'+table+'" ORDER BY rowid')] for table in tables}
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], migrations.LATEST_VERSION)
                row = connection.execute("SELECT * FROM bank_sync_state WHERE plaid_item_id=?", (item,)).fetchone()
                self.assertEqual(row["refresh_state"], "idle")
                for field in ("refresh_requested_at", "refresh_checked_at", "refresh_baseline_updated_at", "refresh_next_allowed_at", "refresh_error_code"):
                    self.assertIsNone(row[field])
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(before, after)
            self.assertEqual(repo.get_funds(month)["funds"][0]["balance_cents"], 1_000)
            self.assertEqual(repo.retrieve_plaid_access_token("synthetic-existing-reference"), "synthetic-existing-token")
            self.assertIsNotNone(repo.auth_context_for_token(auth["token"]))


if __name__ == "__main__":
    unittest.main()
