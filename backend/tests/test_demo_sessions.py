"""Demo access and lifecycle tests: identical IDs must never select real data."""
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.db import BudgetRepository
from backend.app.demo_sessions import DemoSessionExpired, DemoSessionManager, _OwnedDemoRoot
from backend.app.hosted import Application
from backend.app.security import RateLimitError


def small_fixture(path):
    repo = BudgetRepository(path)
    repo.initialize()
    household = repo.create_household("Fictional demo family", spouses=[
        {"name": "Demo person", "username": "demo-person", "password": "synthetic-demo-only"}])
    month = repo.create_budget_month(household_id=household, month="2026-09")
    login = repo.authenticate_local_user(login="demo-person", password="synthetic-demo-only")
    return SimpleNamespace(repository=repo, plaid_service=object(), login=login,
                           household_id=household, budget_month_id=month, user_id=login["user"]["id"])


class DemoSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = BudgetRepository(Path(self.temp.name) / "real.sqlite")
        self.repo.initialize()
        self.household = self.repo.create_household("Private household sentinel", spouses=[
            {"name": "Private person", "username": "private-person", "password": "synthetic-private-only"}])
        self.month = self.repo.create_budget_month(household_id=self.household, month="2026-09")
        self.token = self.repo.authenticate_local_user(login="private-person", password="synthetic-private-only")["token"]
        self.app = Application(self.repo)
        self.app.demo_manager = DemoSessionManager(factory=small_fixture)
        self.addCleanup(self.app.demo_manager.close)

    def request(self, method, path, payload=None, token=None, expected=200):
        raw = json.dumps(payload or {}).encode()
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "wsgi.input": io.BytesIO(raw),
                   "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw))}
        if token:
            environ["HTTP_AUTHORIZATION"] = "Bearer " + token
        result = []
        body = b"".join(self.app(environ, lambda code, headers: result.append((int(code.split()[0]), headers))))
        decoded = json.loads(body)
        self.assertEqual(expected, result[0][0], decoded)
        self.assertIn(("Cache-Control", "no-store"), result[0][1])
        return decoded

    def start(self):
        return self.request("POST", "/demo/start", token=self.token)

    def test_start_requires_real_auth_and_returns_only_fictional_identity(self):
        self.request("POST", "/demo/start", expected=401)
        demo = self.start()
        self.assertTrue(demo["demo"])
        self.assertEqual(demo["budget_month_id"], self.month)
        self.assertEqual(demo["household"]["name"], "Fictional demo family")
        self.assertNotIn("Private", json.dumps(demo))
        for secret in ("password_hash", "token_hash", "encryption_key", ".sqlite"):
            self.assertNotIn(secret, json.dumps(demo))
        self.request("POST", "/demo/start", token=demo["token"], expected=401)

    def test_cross_environment_tokens_and_explicit_production_routes_are_rejected(self):
        token = self.start()["token"]
        for method, route, payload in [("GET", "/budget-months", {}),
                ("PATCH", f"/budget-months/{self.month}", {"low_cushion_daily_cents": 1}),
                ("POST", "/plaid/sync", {"plaid_item_id": 1, "sync_type": "balance"})]:
            with self.subTest(route=route):
                self.request(method, route, payload, token=token, expected=401)
                response = self.request(method, "/demo" + route, payload, token=self.token, expected=401)
                self.assertEqual(response["code"], "demo_session_expired")
        self.request("POST", "/demo/auth/login", token=token, expected=403)
        self.request("POST", "/demo/setup/initialize", token=token, expected=403)
        self.request("PATCH", "/demo/settings/password", token=token, expected=403)

    def test_edits_are_isolated_and_exit_discards_with_fresh_reentry(self):
        first = self.start()["token"]
        second = self.start()["token"]
        # Start authenticates the real session; baseline follows that metadata update.
        before = self.repo.db_path.read_bytes()
        self.request("PATCH", f"/demo/budget-months/{self.month}",
                     {"low_cushion_daily_cents": 123}, token=first)
        with self.app.demo_manager.use(first) as session:
            path = session.directory
            self.assertEqual(session.context.repository.list_budget_months(self.household)[0]["low_cushion_daily_cents"], 123)
        with self.app.demo_manager.use(second) as session:
            self.assertNotEqual(session.context.repository.list_budget_months(self.household)[0]["low_cushion_daily_cents"], 123)
        self.request("POST", "/demo/exit", token=first)
        self.assertFalse(path.exists())
        self.request("GET", "/demo/budget-months", token=first, expected=401)
        self.request("GET", "/demo/budget-months", token=second)
        self.assertEqual(before, self.repo.db_path.read_bytes())
        third = self.start()["token"]
        self.assertNotIn(third, (first, second))
        with self.app.demo_manager.use(third) as session:
            self.assertNotEqual(session.context.repository.list_budget_months(self.household)[0]["low_cushion_daily_cents"], 123)

    def test_concurrent_real_and_demo_requests_never_share_context(self):
        demo = self.start()["token"]
        def read(which):
            is_demo = which % 2 == 0
            result = self.request("GET", ("/demo" if is_demo else "") + "/settings/account",
                                  token=demo if is_demo else self.token)
            serialized = json.dumps(result)
            self.assertIn("Fictional demo family" if is_demo else "Private household sentinel", serialized)
            self.assertNotIn("Private household sentinel" if is_demo else "Fictional demo family", serialized)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(read, range(16)))
        self.assertIs(self.app.repository, self.repo)

    def test_cleanup_waits_for_in_flight_request_then_old_token_stays_invalid(self):
        token = self.start()["token"]
        holding, release, retired = threading.Event(), threading.Event(), threading.Event()
        def request():
            with self.app.demo_manager.use(token) as session:
                path = session.directory
                holding.set()
                self.assertTrue(release.wait(5))
                self.assertTrue(path.exists())
        def exit_demo():
            self.app.demo_manager.retire(token)
            retired.set()
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(request)
            self.assertTrue(holding.wait(5))
            ending = pool.submit(exit_demo)
            self.assertFalse(retired.wait(.05))
            release.set()
            pending.result(5)
            ending.result(5)
        with self.assertRaises(DemoSessionExpired):
            with self.app.demo_manager.use(token):
                pass

    def test_expiry_capacity_and_restart_are_bounded(self):
        manager = self.app.demo_manager
        manager.max_sessions = 1
        token = self.start()["token"]
        self.request("POST", "/demo/start", token=self.token, expected=429)
        with manager.use(token) as session:
            directory = session.directory
            session.deadline = time.monotonic() - 1
        self.request("GET", "/demo/budget-months", token=token, expected=401)
        self.assertFalse(directory.exists())
        token = self.start()["token"]
        manager.close()
        self.app.demo_manager = DemoSessionManager(factory=small_fixture)
        self.addCleanup(self.app.demo_manager.close)
        self.request("GET", "/demo/budget-months", token=token, expected=401)
        self.request("GET", "/budget-months", token=self.token)

    def test_failed_seed_cleans_partial_database_without_touching_real_data(self):
        def fail(path):
            path.write_text("synthetic partial seed")
            raise ValueError("Cannot build sample data")
        self.app.demo_manager._factory = fail
        self.request("POST", "/demo/start", token=self.token, expected=400)
        root = Path(self.app.demo_manager._temporary.name)
        self.assertEqual([path.name for path in root.iterdir()], [_OwnedDemoRoot.MARKER])
        self.assertEqual(self.app.demo_manager._sessions, {})
        self.request("GET", "/budget-months", token=self.token)

    def test_failed_deletion_keeps_invalid_token_and_capacity_until_retry(self):
        manager = self.app.demo_manager
        manager.max_sessions = 1
        token = self.start()["token"]
        with manager.use(token) as session:
            directory = session.directory
        with patch.object(manager, "_remove_directory", side_effect=PermissionError("busy synthetic file")):
            self.request("POST", "/demo/exit", token=token)
            response = self.request("GET", "/demo/budget-months", token=token, expected=401)
            self.assertEqual(response["code"], "demo_session_expired")
            self.assertTrue(response["demo"])
            self.request("POST", "/demo/start", token=self.token, expected=429)
            self.assertTrue(directory.exists())
            self.assertEqual(len(manager._sessions), 1)
        manager.prune()
        self.assertFalse(directory.exists())
        self.assertEqual(manager._sessions, {})
        self.start()

    def test_one_busy_directory_does_not_stop_other_expiry(self):
        manager = self.app.demo_manager
        tokens = (self.start()["token"], self.start()["token"])
        directories = []
        for token in tokens:
            with manager.use(token) as session:
                directories.append(session.directory)
                session.deadline = time.monotonic() - 1
        original = manager._remove_directory
        def sometimes_busy(directory):
            if directory == directories[0]:
                raise PermissionError("busy synthetic file")
            original(directory)
        with patch.object(manager, "_remove_directory", side_effect=sometimes_busy):
            manager.prune()
        self.assertTrue(directories[0].exists())
        self.assertFalse(directories[1].exists())
        manager.prune()
        self.assertFalse(directories[0].exists())

    def test_failed_seed_cleanup_remains_tracked_and_bounded(self):
        manager = self.app.demo_manager
        manager.max_sessions = 1
        def fail(path):
            path.write_text("synthetic partial seed")
            raise ValueError("Cannot build sample data")
        manager._factory = fail
        with patch.object(manager, "_remove_directory", side_effect=PermissionError("busy synthetic file")):
            self.request("POST", "/demo/start", token=self.token, expected=400)
            self.assertEqual(len(manager._pending_directories), 1)
            self.request("POST", "/demo/start", token=self.token, expected=429)
        manager.prune()
        self.assertEqual(manager._pending_directories, set())

    def test_database_session_expiry_uses_demo_error_and_discards_context(self):
        token = self.start()["token"]
        with self.app.demo_manager.use(token) as session:
            directory = session.directory
            with session.context.repository.connect() as connection:
                connection.execute("UPDATE auth_sessions SET expires_at=0")
        response = self.request("GET", "/demo/budget-months", token=token, expected=401)
        self.assertEqual(response["code"], "demo_session_expired")
        self.assertTrue(response["demo"])
        self.assertFalse(directory.exists())
        self.assertNotIn("demo", self.request("GET", "/budget-months", token=self.token))

    def test_sweeper_survives_unexpected_cleanup_failure(self):
        manager = self.app.demo_manager
        with patch.object(manager._stop, "wait", side_effect=[False, False, True]), \
             patch.object(manager, "prune", side_effect=[RuntimeError("transient cleanup failure"), None]) as prune, \
             patch.object(_OwnedDemoRoot, "prune_orphans") as orphans:
            manager._sweep()
        self.assertEqual(prune.call_count, 2)
        orphans.assert_called_once()

    def test_start_rate_limit_counts_exited_sessions(self):
        for _ in range(4):
            token = self.start()["token"]
            self.request("POST", "/demo/exit", token=token)
        self.request("POST", "/demo/start", token=self.token, expected=429)
        self.assertEqual(self.app.demo_manager._sessions, {})


