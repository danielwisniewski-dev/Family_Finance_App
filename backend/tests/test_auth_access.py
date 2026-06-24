from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.app.auth import hash_session_token
from backend.app.api import ApiHandler, build_server
from backend.app.plaid import (
    InMemoryPlaidTokenStore,
    PlaidAccountSnapshot,
    PlaidConnectionService,
    PlaidLinkToken,
    PlaidPublicTokenExchange,
    PlaidTransactionSync,
)


class PrivateHouseholdAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = build_server(Path(self.temp_dir.name) / "auth.sqlite", "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

        self.daniel = self.seed_household(
            household_name="Daniel and Kara",
            username="daniel",
            email="daniel@example.test",
            password="daniel-local-test",
            month="2026-06",
            transaction_id="daniel-txn-1",
        )
        self.kara = self.seed_household(
            household_name="Other Household",
            username="kara",
            email="kara@example.test",
            password="kara-local-test",
            month="2026-07",
            transaction_id="kara-txn-1",
        )
        ApiHandler.plaid_service = PlaidConnectionService(
            ApiHandler.repository,
            client=ApiFakePlaidClient(),
            token_store=InMemoryPlaidTokenStore(),
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp_dir.cleanup()

    def test_login_succeeds_with_valid_credentials_and_returns_safe_context(self) -> None:
        result = self.login("daniel", "daniel-local-test")

        self.assertTrue(result["token"])
        self.assertEqual(result["user"]["username"], "daniel")
        self.assertEqual(result["user"]["household_id"], self.daniel["household_id"])
        self.assertEqual(result["household"]["id"], self.daniel["household_id"])
        serialized = json.dumps(result)
        self.assertNotIn("password", serialized)
        self.assertNotIn("password_hash", serialized)

    def test_session_token_is_stored_hashed_and_not_exposed_after_login(self) -> None:
        result = self.login("daniel", "daniel-local-test")
        token = str(result["token"])

        with ApiHandler.repository.connect() as connection:
            row = connection.execute(
                "SELECT token_hash FROM auth_sessions ORDER BY id DESC LIMIT 1"
            ).fetchone()
        summary = self.get(f"/budget-months/{self.daniel['budget_month_id']}/summary", token=token)
        serialized_summary = json.dumps(summary)

        self.assertEqual(row["token_hash"], hash_session_token(token))
        self.assertNotEqual(row["token_hash"], token)
        self.assertNotIn(token, serialized_summary)
        self.assertNotIn("token_hash", serialized_summary)

    def test_login_fails_with_invalid_credentials(self) -> None:
        error = self.post(
            "/auth/login",
            {"username": "daniel", "password": "wrong-password"},
            expect_status=401,
        )

        self.assertEqual(error["error"], "Invalid credentials")

    def test_public_household_signup_is_not_available(self) -> None:
        unauthenticated = self.post(
            "/households",
            {
                "name": "Public Signup Attempt",
                "spouses": [{"name": "New", "username": "new", "password": "not-used"}],
            },
            expect_status=401,
        )
        token = str(self.login("daniel", "daniel-local-test")["token"])
        authenticated = self.post(
            "/households",
            {
                "name": "Second Household Attempt",
                "spouses": [{"name": "New", "username": "new2", "password": "not-used"}],
            },
            token=token,
            expect_status=403,
        )

        self.assertEqual(unauthenticated["error"], "Authentication required")
        self.assertIn("Household creation is not available", authenticated["error"])

    def test_protected_financial_routes_reject_unauthenticated_requests(self) -> None:
        summary_error = self.get(
            f"/budget-months/{self.daniel['budget_month_id']}/summary",
            expect_status=401,
        )
        safe_to_spend_error = self.post(
            "/safe-to-spend",
            {
                "budget_month_id": self.daniel["budget_month_id"],
                "category_id": self.daniel["category_id"],
                "purchase_amount_cents": 500,
                "today": "2026-06-21",
            },
            expect_status=401,
        )

        self.assertEqual(summary_error["error"], "Authentication required")
        self.assertEqual(safe_to_spend_error["error"], "Authentication required")

    def test_authenticated_user_can_access_own_household_data(self) -> None:
        token = str(self.login("daniel", "daniel-local-test")["token"])

        summary = self.get(f"/budget-months/{self.daniel['budget_month_id']}/summary", token=token)
        transactions = self.get(f"/budget-months/{self.daniel['budget_month_id']}/transactions", token=token)

        self.assertEqual(summary["budget_month_id"], self.daniel["budget_month_id"])
        self.assertEqual(transactions["transactions"][0]["transaction"]["id"], self.daniel["transaction_id"])

    def test_user_cannot_access_another_households_budget_data(self) -> None:
        token = str(self.login("daniel", "daniel-local-test")["token"])

        error = self.get(f"/budget-months/{self.kara['budget_month_id']}/summary", token=token, expect_status=403)

        self.assertIn("Budget month", error["error"])

    def test_user_cannot_access_another_households_transactions(self) -> None:
        token = str(self.login("daniel", "daniel-local-test")["token"])

        detail_error = self.get(f"/transactions/{self.kara['transaction_id']}", token=token, expect_status=403)
        list_error = self.get(
            f"/budget-months/{self.kara['budget_month_id']}/transactions",
            token=token,
            expect_status=403,
        )

        self.assertIn("Transaction", detail_error["error"])
        self.assertIn("Budget month", list_error["error"])

    def test_user_cannot_access_another_households_notifications(self) -> None:
        token = str(self.login("daniel", "daniel-local-test")["token"])

        list_error = self.get(
            f"/budget-months/{self.kara['budget_month_id']}/notifications",
            token=token,
            expect_status=403,
        )
        read_error = self.patch(
            f"/notifications/{self.kara['notification_id']}/read",
            {},
            token=token,
            expect_status=403,
        )

        self.assertIn("Budget month", list_error["error"])
        self.assertIn("Notification", read_error["error"])

    def test_user_cannot_access_another_households_accounts_categories_coach_or_plaid(self) -> None:
        token = str(self.login("daniel", "daniel-local-test")["token"])
        kara_plaid_item_id = ApiHandler.repository.create_plaid_item(
            household_id=self.kara["household_id"],
            plaid_item_id="kara-plaid-item",
            access_token_ref="kara-token-ref",
        )

        account_error = self.patch(
            f"/accounts/{self.kara['account_id']}",
            {"included_in_cash_reality": False},
            token=token,
            expect_status=403,
        )
        category_error = self.patch(
            f"/categories/{self.kara['category_id']}",
            {"planned_cents": 99_999},
            token=token,
            expect_status=403,
        )
        coach_error = self.post(
            "/coach/budget-change-suggestion",
            {
                "budget_month_id": self.kara["budget_month_id"],
                "to_category_id": self.kara["category_id"],
                "amount_cents": 500,
                "today": "2026-06-21",
            },
            token=token,
            expect_status=403,
        )
        plaid_exchange_error = self.post(
            "/plaid/exchange-public-token",
            {
                "household_id": self.kara["household_id"],
                "budget_month_id": self.kara["budget_month_id"],
                "public_token": "public-sandbox-placeholder",
            },
            token=token,
            expect_status=403,
        )
        plaid_sync_error = self.post(
            "/plaid/sync",
            {
                "sync_type": "balance",
                "plaid_item_id": kara_plaid_item_id,
            },
            token=token,
            expect_status=403,
        )

        self.assertIn("Account", account_error["error"])
        self.assertIn("Category", category_error["error"])
        self.assertIn("Budget month", coach_error["error"])
        self.assertIn("Budget month", plaid_exchange_error["error"])
        self.assertIn("Plaid item", plaid_sync_error["error"])

    def test_plaid_link_token_route_requires_authentication(self) -> None:
        unauthenticated = self.post("/plaid/link-token", {}, expect_status=401)
        token = str(self.login("daniel", "daniel-local-test")["token"])
        authenticated = self.post("/plaid/link-token", {}, token=token, expect_status=201)

        self.assertEqual(unauthenticated["error"], "Authentication required")
        self.assertEqual(authenticated["link_token"], "link-token-api-test")

    def test_plaid_public_token_exchange_requires_authentication(self) -> None:
        error = self.post(
            "/plaid/exchange-public-token",
            {
                "budget_month_id": self.daniel["budget_month_id"],
                "public_token": "public-sandbox-token",
            },
            expect_status=401,
        )

        self.assertEqual(error["error"], "Authentication required")

    def test_plaid_public_token_exchange_uses_authenticated_household_and_sanitizes_response(self) -> None:
        token = str(self.login("daniel", "daniel-local-test")["token"])

        result = self.post(
            "/plaid/exchange-public-token",
            {
                "budget_month_id": self.daniel["budget_month_id"],
                "public_token": "public-sandbox-token",
            },
            token=token,
            expect_status=201,
        )
        plaid_item = ApiHandler.repository.get_plaid_item(int(result["plaid_item"]["id"]))
        serialized = json.dumps(result)

        self.assertEqual(plaid_item.household_id, self.daniel["household_id"])
        self.assertNotIn("access-token", serialized)
        self.assertNotIn("access_token", serialized)
        self.assertNotIn("access_token_ref", serialized)
        self.assertNotIn(plaid_item.access_token_ref, serialized)
        self.assertEqual(result["accounts"][0]["account_type"], "checking")

    def test_safe_to_spend_uses_authenticated_household_context(self) -> None:
        token = str(self.login("daniel", "daniel-local-test")["token"])

        result = self.post(
            "/safe-to-spend",
            {
                "budget_month_id": self.daniel["budget_month_id"],
                "category_id": self.daniel["category_id"],
                "purchase_amount_cents": 1_000,
                "today": "2026-06-21",
            },
            token=token,
        )
        cross_household = self.post(
            "/safe-to-spend",
            {
                "budget_month_id": self.kara["budget_month_id"],
                "category_id": self.kara["category_id"],
                "purchase_amount_cents": 1_000,
                "today": "2026-06-21",
            },
            token=token,
            expect_status=403,
        )

        self.assertEqual(result["warning_level"], "safe")
        self.assertIn("Budget month", cross_household["error"])

    def test_notification_unread_and_read_state_uses_authenticated_user_by_default(self) -> None:
        daniel_token = str(self.login("daniel", "daniel-local-test")["token"])
        kara_user_id = int(self.kara["user_id"])

        daniel_before = self.get(
            f"/budget-months/{self.daniel['budget_month_id']}/notifications/unread-count?user_id={kara_user_id}",
            token=daniel_token,
        )
        self.patch(
            f"/notifications/{self.daniel['notification_id']}/read",
            {"user_id": kara_user_id},
            token=daniel_token,
        )
        daniel_after = self.get(
            f"/budget-months/{self.daniel['budget_month_id']}/notifications/unread-count?user_id={kara_user_id}",
            token=daniel_token,
        )

        with ApiHandler.repository.connect() as connection:
            daniel_read = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM notification_event_reads
                WHERE event_id = ? AND user_id = ?
                """,
                (self.daniel["notification_id"], self.daniel["user_id"]),
            ).fetchone()["count"]
            kara_read = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM notification_event_reads
                WHERE event_id = ? AND user_id = ?
                """,
                (self.daniel["notification_id"], kara_user_id),
            ).fetchone()["count"]

        self.assertGreaterEqual(daniel_before["unread_count"], 1)
        self.assertEqual(daniel_after["unread_count"], daniel_before["unread_count"] - 1)
        self.assertEqual(daniel_read, 1)
        self.assertEqual(kara_read, 0)

    def test_api_responses_do_not_expose_sensitive_provider_or_token_fields(self) -> None:
        token = str(self.login("daniel", "daniel-local-test")["token"])
        plaid_item_id = ApiHandler.repository.create_plaid_item(
            household_id=self.daniel["household_id"],
            plaid_item_id="secret-plaid-item-id",
            access_token_ref="secret-token-ref",
        )
        ApiHandler.repository.upsert_connected_account(
            plaid_item_id=plaid_item_id,
            budget_month_id=self.daniel["budget_month_id"],
            plaid_account_id="account-id",
            name="Connected Checking",
            account_type="checking",
            balance_cents=90_000,
            included_in_cash_reality=True,
        )
        ApiHandler.repository.create_notification_event(
            household_id=self.daniel["household_id"],
            budget_month_id=self.daniel["budget_month_id"],
            event_type="sensitive_metadata",
            actor_user_id=self.daniel["user_id"],
            affected_entity_type="test",
            affected_entity_id=None,
            title="Sensitive",
            message="Sensitive metadata test",
            metadata={
                "access_token_ref": "secret-token-ref",
                "openai_api_key": "sk-secret",
                "raw_provider": {"detail": "internal"},
                "safe": "visible",
            },
        )

        accounts = self.get(f"/budget-months/{self.daniel['budget_month_id']}/accounts", token=token)
        notifications = self.get(f"/budget-months/{self.daniel['budget_month_id']}/notifications", token=token)
        coach = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": self.daniel["budget_month_id"],
                "category_id": self.daniel["category_id"],
                "amount_cents": 1_000,
                "today": "2026-06-21",
            },
            token=token,
        )
        serialized = json.dumps({"accounts": accounts, "notifications": notifications, "coach": coach})

        self.assertNotIn("secret-token-ref", serialized)
        self.assertNotIn("access_token_ref", serialized)
        self.assertNotIn("sk-secret", serialized)
        self.assertNotIn("openai_api_key", serialized)
        self.assertNotIn("raw_provider", serialized)

    def seed_household(
        self,
        *,
        household_name: str,
        username: str,
        email: str,
        password: str,
        month: str,
        transaction_id: str,
    ) -> dict[str, int]:
        household_id = ApiHandler.repository.create_household(
            household_name,
            spouses=[
                {
                    "name": username.title(),
                    "username": username,
                    "email": email,
                    "password": password,
                }
            ],
        )
        with ApiHandler.repository.connect() as connection:
            user_id = int(
                connection.execute(
                    "SELECT id FROM users WHERE household_id = ?",
                    (household_id,),
                ).fetchone()["id"]
            )
        token = str(self.login(username, password)["token"])
        budget_month = self.post(
            "/budget-months",
            {
                "household_id": household_id,
                "month": month,
                "included_account_balance_cents": 100_000,
            },
            token=token,
            expect_status=201,
        )
        group = self.post(
            "/budget-groups",
            {
                "budget_month_id": budget_month["id"],
                "name": "Everyday",
            },
            token=token,
            expect_status=201,
        )
        category = self.post(
            "/categories",
            {
                "budget_group_id": group["id"],
                "name": "Groceries",
                "planned_cents": 50_000,
            },
            token=token,
            expect_status=201,
        )
        self.post(
            "/expected-bills",
            {
                "budget_month_id": budget_month["id"],
                "name": "Water",
                "amount_cents": 20_000,
                "due_on": "2026-06-24",
            },
            token=token,
            expect_status=201,
        )
        self.post(
            "/paydays",
            {
                "household_id": household_id,
                "payday_date": "2026-06-28",
            },
            token=token,
            expect_status=201,
        )
        account_id = ApiHandler.repository.add_cash_account(
            budget_month_id=budget_month["id"],
            name="Main Checking",
            account_type="checking",
            balance_cents=100_000,
        )
        transaction_row_id = ApiHandler.repository.upsert_plaid_transaction(
            cash_account_id=account_id,
            plaid_transaction_id=transaction_id,
            amount_cents=-2_500,
            occurred_on=date(2026, 6, 21),
            name="Fresh Market",
            merchant_name="Fresh Market",
        ).transaction_id
        notification_id = ApiHandler.repository.create_notification_event(
            household_id=household_id,
            budget_month_id=budget_month["id"],
            event_type="manual_test",
            actor_user_id=user_id,
            affected_entity_type="transaction",
            affected_entity_id=transaction_row_id,
            title="Manual test",
            message="Manual test notification",
        )
        return {
            "household_id": household_id,
            "user_id": user_id,
            "budget_month_id": budget_month["id"],
            "category_id": category["id"],
            "account_id": account_id,
            "transaction_id": transaction_row_id,
            "notification_id": notification_id,
        }

    def login(self, username: str, password: str) -> dict[str, object]:
        return self.post(
            "/auth/login",
            {
                "username": username,
                "password": password,
            },
        )

    def get(
        self,
        path: str,
        *,
        token: str | None = None,
        expect_status: int = 200,
    ) -> dict[str, object]:
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


class ApiFakePlaidClient:
    def create_link_token(self, household_id: int) -> PlaidLinkToken:
        return PlaidLinkToken(
            link_token="link-token-api-test",
            expiration="2026-06-21T12:00:00Z",
            request_id=f"request-household-{household_id}",
        )

    def exchange_public_token(self, public_token: str) -> PlaidPublicTokenExchange:
        return PlaidPublicTokenExchange(
            access_token="access-token-api-secret",
            plaid_item_id="item-api-test",
            institution_id="ins-api-test",
            institution_name="API Test Bank",
            accounts=(
                PlaidAccountSnapshot(
                    plaid_account_id="checking-api",
                    name="API Checking",
                    account_type="checking",
                    balance_cents=80_000,
                    included_in_cash_reality=True,
                ),
            ),
        )

    def get_balances(self, access_token: str) -> tuple[PlaidAccountSnapshot, ...]:
        return ()

    def sync_transactions(self, access_token: str, cursor: str | None) -> PlaidTransactionSync:
        return PlaidTransactionSync(next_cursor=cursor)


if __name__ == "__main__":
    unittest.main()
