from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.app.api import build_server
from backend.app.auth import verify_password


class SetupSettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = build_server(Path(self.temp_dir.name) / "setup.sqlite", "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp_dir.cleanup()

    def test_setup_status_on_empty_database(self) -> None:
        status = self.get("/setup/status")

        self.assertFalse(status["initialized"])
        self.assertFalse(status["household_exists"])
        self.assertFalse(status["users_exist"])
        self.assertTrue(status["can_initialize"])
        self.assertNotIn("current_user", status)

    def test_setup_creates_private_household_and_users_with_hashed_passwords(self) -> None:
        result = self.initialize_household()

        self.assertEqual(result["household"]["name"], "Daniel and Kara")
        self.assertEqual([user["username"] for user in result["users"]], ["daniel", "kara"])
        serialized = json.dumps(result)
        self.assertNotIn("daniel-secret", serialized)
        self.assertNotIn("password_hash", serialized)
        with self.repository().connect() as connection:
            rows = connection.execute("SELECT username, password_hash FROM users ORDER BY username").fetchall()
        self.assertTrue(verify_password("daniel-secret", rows[0]["password_hash"]))
        self.assertTrue(verify_password("kara-secret", rows[1]["password_hash"]))
        self.assertNotEqual("daniel-secret", rows[0]["password_hash"])

    def test_setup_is_blocked_after_initialization(self) -> None:
        self.initialize_household()

        blocked = self.initialize_household(expect_status=403)
        create_household = self.post(
            "/households",
            {"name": "Second Household"},
            token=str(self.login()["token"]),
            expect_status=403,
        )

        self.assertIn("Setup is only available", blocked["error"])
        self.assertIn("Household creation is not available", create_household["error"])

    def test_login_works_after_setup_and_setup_status_includes_current_context_when_authenticated(self) -> None:
        self.initialize_household()
        auth = self.login()

        status = self.get("/setup/status", token=str(auth["token"]))

        self.assertEqual(auth["user"]["username"], "daniel")
        self.assertEqual(status["current_user"]["username"], "daniel")
        self.assertEqual(status["current_household"]["name"], "Daniel and Kara")

    def test_private_settings_require_auth_and_return_sanitized_summary(self) -> None:
        self.initialize_household()
        unauthorized = self.get("/settings/account", expect_status=401)
        summary = self.get("/settings/account", token=str(self.login()["token"]))
        serialized = json.dumps(summary)

        self.assertEqual(unauthorized["error"], "Authentication required")
        self.assertEqual(summary["user"]["username"], "daniel")
        self.assertEqual(summary["household"]["name"], "Daniel and Kara")
        self.assertNotIn("password", serialized)
        self.assertNotIn("hash", serialized)
        self.assertNotIn("token", serialized)

    def test_password_change_requires_current_password_updates_hash_and_allows_new_login(self) -> None:
        self.initialize_household()
        token = str(self.login()["token"])
        wrong_current = self.patch(
            "/settings/password",
            {"current_password": "wrong", "new_password": "new-daniel-secret"},
            token=token,
            expect_status=403,
        )
        with self.repository().connect() as connection:
            old_hash = connection.execute("SELECT password_hash FROM users WHERE username = 'daniel'").fetchone()["password_hash"]

        self.patch(
            "/settings/password",
            {"current_password": "daniel-secret", "new_password": "new-daniel-secret"},
            token=token,
        )
        with self.repository().connect() as connection:
            new_hash = connection.execute("SELECT password_hash FROM users WHERE username = 'daniel'").fetchone()["password_hash"]

        self.assertIn("Current password is incorrect", wrong_current["error"])
        self.assertNotEqual(old_hash, new_hash)
        self.assertTrue(verify_password("new-daniel-secret", new_hash))
        self.assertEqual(self.login(password="new-daniel-secret")["user"]["username"], "daniel")

    def test_password_and_display_name_changes_emit_sanitized_events(self) -> None:
        self.initialize_household()
        token = str(self.login()["token"])

        self.patch("/settings/display-name", {"display_name": "Daniel W."}, token=token)
        self.patch(
            "/settings/password",
            {"current_password": "daniel-secret", "new_password": "new-daniel-secret"},
            token=token,
        )
        events = self.get("/households/1/notifications", token=token)["notifications"]
        serialized = json.dumps(events)

        event_types = {event["event_type"] for event in events}
        self.assertIn("user_display_name_changed", event_types)
        self.assertIn("password_changed", event_types)
        self.assertNotIn("new-daniel-secret", serialized)
        self.assertNotIn("password_hash", serialized)

    def test_starter_budget_creation_only_when_no_budget_month_exists(self) -> None:
        self.initialize_household()
        token = str(self.login()["token"])

        created = self.post(
            "/starter-budget/current-month",
            {"today": "2026-06-24", "next_payday": "2026-06-28"},
            token=token,
            expect_status=201,
        )
        blocked = self.post("/starter-budget/current-month", {"today": "2026-06-24"}, token=token, expect_status=403)
        months = self.get("/budget-months", token=token)["budget_months"]
        detail = self.get(f"/budget-months/{created['id']}/budget-detail", token=token)

        self.assertEqual(created["month"], "2026-06")
        self.assertIn("only be created when no budget month exists", blocked["error"])
        self.assertEqual(len(months), 1)
        self.assertGreaterEqual(len(detail["groups"]), 1)

    def test_starter_budget_does_not_overwrite_existing_budget_data(self) -> None:
        self.initialize_household()
        token = str(self.login()["token"])
        created = self.post(
            "/budget-months",
            {"household_id": 1, "month": "2026-06", "included_account_balance_cents": 12345},
            token=token,
            expect_status=201,
        )

        blocked = self.post("/starter-budget/current-month", {"today": "2026-06-24"}, token=token, expect_status=403)
        with self.repository().connect() as connection:
            month = connection.execute("SELECT * FROM budget_months WHERE id = ?", (created["id"],)).fetchone()
            group_count = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM budget_groups
                WHERE budget_month_id = ?
                """,
                (created["id"],),
            ).fetchone()["count"]

        self.assertIn("only be created", blocked["error"])
        self.assertEqual(month["included_account_balance_cents"], 12345)
        self.assertEqual(group_count, 0)

    def test_diagnostics_response_is_authenticated_and_sanitized(self) -> None:
        self.initialize_household()
        unauthenticated = self.get("/app/diagnostics", expect_status=401)
        diagnostics = self.get("/app/diagnostics", token=str(self.login()["token"]))
        serialized = json.dumps(diagnostics)

        self.assertEqual(unauthenticated["error"], "Authentication required")
        self.assertTrue(diagnostics["backend_reachable"])
        self.assertTrue(diagnostics["database_initialized"])
        self.assertEqual(diagnostics["plaid_mode"], "sandbox")
        self.assertTrue(diagnostics["plaid_sandbox_only"])
        self.assertNotIn("password", serialized)
        self.assertNotIn("token", serialized)
        self.assertNotIn("secret", serialized)

    def initialize_household(self, *, expect_status: int = 201) -> dict[str, object]:
        return self.post(
            "/setup/initialize",
            {
                "household_name": "Daniel and Kara",
                "users": [
                    {
                        "name": "Daniel",
                        "username": "daniel",
                        "email": "daniel@example.test",
                        "password": "daniel-secret",
                    },
                    {
                        "name": "Kara",
                        "username": "kara",
                        "email": "kara@example.test",
                        "password": "kara-secret",
                    },
                ],
            },
            expect_status=expect_status,
        )

    def login(self, *, password: str = "daniel-secret") -> dict[str, object]:
        return self.post("/auth/login", {"username": "daniel", "password": password})

    def repository(self):
        from backend.app.api import ApiHandler

        return ApiHandler.repository

    def get(self, path: str, *, token: str | None = None, expect_status: int = 200) -> dict[str, object]:
        request = Request(f"{self.base_url}{path}", headers=self.auth_headers(token), method="GET")
        return self.open_json(request, expect_status)

    def post(
        self,
        path: str,
        payload: dict[str, object],
        *,
        token: str | None = None,
        expect_status: int = 200,
    ) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=self.auth_headers(token) | {"Content-Type": "application/json"},
            method="POST",
        )
        return self.open_json(request, expect_status)

    def patch(
        self,
        path: str,
        payload: dict[str, object],
        *,
        token: str | None = None,
        expect_status: int = 200,
    ) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=self.auth_headers(token) | {"Content-Type": "application/json"},
            method="PATCH",
        )
        return self.open_json(request, expect_status)

    def open_json(self, request: Request, expect_status: int) -> dict[str, object]:
        try:
            with urlopen(request, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, expect_status)
                return body
        except HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            if exc.code != expect_status:
                raise
            return body

    def auth_headers(self, token: str | None) -> dict[str, str]:
        if token is None:
            return {}
        return {"Authorization": f"Bearer {token}"}


if __name__ == "__main__":
    unittest.main()
