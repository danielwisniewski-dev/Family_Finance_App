"""Authenticated fund routes, using disposable data and no bank network calls."""
import io
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from backend.app.dates import household_today
from backend.app.db import BudgetRepository
from backend.app.hosted import Application


class ProvisionFundApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = BudgetRepository(Path(self.temp.name) / "synthetic.sqlite")
        self.repo.initialize()
        self.today = household_today()
        self.one = self.seed("fund-owner-one")
        self.two = self.seed("fund-owner-two")
        self.app = Application(self.repo)

    def seed(self, username):
        household = self.repo.create_household("Synthetic funds", spouses=[
            {"name": username, "username": username, "password": "synthetic-password"}])
        month = self.repo.create_budget_month(household_id=household, month=self.today.strftime("%Y-%m"))
        account = self.repo.add_cash_account(budget_month_id=month, name="Synthetic checking",
            account_type="checking", balance_cents=500000, included_in_cash_reality=True)
        self.repo.add_payday(household_id=household, payday_date=self.today + timedelta(days=7))
        token = self.repo.authenticate_local_user(login=username, password="synthetic-password")["token"]
        return {"household": household, "month": month, "account": account, "token": token}

    def request(self, method, path, payload=None, *, token=None, expected=200):
        body = json.dumps(payload or {}).encode()
        status = []
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
            "wsgi.input": io.BytesIO(body), "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/json"}
        if token:
            environ["HTTP_AUTHORIZATION"] = "Bearer " + token
        response = b"".join(self.app(environ, lambda code, headers: status.append(int(code.split()[0]))))
        decoded = json.loads(response)
        self.assertEqual([expected], status, decoded)
        return decoded

    def create(self, owner=None, name="Synthetic reserve"):
        owner = owner or self.one
        return self.request("POST", f"/budget-months/{owner['month']}/funds", {
            "name": name, "backing_account_id": owner["account"], "monthly_plan_cents": 20000,
            "annual_target_cents": 240000, "timing_note": "Later this year",
            "breakdown": [{"name": "Synthetic renewal", "annual_cents": 240000, "timing_note": "Winter"}],
        }, token=owner["token"], expected=201)

    def entry(self, key="synthetic-entry", **changes):
        return {"budget_month_id": self.one["month"], "kind": "contribution", "amount_cents": 5000,
            "occurred_on": self.today.isoformat(), "idempotency_key": key, **changes}

    def test_all_new_routes_require_authentication(self):
        for method, path in [("GET", "/budget-months/1/funds"), ("POST", "/budget-months/1/funds"),
                ("POST", "/budget-months/1/funds/setup"), ("PATCH", "/funds/1"),
                ("POST", "/funds/1/entries"), ("POST", "/funds/1/transfer")]:
            with self.subTest(path=path, method=method):
                self.request(method, path, expected=401)

    def test_cross_household_access_and_references_are_forbidden(self):
        fund = self.create(self.two)
        token = self.one["token"]
        self.request("GET", f"/budget-months/{self.two['month']}/funds", token=token, expected=403)
        # A foreign fund is indistinguishable from a nonexistent one.
        self.request("PATCH", f"/funds/{fund['id']}", {"budget_month_id": self.one["month"], "name": "No"}, token=token, expected=404)
        self.request("POST", f"/funds/{fund['id']}/entries", self.entry(), token=token, expected=404)
        mine = self.create()
        self.request("POST", f"/funds/{mine['id']}/transfer", self.entry(target_fund_id=fund["id"]), token=token, expected=404)
        self.request("POST", f"/budget-months/{self.one['month']}/funds", {
            "name": "Invalid backing", "backing_account_id": self.two["account"], "monthly_plan_cents": 10,
        }, token=token, expected=403)
        self.request("POST", f"/funds/{mine['id']}/entries", self.entry(budget_month_id=self.two["month"]), token=token, expected=403)
        self.request("POST", "/expected-bills", {"budget_month_id": self.one["month"],
            "name": "Invalid reserve link", "amount_cents": 100, "due_on": self.today.isoformat(),
            "reserve_fund_id": fund["id"]}, token=token, expected=404)

    def test_entry_requires_integer_money_and_idempotency_key(self):
        fund = self.create()
        for value in (1.5, True, None):
            self.request("POST", f"/funds/{fund['id']}/entries", self.entry(amount_cents=value), token=self.one["token"], expected=400)
        payload = self.entry()
        payload.pop("idempotency_key")
        self.request("POST", f"/funds/{fund['id']}/entries", payload, token=self.one["token"], expected=400)

    def test_create_edit_fund_entry_replay_and_safe_response(self):
        fund = self.create()
        self.assertEqual(0, fund["balance_cents"])
        updated = self.request("PATCH", f"/funds/{fund['id']}", {
            "budget_month_id": self.one["month"], "monthly_plan_cents": 25000, "timing_note": "Autumn",
        }, token=self.one["token"])
        self.assertEqual(25000, updated["monthly_plan_cents"])
        response = self.request("POST", f"/funds/{fund['id']}/entries", self.entry(), token=self.one["token"])
        replay = self.request("POST", f"/funds/{fund['id']}/entries", self.entry(), token=self.one["token"])
        funds = self.request("GET", f"/budget-months/{self.one['month']}/funds", token=self.one["token"])
        self.assertEqual(5000, funds["funds"][0]["balance_cents"])
        for forbidden in ("access_token", "token_ref", "password_hash", "session_token_hash", "plaid_account_id"):
            self.assertNotIn(forbidden, json.dumps([response, replay, funds]))

    def test_atomic_setup_replaces_plan_without_reassigning_old_spending(self):
        group = self.repo.add_budget_group(budget_month_id=self.one["month"], name="Old plan")
        category = self.repo.add_category(budget_group_id=group, name="Old provision", planned_cents=30000)
        self.repo.record_spending(category_id=category, amount_cents=1000, occurred_on=self.today)
        response = self.request("POST", f"/budget-months/{self.one['month']}/funds/setup", {
            "backing_account_id": self.one["account"], "replace_category_id": category,
            "funds": [{"name": "Synthetic A", "monthly_plan_cents": 10000},
                      {"name": "Synthetic B", "monthly_plan_cents": 20000}],
        }, token=self.one["token"], expected=201)
        self.assertEqual(2, len(response["funds"]))
        summary = self.repo.get_summary(self.one["month"], self.today)
        self.assertEqual(30000, summary.planned_cents)
        self.assertEqual(1000, sum(c.spent_cents for c in summary.categories))
        self.assertTrue(all(f["balance_cents"] == 0 for f in response["funds"]))

    def test_bill_funding_link_survives_unrelated_edit_and_can_be_cleared(self):
        fund = self.create()
        token = self.one["token"]
        bill = self.request("POST", "/expected-bills", {
            "budget_month_id": self.one["month"], "name": "Synthetic renewal",
            "amount_cents": 1000, "due_on": self.today.isoformat(),
            "reserve_fund_id": fund["id"],
        }, token=token, expected=201)
        self.request("PATCH", f"/expected-bills/{bill['id']}", {"name": "Changed name"}, token=token)
        self.assertEqual(fund["id"], self.repo._load_snapshot(self.one["month"])["expected_bills"][0].reserve_fund_id)
        self.request("PATCH", f"/expected-bills/{bill['id']}", {"reserve_fund_id": None}, token=token)
        self.assertIsNone(self.repo._load_snapshot(self.one["month"])["expected_bills"][0].reserve_fund_id)

    def test_archive_preserves_saved_money_and_blocks_new_contributions(self):
        fund = self.create()
        token = self.one["token"]
        self.request("POST", f"/funds/{fund['id']}/entries", self.entry(), token=token)
        updated = self.request("PATCH", f"/funds/{fund['id']}", {
            "budget_month_id": self.one["month"], "archived": True,
        }, token=token)
        self.assertTrue(updated["archived"])
        self.assertEqual(5000, updated["balance_cents"])
        self.request("POST", f"/funds/{fund['id']}/entries", self.entry(key="after-archive"), token=token, expected=400)
        self.assertEqual(5000, self.repo.get_summary(self.one["month"], self.today).reserved_cash_cents)


if __name__ == "__main__":
    unittest.main()
