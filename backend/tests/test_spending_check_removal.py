"""Retired clients cannot calculate purchases, notify spouses, or cross demo boundaries."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.demo_data import create_demo_context
from backend.app.hosted import Application


class SpendingCheckRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.context = create_demo_context(Path(self.temporary.name) / "synthetic-real.sqlite")
        self.app = Application(self.context.repository)
        self.app.plaid = self.context.plaid_service
        self.addCleanup(self.app.demo_manager.close)
        self.token = self.context.login["token"]

    def request(self, path, token=None, method="POST", payload=None, expected=200):
        data = json.dumps(payload or {}).encode()
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path,
                   "wsgi.input": io.BytesIO(data), "CONTENT_LENGTH": str(len(data)),
                   "CONTENT_TYPE": "application/json"}
        if token:
            environ["HTTP_AUTHORIZATION"] = "Bearer " + token
        statuses = []
        body = json.loads(b"".join(self.app(environ, lambda status, headers: statuses.append(int(status.split()[0])))))
        self.assertEqual(statuses, [expected], body)
        return body

    def financial_snapshot(self):
        # Ordinary authentication updates last_used_at; all money and history must stay intact.
        with self.context.repository.connect() as connection:
            return tuple(line for line in connection.iterdump()
                         if not line.startswith('INSERT INTO "auth_sessions"'))

    def test_retired_routes_return_clear_response_without_financial_writes_or_provider_calls(self):
        repository = self.context.repository
        repository.create_notification_event(household_id=self.context.household_id,
            budget_month_id=self.context.budget_month_id, event_type="safe_to_spend_caution",
            actor_user_id=None, affected_entity_id=None, affected_entity_type="category",
            title="Historical check", message="Existing history")
        before = self.financial_snapshot()
        with patch("socket.socket.connect", side_effect=AssertionError("No provider calls")):
            for path in ("/safe-to-spend", "/coach/safe-to-spend"):
                self.request(path, expected=401)
                response = self.request(path, self.token, payload={"budget_month_id": self.context.budget_month_id,
                    "category_id": 1, "purchase_amount_cents": 2500}, expected=410)
                self.assertIn("has been removed", response["message"])
                self.assertNotIn("warning_level", response)
                self.assertNotIn("required_phrase", response)
        self.assertEqual(before, self.financial_snapshot())

    def test_demo_retirement_preserves_isolation_and_normal_dashboard(self):
        started = self.request("/demo/start", self.token)
        demo_token = started["token"]
        baseline = self.financial_snapshot()
        month = started["budget_month_id"]
        with patch("socket.socket.connect", side_effect=AssertionError("No provider calls")):
            before = self.request(f"/demo/budget-months/{month}/summary", demo_token, method="GET")
            self.assertEqual(before["cash_after_bills_cents"], 142_000)
            self.assertEqual(before["reserved_cash_cents"], 181_500)
            self.assertEqual(before["days_until_payday"], 6)
            for path in ("/safe-to-spend", "/coach/safe-to-spend"):
                self.request("/demo" + path, demo_token, expected=410)
                self.request("/demo" + path, self.token, expected=401)
                self.request(path, demo_token, expected=401)
            after = self.request(f"/demo/budget-months/{month}/summary", demo_token, method="GET")
            self.assertEqual(before, after)
            diagnostics = self.request("/demo/app/diagnostics", demo_token, method="GET")
            self.assertNotIn("safe_to_spend_ready", json.dumps(diagnostics))
            self.request("/demo/exit", demo_token)
        self.assertEqual(baseline, self.financial_snapshot())


if __name__ == "__main__":
    unittest.main()
