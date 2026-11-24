import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from backend.app import migrations
from backend.app.db import BudgetRepository
from backend.app.hosted import Application
from backend.app.payday_schedules import PaydayRule


class PaydayRuleTests(unittest.TestCase):
    def test_interval_rules_keep_their_phase_and_start_on_the_chosen_payday(self):
        start = date(2026, 1, 2)
        since = date(2026, 5, 1)
        self.assertEqual(PaydayRule("every_two_weeks", start).upcoming(since, {}, 3), [
            (date(2026, 5, day), date(2026, 5, day)) for day in (8, 22)
        ] + [(date(2026, 6, 5), date(2026, 6, 5))])
        self.assertEqual(next(PaydayRule("weekly", start).dates_from(date(2025, 12, 1))), start)

    def test_monthly_returns_to_regular_day_after_a_short_month(self):
        start = date(2028, 1, 1)
        rule = PaydayRule("monthly", start, 31)
        self.assertEqual([actual for actual, _ in rule.upcoming(start, {}, 3)],
                         [date(2028, 1, 31), date(2028, 2, 29), date(2028, 3, 31)])

    def test_twice_a_month_uses_two_distinct_dates_and_spans_year_end(self):
        start = date(2026, 12, 14)
        rule = PaydayRule("twice_monthly", start, 15, 0)
        self.assertEqual([actual for actual, _ in rule.upcoming(start, {}, 4)],
                         [date(2026, 12, 15), date(2026, 12, 31), date(2027, 1, 15), date(2027, 1, 31)])
        with self.assertRaisesRegex(ValueError, "two different days"):
            PaydayRule("twice_monthly", start, 0, 28)
        rule = PaydayRule("twice_monthly", start, 15, 30)
        self.assertEqual([actual for actual, _ in rule.upcoming(date(2027, 2, 1), {}, 4)],
                         [date(2027, 2, 15), date(2027, 2, 28), date(2027, 3, 15), date(2027, 3, 30)])

    def test_payday_moved_earlier_does_not_reappear_on_its_original_date(self):
        start = date(2026, 1, 2)
        rule = PaydayRule("every_two_weeks", start)
        original, actual = date(2026, 1, 16), date(2026, 1, 15)
        self.assertEqual(rule.upcoming(actual, {original: actual}, 2), [
            (actual, original), (date(2026, 1, 30), date(2026, 1, 30)),
        ])
        self.assertEqual(rule.upcoming(original, {original: actual}, 1),
                         [(date(2026, 1, 30), date(2026, 1, 30))])


class PaydayScheduleApiTests(unittest.TestCase):
    def test_household_shares_schedules_and_forecast_but_another_household_cannot_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = BudgetRepository(Path(directory) / "households.sqlite")
            with patch.object(migrations, "MIGRATIONS", migrations.MIGRATIONS[:7]):
                repo.initialize()
            household = repo.create_household("Shared", [
                {"name": "First", "username": "first", "password": "fixture-passphrase"},
                {"name": "Second", "username": "second", "password": "fixture-passphrase"},
            ])
            other = repo.create_household("Separate", [
                {"name": "Third", "username": "third", "password": "fixture-passphrase"},
            ])
            month = repo.create_budget_month(household_id=household, month="2026-12",
                                             included_account_balance_cents=100_000)
            repo.create_budget_month(household_id=other, month="2026-12")
            one_off = repo.add_payday(household_id=household, payday_date=date(2026, 12, 29))
            repo.add_expected_bill(budget_month_id=month, name="Utilities",
                                   due_on=date(2026, 12, 23), amount_cents=10_000)
            repo.initialize()
            today = date(2026, 12, 19)
            self.assertEqual(repo.get_summary(month, today).next_payday, date(2026, 12, 29))
            self.assertEqual(repo.get_budget_detail(month, today)["paydays"][0]["id"], one_off)
            app = Application(repo)
            self.addCleanup(app.demo_manager.close)
            tokens = {username: repo.authenticate_local_user(username, "fixture-passphrase")["token"]
                      for username in ("first", "second", "third")}

            def call(username, method, path, payload=None, expected=200):
                raw = json.dumps(payload or {}).encode()
                status = []
                environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "wsgi.input": io.BytesIO(raw),
                           "CONTENT_LENGTH": str(len(raw)), "CONTENT_TYPE": "application/json",
                           "HTTP_AUTHORIZATION": "Bearer " + tokens[username]}
                with patch("backend.app.api.household_today", return_value=today):
                    response = json.loads(b"".join(app(environ, lambda code, headers: status.append(int(code.split()[0])))))
                self.assertEqual(status, [expected], response)
                return response

            path = "/payday-schedules"
            weekly = {"name": "Weekly pay", "frequency": "weekly", "starts_on": "2026-12-25"}
            semimonthly = {"name": "Other paycheck", "frequency": "twice_monthly",
                           "starts_on": "2026-12-20", "day_one": 20, "day_two": 0}
            first_id = call("first", "POST", path, weekly, expected=201)["id"]
            second_id = call("second", "POST", path, semimonthly, expected=201)["id"]
            self.assertEqual(call("first", "GET", path), call("second", "GET", path))
            self.assertEqual(call("third", "GET", path)["schedules"], [])
            self.assertEqual(repo.get_summary(month, today).next_payday, date(2026, 12, 20))
            self.assertEqual(repo.get_summary(month, today).cash_after_bills_cents, 100_000)

            target = f"{path}/{second_id}"
            move = {"original_date": "2026-12-20", "moved_to": "2026-12-26"}
            call("third", "PATCH", target, semimonthly, expected=403)
            call("third", "PATCH", target + "/move", move, expected=403)
            call("third", "DELETE", target, expected=403)
            call("first", "PATCH", target + "/move", move)
            summary = call("second", "GET", f"/budget-months/{month}/summary")
            self.assertEqual(summary["next_payday"], "2026-12-25")
            self.assertEqual(summary["cash_after_bills_cents"], 90_000)
            upcoming = call("second", "GET", path)["upcoming_paydays"]
            self.assertIn({"schedule_id": second_id, "name": "Other paycheck", "payday_date": "2026-12-26",
                           "original_date": "2026-12-20"}, upcoming)
            call("second", "PATCH", target + "/move", move | {"moved_to": None})
            self.assertEqual(repo.get_summary(month, today).next_payday, date(2026, 12, 20))
            call("second", "PATCH", target, {"name": "Monthly pay", "frequency": "monthly",
                                             "starts_on": "2026-12-20", "day_one": 0})
            self.assertEqual(repo.get_summary(month, today).next_payday, date(2026, 12, 25))
            call("second", "DELETE", f"{path}/{first_id}")
            self.assertEqual(repo.get_summary(month, today).next_payday, date(2026, 12, 29))
