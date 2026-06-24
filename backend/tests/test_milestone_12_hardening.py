from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.app.api import ApiHandler, build_server
from backend.app.plaid import (
    InMemoryPlaidTokenStore,
    PlaidConnectionService,
    PlaidIntegrationError,
    PlaidLinkToken,
)


class Milestone12HardeningApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = build_server(Path(self.temp_dir.name) / "hardening.sqlite", "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.token: str | None = None

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp_dir.cleanup()

    def test_error_payloads_are_consistent_and_sanitized(self) -> None:
        unauthorized = self.get("/settings/account", expect_status=401)
        missing = self.get("/missing-route", expect_status=404)

        self.assert_error_contract(unauthorized, "unauthorized", 401)
        self.assert_error_contract(missing, "not_found", 404)
        self.assertEqual(unauthorized["error"], unauthorized["message"])
        self.assertNotIn("token_hash", json.dumps(unauthorized))

    def test_validation_errors_for_invalid_names_amounts_and_dates(self) -> None:
        setup_error = self.post(
            "/setup/initialize",
            {
                "household_name": "",
                "users": [{"name": "Daniel", "username": "daniel", "password": "daniel-secret"}],
            },
            expect_status=400,
        )
        self.initialize_household()
        self.login()
        budget_month = self.post(
            "/budget-months",
            {"household_id": 1, "month": "2026-06"},
            expect_status=201,
        )
        blank_group = self.post(
            "/budget-groups",
            {"budget_month_id": budget_month["id"], "name": ""},
            expect_status=400,
        )
        invalid_bill = self.post(
            "/expected-bills",
            {"budget_month_id": budget_month["id"], "name": "Water", "amount_cents": -1, "due_on": "2026-06-24"},
            expect_status=400,
        )
        invalid_date = self.post(
            "/paydays",
            {"household_id": 1, "payday_date": "06/30/2026"},
            expect_status=400,
        )

        self.assertIn("household_name is required", setup_error["error"])
        self.assertIn("name is required", blank_group["error"])
        self.assertIn("amount_cents must be positive", invalid_bill["error"])
        self.assertIn("Date fields must use YYYY-MM-DD", invalid_date["error"])

    def test_safe_to_spend_missing_payday_returns_clear_safe_error(self) -> None:
        category_id = self.create_budget_with_category()

        error = self.post(
            "/safe-to-spend",
            {
                "budget_month_id": 1,
                "category_id": category_id,
                "purchase_amount_cents": 500,
                "today": "2026-06-24",
            },
            expect_status=400,
        )

        self.assert_error_contract(error, "validation_error", 400)
        self.assertIn("No upcoming payday configured", error["error"])

    def test_diagnostics_are_authenticated_sanitized_and_report_integrity(self) -> None:
        self.create_budget_with_category()

        unauthenticated = self.get("/app/diagnostics", expect_status=401, use_auth=False)
        diagnostics = self.get("/app/diagnostics")
        serialized = json.dumps(diagnostics)

        self.assert_error_contract(unauthenticated, "unauthorized", 401)
        self.assertIn("integrity", diagnostics)
        self.assertIn("checks", diagnostics["integrity"])
        self.assertNotIn("password", serialized)
        self.assertNotIn("token", serialized)
        self.assertNotIn("secret", serialized)

    def test_diagnostics_catch_split_total_mismatch(self) -> None:
        category_id = self.create_budget_with_category()
        account_id = ApiHandler.repository.add_cash_account(
            budget_month_id=1,
            name="Main Checking",
            account_type="checking",
            balance_cents=100_000,
        )
        transaction_id = ApiHandler.repository.upsert_plaid_transaction(
            cash_account_id=account_id,
            plaid_transaction_id="bad-split",
            amount_cents=-10_00,
            occurred_on=date(2026, 6, 24),
            name="Bad Split",
            merchant_name="Bad Split",
        ).transaction_id
        with ApiHandler.repository.connect() as connection:
            connection.execute(
                """
                INSERT INTO transaction_category_assignments(
                    transaction_id,
                    budget_category_id,
                    amount_cents,
                    source,
                    active
                )
                VALUES (?, ?, 500, 'split', 1)
                """,
                (transaction_id, category_id),
            )

        diagnostics = self.get("/app/diagnostics")
        split_check = self.find_check(diagnostics, "split_totals_match")

        self.assertFalse(split_check["ok"])
        self.assertEqual(split_check["count"], 1)

    def test_diagnostics_catch_archived_category_rule_misuse(self) -> None:
        category_id = self.create_budget_with_category()
        ApiHandler.repository.create_merchant_rule(
            household_id=1,
            merchant_match_text="corner store",
            category_id=category_id,
            actor_user_id=1,
        )
        ApiHandler.repository.update_category(category_id=category_id, archived=True, actor_user_id=1)

        diagnostics = self.get("/app/diagnostics")
        archived_check = self.find_check(diagnostics, "archived_categories_unused")

        self.assertFalse(archived_check["ok"])
        self.assertEqual(archived_check["count"], 1)

    def test_plaid_sandbox_errors_are_sanitized(self) -> None:
        self.initialize_household()
        self.login()
        ApiHandler.plaid_service = PlaidConnectionService(
            repository=ApiHandler.repository,
            client=FailingPlaidClient(),
            token_store=InMemoryPlaidTokenStore(),
        )

        error = self.post("/plaid/link-token", {}, expect_status=503)
        serialized = json.dumps(error)

        self.assert_error_contract(error, "service_unavailable", 503)
        self.assertIn("Plaid Sandbox is not configured", error["error"])
        self.assertNotIn("sensitive backend value", serialized)
        self.assertNotIn("token-ref", serialized)

    def test_settings_password_validation_error_is_sanitized(self) -> None:
        self.initialize_household()
        self.login()

        error = self.patch(
            "/settings/password",
            {"current_password": "daniel-secret", "new_password": "short"},
            expect_status=400,
        )
        serialized = json.dumps(error)

        self.assert_error_contract(error, "validation_error", 400)
        self.assertIn("new_password must be at least 8 characters", error["error"])
        self.assertNotIn("password_hash", serialized)

    def create_budget_with_category(self) -> int:
        self.initialize_household()
        self.login()
        self.post("/budget-months", {"household_id": 1, "month": "2026-06"}, expect_status=201)
        group = self.post("/budget-groups", {"budget_month_id": 1, "name": "Food"}, expect_status=201)
        category = self.post(
            "/categories",
            {"budget_group_id": group["id"], "name": "Groceries", "planned_cents": 50000},
            expect_status=201,
        )
        return int(category["id"])

    def initialize_household(self) -> None:
        self.post(
            "/setup/initialize",
            {
                "household_name": "Daniel and Kara",
                "users": [{"name": "Daniel", "username": "daniel", "password": "daniel-secret"}],
            },
            expect_status=201,
        )

    def login(self) -> None:
        result = self.post(
            "/auth/login",
            {"username": "daniel", "password": "daniel-secret"},
            expect_status=200,
            use_auth=False,
        )
        self.token = str(result["token"])

    def get(self, path: str, *, expect_status: int = 200, use_auth: bool = True) -> dict[str, object]:
        request = Request(f"{self.base_url}{path}", headers=self.auth_headers() if use_auth else {}, method="GET")
        return self.open_json(request, expect_status)

    def post(
        self,
        path: str,
        payload: dict[str, object],
        *,
        expect_status: int = 200,
        use_auth: bool = True,
    ) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=(self.auth_headers() if use_auth else {}) | {"Content-Type": "application/json"},
            method="POST",
        )
        return self.open_json(request, expect_status)

    def patch(self, path: str, payload: dict[str, object], *, expect_status: int = 200) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=self.auth_headers() | {"Content-Type": "application/json"},
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

    def auth_headers(self) -> dict[str, str]:
        if self.token is None:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def assert_error_contract(self, payload: dict[str, object], code: str, status: int) -> None:
        self.assertEqual(payload["code"], code)
        self.assertEqual(payload["status"], status)
        self.assertIsInstance(payload["error"], str)
        self.assertEqual(payload["error"], payload["message"])

    def find_check(self, diagnostics: dict[str, object], name: str) -> dict[str, object]:
        integrity = diagnostics["integrity"]
        self.assertIsInstance(integrity, dict)
        for check in integrity["checks"]:
            if check["name"] == name:
                return check
        raise AssertionError(f"Missing diagnostics check {name}")


class FailingPlaidClient:
    def create_link_token(self, household_id: int) -> PlaidLinkToken:
        raise PlaidIntegrationError(
            "Plaid Sandbox is not configured: sensitive backend value leaked",
            "PLAID_CONFIG_MISSING",
        )


if __name__ == "__main__":
    unittest.main()