class DemoRootCleanupTests(unittest.TestCase):
    def test_next_manager_cleans_crash_orphan_but_preserves_live_roots_and_unowned_data(self):
        with tempfile.TemporaryDirectory() as parent, patch("tempfile.tempdir", parent):
            live = _OwnedDemoRoot()
            try:
                unowned = Path(parent) / (_OwnedDemoRoot.PREFIX + "unowned")
                unowned.mkdir()
                sentinel = unowned / "preserve.txt"
                sentinel.write_text("not a demo-owned root")
                script = (
                    "import os,sys,tempfile\n"
                    "from pathlib import Path\n"
                    "from backend.app.demo_sessions import _OwnedDemoRoot\n"
                    "tempfile.tempdir=sys.argv[1]\n"
                    "root=_OwnedDemoRoot()\n"
                    "(Path(root.name)/'demo.sqlite').write_text('synthetic crash fixture')\n"
                    "print(root.name,flush=True)\n"
                    "os._exit(0)\n"
                )
                result = subprocess.run([sys.executable, "-c", script, parent], check=True,
                    capture_output=True, text=True, timeout=20)
                orphan = Path(result.stdout.strip())
                self.assertTrue(orphan.exists())
                fresh = _OwnedDemoRoot()
                try:
                    self.assertFalse(orphan.exists())
                    self.assertTrue(Path(live.name).exists())
                    self.assertEqual(sentinel.read_text(), "not a demo-owned root")
                finally:
                    fresh.cleanup()
            finally:
                live.cleanup()

    def test_busy_orphan_is_retried_without_deleting_live_root(self):
        with tempfile.TemporaryDirectory() as parent, patch("tempfile.tempdir", parent):
            orphan = _OwnedDemoRoot()
            orphan.owner.close()
            with patch("backend.app.demo_sessions.shutil.rmtree", side_effect=PermissionError("busy synthetic file")):
                _OwnedDemoRoot.prune_orphans()
            self.assertTrue(Path(orphan.name).exists())
            _OwnedDemoRoot.prune_orphans()
            self.assertFalse(Path(orphan.name).exists())


if __name__ == "__main__":
    unittest.main()
