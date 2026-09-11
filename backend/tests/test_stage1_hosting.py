from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from backend.app import migrations
from backend.app.auth import hash_session_token
from backend.app.backup import BackupScheduler, create_backup, restore_backup
from backend.app.db import BudgetRepository
from backend.app.hosted import Application, prepare_application
from backend.app.security import RateLimitError, RuntimeSettings, SecretBox, SecretError
from backend.app.upgrade import upgrade_copy


class Stage1HostingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.settings = RuntimeSettings(hosted=True, setup_code="synthetic-setup-code-" * 3,
                                        encryption_key="synthetic-encryption-key-" * 3)
        self.repo = BudgetRepository(self.directory / "household.sqlite", self.settings)
        self.repo.initialize()
        self.app = Application(self.repo)

    def request(self, method, path, payload=None, token=None, app=None):
        raw = json.dumps(payload).encode() if payload is not None else b""
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "wsgi.input": io.BytesIO(raw),
                   "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw))}
        if token:
            environ["HTTP_AUTHORIZATION"] = "Bearer " + token
        response = {}
        def start(status, headers):
            response.update(status=int(status.split()[0]), headers=dict(headers))
        body = b"".join((app or self.app)(environ, start))
        return response["status"], json.loads(body), response["headers"]

    def users(self):
        return [{"name": "Daniel", "username": "daniel", "password": "synthetic-password-one"},
                {"name": "Kara", "username": "kara", "password": "synthetic-password-two"}]

    def initialize(self):
        self.assertEqual(self.request("POST", "/setup/initialize", {
            "household_name": "Synthetic household", "users": self.users(), "setup_code": self.settings.setup_code,
        })[0], 201)
        status, auth, _ = self.request("POST", "/auth/login", {"username": "daniel", "password": "synthetic-password-one"})
        self.assertEqual(status, 200)
        return auth

    def test_setup_code_is_required_single_use_and_never_serialized(self):
        payload = {"household_name": "Synthetic", "users": self.users()}
        self.assertEqual(self.request("POST", "/setup/initialize", payload)[0], 403)
        self.assertTrue(self.request("GET", "/setup/status")[1]["can_initialize"])
        payload["setup_code"] = self.settings.setup_code
        self.assertEqual(self.request("POST", "/setup/initialize", payload)[0], 201)
        self.assertEqual(self.request("POST", "/setup/initialize", payload)[0], 403)
        status, body, headers = self.request("GET", "/setup/status")
        self.assertFalse(body["can_initialize"])
        self.assertFalse(body["bank_linking_enabled"])
        self.assertNotIn(self.settings.setup_code, json.dumps(body))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("Strict-Transport-Security", headers)

    def test_hosted_setup_rejects_missing_spouse_and_short_password(self):
        users = self.users()
        for changed in [users[:1], [dict(users[0], password="short"), users[1]]]:
            self.assertEqual(self.request("POST", "/setup/initialize", {
                "household_name": "Synthetic", "users": changed, "setup_code": self.settings.setup_code,
            })[0], 400)
        self.assertTrue(self.repo.setup_status()["can_initialize"])

    def test_expiry_logout_and_password_change_revoke_server_sessions(self):
        auth = self.initialize()
        token = auth["token"]
        with self.repo.connect() as connection:
            row = connection.execute("SELECT token_hash,expires_at FROM auth_sessions").fetchone()
        self.assertEqual(row["token_hash"], hash_session_token(token))
        self.assertEqual(row["expires_at"], auth["expires_at"])
        with patch("backend.app.db.time.time", return_value=auth["expires_at"]):
            self.assertEqual(self.request("GET", "/settings/account", token=token)[0], 401)
        self.assertEqual(self.request("POST", "/auth/logout", {}, token=token)[0], 200)
        self.assertEqual(self.request("GET", "/settings/account", token=token)[0], 401)
        tokens = [self.request("POST", "/auth/login", {"username": "daniel", "password": "synthetic-password-one"})[1]["token"] for _ in range(2)]
        self.assertEqual(self.request("PATCH", "/settings/password", {
            "current_password": "synthetic-password-one", "new_password": "synthetic-password-new",
        }, token=tokens[0])[0], 200)
        for token in tokens:
            self.assertEqual(self.request("GET", "/settings/account", token=token)[0], 401)

    def test_login_limits_survive_restart_and_return_retry_guidance(self):
        self.initialize()
        for _ in range(9):
            self.assertEqual(self.request("POST", "/auth/login", {"username": "daniel", "password": "wrong"})[0], 401)
        restarted = Application(BudgetRepository(self.repo.db_path, self.settings))
        status, body, headers = self.request("POST", "/auth/login", {
            "username": "DANIEL", "password": "synthetic-password-one",
        }, app=restarted)
        self.assertEqual(status, 429)
        self.assertEqual(body["code"], "rate_limited")
        self.assertEqual(headers["Retry-After"], "300")
        with patch("backend.app.db.time.time", return_value=time.time() + 301):
            self.assertEqual(self.request("POST", "/auth/login", {"username": "daniel", "password": "synthetic-password-one"})[0], 200)

    def test_throttling_is_atomic_for_concurrent_requests(self):
        def attempt(_):
            try:
                self.repo.consume_auth_attempt("concurrent", limit=5)
                return True
            except RateLimitError:
                return False
        with ThreadPoolExecutor(max_workers=8) as executor:
            self.assertEqual(sum(executor.map(attempt, range(16))), 5)

    def test_hosted_plaid_routes_disabled_and_unexpected_methods_rejected(self):
        token = self.initialize()["token"]
        for route in ["/plaid/link-token", "/plaid/exchange-public-token", "/plaid/sync"]:
            self.assertEqual(self.request("POST", route, {}, token=token)[0], 403)
        self.assertEqual(self.request("OPTIONS", "/health")[0], 405)

    def test_token_vault_encryption_is_authenticated_and_key_bound(self):
        self.repo.store_plaid_access_token("synthetic-reference", "synthetic-private-token")
        with self.repo.connect() as connection:
            stored = connection.execute("SELECT access_token FROM plaid_access_tokens").fetchone()[0]
        self.assertNotIn("synthetic-private-token", stored)
        self.assertEqual(self.repo.retrieve_plaid_access_token("synthetic-reference"), "synthetic-private-token")
        wrong = BudgetRepository(self.repo.db_path, RuntimeSettings(encryption_key="different-synthetic-key" * 3))
        with self.assertRaises(SecretError):
            wrong.initialize()
        with self.assertRaises(SecretError):
            BudgetRepository(self.repo.db_path).retrieve_plaid_access_token("synthetic-reference")
        with self.repo.connect() as connection:
            connection.execute("UPDATE plaid_access_tokens SET access_token = 'plaintext'")
        with self.assertRaises(SecretError):
            self.repo.initialize()

    def test_versioned_upgrade_preserves_money_and_invalidates_legacy_sessions(self):
        auth = self.initialize()
        month = self.repo.create_budget_month(household_id=auth["household"]["id"], month="2026-09", included_account_balance_cents=123456)
        with self.repo.connect() as connection:
            connection.execute("DROP TABLE schema_migrations")
            connection.execute("PRAGMA user_version = 0")
            connection.execute("UPDATE auth_sessions SET expires_at = NULL")
        self.repo.initialize()
        self.repo.initialize()
        self.assertEqual(self.repo.get_summary(month, date(2026, 9, 11)).included_account_balance_cents, 123456)
        self.assertIsNone(self.repo.auth_context_for_token(auth["token"]))
        with self.repo.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], migrations.LATEST_VERSION)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 2)

    def test_migrations_rollback_ddl_and_reject_future_schema(self):
        path = self.directory / "rollback.sqlite"
        def fail(connection):
            connection.execute("CREATE TABLE should_rollback(id INTEGER)")
            raise RuntimeError("Synthetic migration failure")
        with closing(sqlite3.connect(path)) as connection:
            with patch.object(migrations, "MIGRATIONS", [(1, "fails", fail)]):
                with self.assertRaises(RuntimeError):
                    migrations.migrate(connection)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0], 0)
            connection.execute("PRAGMA user_version = 999")
            with self.assertRaises(RuntimeError):
                migrations.migrate(connection)

    def test_offline_upgrade_encrypts_legacy_tokens_without_changing_original(self):
        source = self.directory / "legacy.sqlite"
        legacy = BudgetRepository(source)
        legacy.initialize()
        legacy.create_household("Synthetic old household")
        legacy.store_plaid_access_token("synthetic-old-ref", "synthetic-old-private-token")
        with legacy.connect() as connection:
            connection.execute("DROP TABLE schema_migrations")
            connection.execute("PRAGMA user_version=0")
        original = source.read_bytes()
        destination = self.directory / "upgraded.sqlite"
        upgrade_copy(source, destination, self.directory / "before.ffbackup", self.settings.encryption_key)
        upgraded = BudgetRepository(destination, self.settings)
        upgraded.initialize()
        self.assertEqual(upgraded.retrieve_plaid_access_token("synthetic-old-ref"), "synthetic-old-private-token")
        self.assertNotIn(b"synthetic-old-private-token", destination.read_bytes())
        self.assertEqual(source.read_bytes(), original)

    def test_backup_captures_committed_wal_and_preserves_uncommitted_isolation(self):
        with self.repo.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        self.repo.create_household("Committed synthetic household")
        with closing(sqlite3.connect(self.repo.db_path)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO households(name) VALUES ('Uncommitted synthetic household')")
            backup = create_backup(self.repo.db_path, self.directory / "wal.ffbackup", self.settings.encryption_key)
            writer.rollback()
        restored = restore_backup(backup, self.directory / "wal-restored.sqlite", self.settings.encryption_key)
        with closing(sqlite3.connect(restored)) as reader:
            self.assertEqual(reader.execute("SELECT name FROM households").fetchall(), [("Committed synthetic household",)])

    def test_backup_restore_preserves_finances_and_does_not_resurrect_sessions(self):
        auth = self.initialize()
        month = self.repo.create_budget_month(household_id=auth["household"]["id"], month="2026-09", included_account_balance_cents=100000)
        self.repo.add_payday(household_id=auth["household"]["id"], payday_date=date(2026, 9, 16))
        group = self.repo.add_budget_group(budget_month_id=month, name="Food")
        category = self.repo.add_category(budget_group_id=group, name="Groceries", planned_cents=20000)
        self.repo.record_spending(category_id=category, amount_cents=1234, occurred_on=date(2026, 9, 11))
        expected = self.repo.get_summary(month, date(2026, 9, 11))
        backup = create_backup(self.repo.db_path, self.directory / "snapshot.ffbackup", self.settings.encryption_key)
        self.assertNotIn(b"Synthetic household", backup.read_bytes())
        restored_path = restore_backup(backup, self.directory / "restored.sqlite", self.settings.encryption_key)
        restored = BudgetRepository(restored_path, self.settings)
        restored.initialize()
        self.assertEqual(restored.get_summary(month, date(2026, 9, 11)), expected)
        self.assertIsNone(restored.auth_context_for_token(auth["token"]))
        self.assertIsNotNone(restored.authenticate_local_user("kara", "synthetic-password-two"))
        before = self.repo.db_path.read_bytes()
        with self.assertRaises(FileExistsError):
            restore_backup(backup, self.repo.db_path, self.settings.encryption_key)
        self.assertEqual(self.repo.db_path.read_bytes(), before)

    def test_corrupt_backup_or_wrong_key_never_creates_a_database(self):
        backup = create_backup(self.repo.db_path, self.directory / "snapshot.ffbackup", self.settings.encryption_key)
        output = self.directory / "must-not-exist.sqlite"
        with self.assertRaises(SecretError):
            restore_backup(backup, output, "different-synthetic-key" * 3)
        content = bytearray(backup.read_bytes())
        content[len(content) // 2] ^= 1
        backup.write_bytes(content)
        with self.assertRaises(SecretError):
            restore_backup(backup, output, self.settings.encryption_key)
        self.assertFalse(output.exists())

    def test_scheduler_checks_restore_and_readiness_reports_backup_failure(self):
        scheduler = BackupScheduler(self.repo.db_path, self.directory / "backups", self.settings.encryption_key)
        app = Application(self.repo, scheduler)
        self.assertEqual(self.request("GET", "/ready", app=app)[0], 503)
        scheduler.snapshot()
        self.assertEqual(self.request("GET", "/ready", app=app)[0], 200)
        scheduler.failed = True
        self.assertEqual(self.request("GET", "/ready", app=app)[0], 503)

    def test_hosted_configuration_fails_closed_and_checks_timezone(self):
        good = {"FF_MODE": "hosted", "FF_SETUP_CODE": self.settings.setup_code,
                "FF_ENCRYPTION_KEY": self.settings.encryption_key}
        for update in [{"FF_SETUP_CODE": ""}, {"FF_ENCRYPTION_KEY": "short"}, {"PLAID_ENV": "production"},
                       {"PLAID_SECRET": "synthetic"}, {"COACH_PROVIDER": "openai"}, {"OPENAI_API_KEY": "synthetic"},
                       {"FF_SETUP_CODE": self.settings.encryption_key}]:
            with patch.dict(os.environ, {**good, **update}, clear=True):
                with self.assertRaises((ValueError, SecretError)):
                    RuntimeSettings.from_env()
        with patch.dict(os.environ, {**good, "FF_TIMEZONE": "Not/A_Timezone"}, clear=True):
            from zoneinfo import ZoneInfoNotFoundError
            with self.assertRaises(ZoneInfoNotFoundError):
                RuntimeSettings.from_env()

    def test_backup_retention_bounds_age_and_space_while_keeping_two_recovery_points(self):
        scheduler = BackupScheduler(self.repo.db_path, self.directory / "backups", self.settings.encryption_key)
        old = scheduler.snapshot()
        os.utime(old, (time.time() - 8 * 86400,) * 2)
        second = scheduler.snapshot()
        self.assertTrue(old.exists())  # Retain a second recovery point even when old.
        third = scheduler.snapshot()
        self.assertFalse(old.exists())
        with patch("backend.app.backup.MAX_BACKUP_STORAGE_BYTES", 1):
            newest = scheduler.snapshot()
        remaining = list(scheduler.directory.glob("backup-*.ffbackup"))
        self.assertEqual(len(remaining), 2)
        self.assertIn(newest, remaining)
        for index, archive in enumerate(remaining):
            restore_backup(archive, self.directory / f"retained-{index}.sqlite", self.settings.encryption_key)

    def test_hosted_startup_preserves_household_and_checks_recovery_before_serving(self):
        auth = self.initialize()
        directory = self.directory / "backups"
        for index in range(5):
            create_backup(self.repo.db_path, directory / f"pre-upgrade-{index}.ffbackup", self.settings.encryption_key)
        environment = {"FF_MODE": "hosted", "FF_SETUP_CODE": self.settings.setup_code,
                       "FF_ENCRYPTION_KEY": self.settings.encryption_key, "FF_DB_PATH": str(self.repo.db_path),
                       "FF_BACKUP_DIR": str(directory)}
        with patch.dict(os.environ, environment, clear=True):
            app = prepare_application()
        try:
            self.assertEqual(self.request("GET", "/ready", app=app)[0], 200)
            self.assertEqual(self.request("GET", "/settings/account", token=auth["token"], app=app)[0], 200)
            self.assertEqual(len(list(directory.glob("pre-upgrade-*.ffbackup"))), 3)
        finally:
            app.backups.stop_event.set()
        original = self.repo.db_path.read_bytes()
        with patch.dict(os.environ, {**environment, "FF_ENCRYPTION_KEY": "different-synthetic-key" * 3}, clear=True):
            with self.assertRaises(SecretError):
                prepare_application()
        self.assertEqual(original, self.repo.db_path.read_bytes())

    def test_actual_waitress_http_flow(self):
        from waitress import create_server
        server = create_server(self.app, host="127.0.0.1", port=0, threads=2, max_request_body_size=262144)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", int(server.effective_port), timeout=5)
            connection.request("GET", "/health")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()), {"ok": True})
            connection.close()
            connection = HTTPConnection("127.0.0.1", int(server.effective_port), timeout=5)
            connection.request("GET", "/budget-months")
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            self.assertNotIn(b"Traceback", response.read())
            connection.close()
        finally:
            server.task_dispatcher.shutdown()
            server.close()
            thread.join(timeout=5)
