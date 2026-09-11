from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from backend.app.api import MAX_REQUEST_BODY_BYTES, build_server
from backend.app.auth import hash_password, verify_password


class ApiSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = self.start_server("first")
        self.repo = self.server.RequestHandlerClass.repository
        self.household = self.repo.create_household(
            "Synthetic Household", spouses=[{"name": "User", "username": "local-user", "password": "local-password"}]
        )
        self.month = self.repo.create_budget_month(household_id=self.household, month="2026-06", included_account_balance_cents=100_000)
        self.group = self.repo.add_budget_group(budget_month_id=self.month, name="Food")
        self.category = self.repo.add_category(budget_group_id=self.group, name="Groceries", planned_cents=50_000)
        self.bill = self.repo.add_expected_bill(budget_month_id=self.month, name="Water", amount_cents=2_000, due_on=date(2026, 6, 24))
        self.repo.add_payday(household_id=self.household, payday_date=date(2026, 6, 28))
        self.account = self.repo.add_cash_account(budget_month_id=self.month, name="Checking", account_type="checking", balance_cents=100_000)
        self.transaction = self.repo.upsert_plaid_transaction(
            cash_account_id=self.account, plaid_transaction_id="synthetic-transaction", amount_cents=-1_000,
            occurred_on=date(2026, 6, 21), name="Market", merchant_name="Market",
        ).transaction_id
        _, auth, _ = self.request("POST", "/auth/login", {"username": "local-user", "password": "local-password"})
        self.token = auth["token"]

    def start_server(self, name):
        server = build_server(Path(self.temp.name) / (name + ".sqlite"), "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
        self.addCleanup(close)
        return server

    def request(self, method, path, payload=None, *, auth=False, raw=None, headers=None, server=None):
        connection = HTTPConnection("127.0.0.1", (server or self.server).server_port, timeout=5)
        request_headers = {"Content-Type": "application/json"}
        if auth:
            request_headers["Authorization"] = "Bearer " + self.token
        request_headers.update(headers or {})
        body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read()), dict(response.getheaders())
        finally:
            connection.close()

    def test_servers_do_not_share_repositories_services_or_sessions(self):
        other = self.start_server("second")
        other_repo = other.RequestHandlerClass.repository
        other_repo.create_household("Other Household", spouses=[
            {"name": "Other", "username": "local-user", "password": "other-password"},
        ])
        status, own, _ = self.request("GET", "/settings/account", auth=True)
        self.assertEqual(status, 200)
        self.assertEqual(own["household"]["name"], "Synthetic Household")
        self.assertEqual(self.request("GET", "/settings/account", auth=True, server=other)[0], 401)
        self.assertEqual(self.request("POST", "/auth/login", {
            "username": "local-user", "password": "other-password",
        }, server=other)[0], 200)
        self.assertEqual(self.request("POST", "/auth/login", {
            "username": "local-user", "password": "other-password",
        })[0], 401)
        self.assertIsNot(self.server.RequestHandlerClass.plaid_service, other.RequestHandlerClass.plaid_service)
        self.assertIsNot(self.server.RequestHandlerClass.coach_service, other.RequestHandlerClass.coach_service)

    def test_malformed_json_is_rejected_without_initializing_a_household(self):
        cases = [b"null", b"[]", b'"text"', b"1", b"{", b"\xff", b'{"a":NaN}',
                 b'{"a":Infinity}', b'{"password":"first","password":"second"}',
                 b'{"users":[null]}', b'{"users":{}}', b'{"password":42}',
                 b'{"users":[{"username":true}]}', b"[" * 1200 + b"]" * 1200]
        for raw in cases:
            with self.subTest(raw=raw[:50]):
                status, body, _ = self.request("POST", "/setup/initialize", raw=raw)
                self.assertEqual(status, 400)
                self.assertEqual(body["code"], "validation_error")
                self.assertNotIn("Traceback", body["error"])
        self.assertEqual(len(self.repo.list_budget_months(self.household)), 1)

    def test_request_framing_and_body_limits_fail_before_reading_unbounded_data(self):
        cases = [({"Content-Length": "-1"}, 400),
                 ({"Content-Length": "x"}, 400),
                 ({"Content-Length": str(MAX_REQUEST_BODY_BYTES + 1)}, 413),
                 ({"Transfer-Encoding": "chunked"}, 400),
                 ({"Content-Type": "text/plain"}, 400)]
        for headers, expected in cases:
            with self.subTest(headers=headers):
                status, body, _ = self.request("POST", "/auth/login", raw=b"{}", headers=headers)
                self.assertEqual(status, expected)
                self.assertEqual(body["status"], expected)
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.putrequest("POST", "/auth/login")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", "2")
            connection.putheader("Content-Length", "2")
            connection.endheaders(b"{}")
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            connection.close()

    def test_incomplete_request_times_out_and_server_remains_available(self):
        with patch("backend.app.api.REQUEST_TIMEOUT_SECONDS", 0.2):
            status, body, _ = self.request("POST", "/auth/login", raw=b"{", headers={"Content-Length": "2"})
        self.assertEqual(status, 408)
        self.assertEqual(body["code"], "request_timeout")
        self.assertEqual(self.request("GET", "/health")[0], 200)

    def test_money_and_identifier_fields_do_not_coerce_booleans_or_fractions(self):
        invalid_values = [True, False, 1.5, 1.0, "1.5", 2**63, -(2**63)-1, [], {}]
        for value in invalid_values:
            with self.subTest(value=value):
                self.assertEqual(self.request("POST", "/spending", {
                    "category_id": self.category, "amount_cents": value, "occurred_on": "2026-06-21",
                }, auth=True)[0], 400)
                self.assertEqual(self.request("PATCH", f"/categories/{self.category}", {
                    "planned_cents": value,
                }, auth=True)[0], 400)
                self.assertEqual(self.request("POST", "/categories", {
                    "budget_group_id": value, "name": "Invalid category",
                }, auth=True)[0], 400)
        summary = self.repo.get_summary(self.month, date(2026, 6, 21))
        self.assertEqual(summary.categories[0].planned_cents, 50_000)
        self.assertEqual(summary.categories[0].spent_cents, 0)

    def test_all_money_post_routes_reject_fractional_values(self):
        cases = [
            ("/budget-months", {"household_id": self.household, "month": "2026-07", "included_account_balance_cents": 1.5}),
            ("/income", {"budget_month_id": self.month, "name": "Pay", "kind": "main", "planned_cents": 1.5}),
            ("/categories", {"budget_group_id": self.group, "name": "New", "planned_cents": 1.5}),
            ("/expected-bills", {"budget_month_id": self.month, "name": "Bill", "amount_cents": 1.5, "due_on": "2026-06-23"}),
            ("/safe-to-spend", {"budget_month_id": self.month, "category_id": self.category, "purchase_amount_cents": 1.5}),
            ("/coach/safe-to-spend", {"budget_month_id": self.month, "category_id": self.category, "amount_cents": 1.5}),
            ("/coach/budget-change-suggestion", {"budget_month_id": self.month, "amount_cents": 1.5}),
        ]
        for path, payload in cases:
            with self.subTest(path=path):
                self.assertEqual(self.request("POST", path, payload, auth=True)[0], 400)

    def test_string_flags_do_not_mark_bills_paid_archive_categories_or_bulk_apply_rules(self):
        cases = [
            (f"/expected-bills/{self.bill}", {"paid": "false"}),
            (f"/categories/{self.category}", {"archived": "false"}),
            (f"/budget-groups/{self.group}", {"archived": "false"}),
            (f"/accounts/{self.account}", {"included_in_cash_reality": "false"}),
            (f"/transactions/{self.transaction}/ignore", {"ignored": "false"}),
            (f"/transactions/{self.transaction}/review", {"reviewed": "false"}),
        ]
        for path, payload in cases:
            with self.subTest(path=path):
                self.assertEqual(self.request("PATCH", path, payload, auth=True)[0], 400)
        status, _, _ = self.request("POST", "/merchant-category-rules", {
            "category_id": self.category, "merchant_match_text": "Market", "apply_to_existing_unreviewed": "false",
        }, auth=True)
        self.assertEqual(status, 400)
        transaction = self.repo.get_transaction_detail(self.transaction).transaction
        self.assertFalse(transaction.ignored)
        self.assertFalse(transaction.reviewed)
        self.assertEqual(self.repo.list_merchant_rules(self.household), [])
        self.assertEqual(self.repo.get_summary(self.month, date(2026, 6, 21)).bills_before_payday_cents, 2_000)

    def test_invalid_splits_preserve_original_assignment(self):
        self.repo.assign_transaction_category(transaction_id=self.transaction, category_id=self.category)
        for value in (True, 1000.5, "1000.5", 2**63):
            with self.subTest(value=value):
                status, _, _ = self.request("PATCH", f"/transactions/{self.transaction}/split", {
                    "splits": [{"category_id": self.category, "amount_cents": value}],
                }, auth=True)
                self.assertEqual(status, 400)
                detail = self.repo.get_transaction_detail(self.transaction)
                self.assertEqual(len(detail.assignments), 1)
                self.assertEqual(detail.assignments[0].amount_cents, 1_000)
                self.assertEqual(detail.assignments[0].source, "manual")

    def test_unknown_resource_suffixes_do_not_read_or_mutate_real_records(self):
        for method, path, payload in [
            ("DELETE", f"/expected-bills/{self.bill}/typo", None),
            ("PATCH", f"/categories/{self.category}/typo", {"planned_cents": 0}),
            ("GET", f"/transactions/{self.transaction}/typo", None),
            ("PATCH", f"/transactions/{self.transaction}/typo/ignore", {"ignored": True}),
        ]:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.request(method, path, payload, auth=True)[0], 404)
        self.assertFalse(self.repo.get_transaction_detail(self.transaction).transaction.ignored)
        summary = self.repo.get_summary(self.month, date(2026, 6, 21))
        self.assertEqual(summary.bills_before_payday_cents, 2_000)
        self.assertEqual(summary.categories[0].planned_cents, 50_000)

    def test_missing_fields_are_validation_errors_and_numeric_strings_remain_compatible(self):
        status, body, _ = self.request("POST", "/paydays", {"household_id": self.household}, auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "payday_date is required")
        self.assertEqual(self.request("POST", "/spending", {
            "category_id": str(self.category), "amount_cents": "100", "occurred_on": "2026-06-21",
        }, auth=True)[0], 201)

    def test_dates_use_the_documented_calendar_format(self):
        for value in ("20260621", "2026-W25-7", 20260621, "2026-02-30"):
            with self.subTest(value=value):
                self.assertEqual(self.request("POST", "/paydays", {
                    "household_id": self.household, "payday_date": value,
                }, auth=True)[0], 400)

    def test_financial_and_login_responses_cannot_be_cached(self):
        for method, path, payload in [
            ("GET", "/settings/account", None),
            ("POST", "/auth/login", {"username": "local-user", "password": "local-password"}),
        ]:
            with self.subTest(path=path):
                status, _, headers = self.request(method, path, payload, auth=True)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.request("GET", "/setup/status", headers={"Authorization": "Basic nonsense"})[0], 401)

    def test_every_private_route_requires_a_session(self):
        routes = {
            "GET": ["/settings/account", "/app/diagnostics", "/budget-months", "/merchant-category-rules",
                    "/transactions/1", "/budget-months/1/summary", "/budget-months/1/budget-detail",
                    "/budget-months/1/accounts", "/budget-months/1/transactions",
                    "/budget-months/1/transaction-review-queue", "/budget-months/1/notifications",
                    "/budget-months/1/notifications/unread-count", "/households/1/notifications",
                    "/households/1/notifications/unread-count"],
            "POST": ["/households", "/starter-budget/current-month", "/budget-months", "/income",
                     "/budget-groups", "/categories", "/spending", "/expected-bills", "/paydays",
                     "/safe-to-spend", "/coach/safe-to-spend", "/coach/budget-change-suggestion",
                     "/plaid/link-token", "/plaid/exchange-public-token", "/plaid/sync", "/merchant-category-rules"],
            "PATCH": ["/settings/display-name", "/settings/password", "/budget-months/1/activate", "/budget-months/1",
                      "/income/1", "/budget-groups/1", "/categories/1", "/expected-bills/1", "/paydays/1",
                      "/budget-months/1/account-balance", "/accounts/1", "/transactions/1/review",
                      "/transactions/1/category", "/transactions/1/split", "/transactions/1/ignore",
                      "/merchant-category-rules/1", "/notifications/1/read", "/households/1/notifications/read-all",
                      "/budget-months/1/notifications/read-all"],
            "DELETE": ["/income/1", "/expected-bills/1", "/paydays/1", "/transactions/1/split", "/merchant-category-rules/1"],
        }
        for method, paths in routes.items():
            for path in paths:
                with self.subTest(method=method, path=path):
                    status, body, _ = self.request(method, path, {} if method in ("POST", "PATCH") else None)
                    self.assertEqual(status, 401)
                    self.assertEqual(body["code"], "unauthorized")

    def test_password_change_invalidates_current_and_other_existing_sessions(self):
        _, second, _ = self.request("POST", "/auth/login", {"username": "local-user", "password": "local-password"})
        self.assertEqual(self.request("PATCH", "/settings/password", {
            "current_password": "local-password", "new_password": "changed-password",
        }, auth=True)[0], 200)
        self.assertEqual(self.request("GET", "/settings/account", auth=True)[0], 401)
        self.assertEqual(self.request("GET", "/settings/account", headers={
            "Authorization": "Bearer " + second["token"],
        })[0], 401)
        self.assertEqual(self.request("POST", "/auth/login", {
            "username": "local-user", "password": "local-password",
        })[0], 401)
        self.assertEqual(self.request("POST", "/auth/login", {
            "username": "local-user", "password": "changed-password",
        })[0], 200)

    def test_simultaneous_first_setup_creates_exactly_one_household(self):
        empty_server = self.start_server("empty")
        ready = threading.Barrier(2)

        def initialize(name):
            ready.wait(timeout=5)
            return self.request("POST", "/setup/initialize", {
                "household_name": name,
                "users": [{"name": name, "username": name, "password": "setup-password"}],
            }, server=empty_server)[0]

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(initialize, ("first", "second")))
        self.assertEqual(sorted(results), [201, 403])
        with empty_server.RequestHandlerClass.repository.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM households").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)

    def test_ambiguous_username_and_email_do_not_authenticate_either_identity(self):
        self.repo.create_local_user(household_id=self.household, name="First", username="shared@example.test",
                                    email=None, password="first-password")
        other_household = self.repo.create_household("Other Household")
        self.repo.create_local_user(household_id=other_household, name="Second", username="second",
                                    email="shared@example.test", password="second-password")
        with self.repo.connect() as connection:
            before = connection.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0]
        for password in ("first-password", "second-password"):
            with self.subTest(password=password):
                status, body, _ = self.request("POST", "/auth/login", {
                    "username": "shared@example.test", "password": password,
                })
                self.assertEqual(status, 401)
                self.assertEqual(body["error"], "Invalid credentials")
        with self.repo.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0], before)

    def test_setup_rejects_ambiguous_identifiers_atomically_but_allows_own_email_as_username(self):
        empty_server = self.start_server("empty")
        payload = {
            "household_name": "Synthetic Household",
            "users": [
                {"name": "First", "username": "shared@example.test", "password": "first-password"},
                {"name": "Second", "username": "second", "email": "SHARED@example.test", "password": "second-password"},
            ],
        }
        status, body, _ = self.request("POST", "/setup/initialize", payload, server=empty_server)
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "validation_error")
        with empty_server.RequestHandlerClass.repository.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM households").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        payload["users"] = [{"name": "First", "username": "shared@example.test", "email": "shared@example.test",
                             "password": "first-password"}]
        self.assertEqual(self.request("POST", "/setup/initialize", payload, server=empty_server)[0], 201)


class PasswordHashValidationTests(unittest.TestCase):
    def test_malformed_or_corrupt_hashes_fail_closed(self):
        salt = base64.urlsafe_b64encode(b"example-salt").decode()
        digest = base64.urlsafe_b64encode(b"x" * 32).decode()
        hashes = [None, "wrong", "other$210000$bad$bad", "pbkdf2_sha256$0$" + salt + "$" + digest,
                  "pbkdf2_sha256$-1$" + salt + "$" + digest,
                  "pbkdf2_sha256$9999999999999999999$" + salt + "$" + digest,
                  "pbkdf2_sha256$210000$!$!", "pbkdf2_sha256$210000$" + salt + "$short"]
        for value in hashes:
            with self.subTest(value=value):
                self.assertFalse(verify_password("local-password", value))
        valid = hash_password("local-password")
        self.assertTrue(verify_password("local-password", valid))
        self.assertFalse(verify_password("different-password", valid))


if __name__ == "__main__":
    unittest.main()
