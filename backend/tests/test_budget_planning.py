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
from backend.app.db import BudgetRepository


class BudgetPlanningRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = BudgetRepository(Path(self.temp_dir.name) / "planning.sqlite")
        self.repository.initialize()
        self.household_id = self.repository.create_household(
            "Planning Household",
            spouses=[{"name": "Daniel", "username": "repo-daniel", "password": "password"}],
        )
        self.user_id = self._user_id(self.household_id)
        self.budget_month_id = self.repository.create_budget_month(
            household_id=self.household_id,
            month="2026-06",
            included_account_balance_cents=120_000,
        )
        self.repository.add_payday(
            household_id=self.household_id,
            payday_date=date(2026, 6, 28),
            actor_user_id=self.user_id,
        )
        self.group_id = self.repository.add_budget_group(
            budget_month_id=self.budget_month_id,
            name="Food",
            actor_user_id=self.user_id,
        )
        self.category_id = self.repository.add_category(
            budget_group_id=self.group_id,
            name="Groceries",
            planned_cents=50_000,
            actor_user_id=self.user_id,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_planned_income_can_be_added_edited_and_removed(self) -> None:
        income_id = self.repository.add_income(
            budget_month_id=self.budget_month_id,
            name="Main paycheck",
            kind="main",
            planned_cents=300_000,
            actor_user_id=self.user_id,
        )

        self.repository.update_income(
            income_id=income_id,
            name="Updated paycheck",
            planned_cents=325_000,
            actor_user_id=self.user_id,
        )
        detail = self.repository.get_budget_detail(self.budget_month_id, today=date(2026, 6, 21))
        self.assertEqual(detail["income"][0]["name"], "Updated paycheck")
        self.assertEqual(detail["planned_income_total_cents"], 325_000)

        self.repository.remove_income(income_id=income_id, actor_user_id=self.user_id)
        detail = self.repository.get_budget_detail(self.budget_month_id, today=date(2026, 6, 21))
        self.assertEqual(detail["income"], [])

    def test_category_can_be_created_and_funded_and_remaining_updates(self) -> None:
        category_id = self.repository.add_category(
            budget_group_id=self.group_id,
            name="Restaurants",
            planned_cents=15_000,
            actor_user_id=self.user_id,
        )
        before = self.repository.get_summary(self.budget_month_id, today=date(2026, 6, 21))

        self.repository.update_category(
            category_id=category_id,
            planned_cents=25_000,
            actor_user_id=self.user_id,
        )
        after = self.repository.get_summary(self.budget_month_id, today=date(2026, 6, 21))

        before_restaurants = [item for item in before.categories if item.id == category_id][0]
        after_restaurants = [item for item in after.categories if item.id == category_id][0]
        self.assertEqual(before_restaurants.remaining_cents, 15_000)
        self.assertEqual(after_restaurants.remaining_cents, 25_000)
        self.assertEqual(after.planned_cents - before.planned_cents, 10_000)

    def test_category_archive_preserves_history_but_blocks_new_use(self) -> None:
        account_id = self.repository.add_cash_account(
            budget_month_id=self.budget_month_id,
            name="Main Checking",
            account_type="checking",
            balance_cents=120_000,
        )
        transaction_id = self.repository.upsert_plaid_transaction(
            cash_account_id=account_id,
            plaid_transaction_id="archive-history",
            amount_cents=-3_500,
            occurred_on=date(2026, 6, 21),
            name="Fresh Market",
            merchant_name="Fresh Market",
        ).transaction_id
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.category_id,
            actor_user_id=self.user_id,
        )

        self.repository.update_category(
            category_id=self.category_id,
            archived=True,
            actor_user_id=self.user_id,
        )
        detail = self.repository.get_transaction_detail(transaction_id)

        self.assertEqual(detail.assignments[0].category_id, self.category_id)
        with self.assertRaisesRegex(ValueError, "active"):
            self.repository.assign_transaction_category(
                transaction_id=transaction_id,
                category_id=self.category_id,
                actor_user_id=self.user_id,
            )
        with self.assertRaisesRegex(ValueError, "archived category"):
            self.repository.safe_to_spend(
                budget_month_id=self.budget_month_id,
                category_id=self.category_id,
                purchase_amount_cents=1_000,
                today=date(2026, 6, 21),
            )
        with self.assertRaisesRegex(ValueError, "archived category"):
            self.repository.record_spending(
                category_id=self.category_id,
                amount_cents=1_000,
                occurred_on=date(2026, 6, 21),
            )

    def test_category_cannot_move_to_different_budget_month(self) -> None:
        next_budget_month_id = self.repository.create_budget_month(
            household_id=self.household_id,
            month="2026-07",
        )
        next_group_id = self.repository.add_budget_group(
            budget_month_id=next_budget_month_id,
            name="Food",
            actor_user_id=self.user_id,
        )

        with self.assertRaisesRegex(ValueError, "same budget month"):
            self.repository.update_category(
                category_id=self.category_id,
                budget_group_id=next_group_id,
                actor_user_id=self.user_id,
            )

    def test_expected_bill_changes_affect_safe_to_spend_cash_reality(self) -> None:
        bill_id = self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Utilities",
            amount_cents=20_000,
            due_on=date(2026, 6, 24),
            actor_user_id=self.user_id,
        )
        before = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=5_000,
            today=date(2026, 6, 21),
        )

        self.repository.update_expected_bill(
            bill_id=bill_id,
            amount_cents=45_000,
            actor_user_id=self.user_id,
        )
        after = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.category_id,
            purchase_amount_cents=5_000,
            today=date(2026, 6, 21),
        )

        self.assertEqual(before.bills_before_payday_cents, 20_000)
        self.assertEqual(after.bills_before_payday_cents, 45_000)
        self.assertEqual(before.cash_after_purchase_and_bills_cents - after.cash_after_purchase_and_bills_cents, 25_000)

    def test_payday_changes_affect_days_until_payday(self) -> None:
        payday_id = self.repository.add_payday(
            household_id=self.household_id,
            payday_date=date(2026, 7, 15),
            actor_user_id=self.user_id,
        )
        self.repository.update_payday(
            payday_id=payday_id,
            payday_date=date(2026, 6, 25),
            actor_user_id=self.user_id,
        )
        summary = self.repository.get_summary(self.budget_month_id, today=date(2026, 6, 24))

        self.assertEqual(summary.next_payday, date(2026, 6, 25))
        self.assertEqual(summary.days_until_payday, 1)

    def test_budget_totals_calculate_income_assigned_remaining_and_spent(self) -> None:
        self.repository.add_income(
            budget_month_id=self.budget_month_id,
            name="Paycheck",
            kind="main",
            planned_cents=300_000,
        )
        self.repository.add_income(
            budget_month_id=self.budget_month_id,
            name="Side job",
            kind="sporadic",
            planned_cents=40_000,
            received_cents=12_000,
        )
        self.repository.record_spending(
            category_id=self.category_id,
            amount_cents=8_000,
            occurred_on=date(2026, 6, 22),
        )
        detail = self.repository.get_budget_detail(self.budget_month_id, today=date(2026, 6, 21))

        self.assertEqual(detail["planned_income_total_cents"], 312_000)
        self.assertEqual(detail["assigned_total_cents"], 50_000)
        self.assertEqual(detail["remaining_to_assign_cents"], 262_000)
        self.assertEqual(detail["total_spent_cents"], 8_000)

    def test_budget_setup_changes_create_accountability_events(self) -> None:
        income_id = self.repository.add_income(
            budget_month_id=self.budget_month_id,
            name="Paycheck",
            kind="main",
            planned_cents=300_000,
            actor_user_id=self.user_id,
        )
        bill_id = self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Rent",
            amount_cents=100_000,
            due_on=date(2026, 6, 24),
            actor_user_id=self.user_id,
        )
        payday_id = self.repository.add_payday(
            household_id=self.household_id,
            payday_date=date(2026, 7, 15),
            actor_user_id=self.user_id,
        )
        self.repository.update_income(income_id=income_id, planned_cents=310_000, actor_user_id=self.user_id)
        self.repository.update_category(category_id=self.category_id, planned_cents=55_000, actor_user_id=self.user_id)
        self.repository.update_category(category_id=self.category_id, archived=True, actor_user_id=self.user_id)
        self.repository.update_expected_bill(bill_id=bill_id, amount_cents=105_000, actor_user_id=self.user_id)
        self.repository.update_payday(payday_id=payday_id, payday_date=date(2026, 7, 16), actor_user_id=self.user_id)

        month_event_types = {
            event.event_type
            for event in self.repository.list_notification_events(budget_month_id=self.budget_month_id)
        }
        household_event_types = {
            event.event_type
            for event in self.repository.list_notification_events(household_id=self.household_id)
        }

        self.assertIn("category_created", month_event_types)
        self.assertIn("category_funding_changed", month_event_types)
        self.assertIn("category_archived", month_event_types)
        self.assertIn("income_changed", month_event_types)
        self.assertIn("bill_changed", month_event_types)
        self.assertIn("payday_changed", household_event_types)

    def _user_id(self, household_id: int) -> int:
        with self.repository.connect() as connection:
            return int(
                connection.execute(
                    "SELECT id FROM users WHERE household_id = ? ORDER BY id LIMIT 1",
                    (household_id,),
                ).fetchone()["id"]
            )


class BudgetPlanningApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = build_server(Path(self.temp_dir.name) / "planning_api.sqlite", "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp_dir.cleanup()

    def test_authenticated_user_can_create_edit_select_and_copy_budget_month(self) -> None:
        household_id = ApiHandler.repository.create_household(
            "API Planning",
            spouses=[{"name": "Daniel", "username": "api-plan-daniel", "password": "password"}],
        )
        token = self.login("api-plan-daniel", "password")
        first = self.post(
            "/budget-months",
            {"household_id": household_id, "month": "2026-06", "included_account_balance_cents": 150_000},
            token,
            201,
        )
        self.patch(f"/budget-months/{first['id']}", {"low_cushion_daily_cents": 7_500}, token)
        self.post(
            "/income",
            {"budget_month_id": first["id"], "name": "Paycheck", "kind": "main", "planned_cents": 300_000},
            token,
            201,
        )
        group = self.post("/budget-groups", {"budget_month_id": first["id"], "name": "Food"}, token, 201)
        self.post(
            "/categories",
            {"budget_group_id": group["id"], "name": "Groceries", "planned_cents": 60_000},
            token,
            201,
        )
        copied = self.post(
            "/budget-months",
            {
                "household_id": household_id,
                "month": "2026-07",
                "copy_from_budget_month_id": first["id"],
            },
            token,
            201,
        )
        self.post("/paydays", {"household_id": household_id, "payday_date": "2026-07-15"}, token, 201)
        self.patch(f"/budget-months/{copied['id']}/activate", {}, token)

        months = self.get("/budget-months", token)
        copied_detail = self.get(f"/budget-months/{copied['id']}/budget-detail?today=2026-07-01", token)

        self.assertTrue(any(item["id"] == copied["id"] and item["is_active"] for item in months["budget_months"]))
        self.assertEqual(copied_detail["income"][0]["name"], "Paycheck")
        self.assertEqual(copied_detail["groups"][0]["categories"][0]["name"], "Groceries")

    def test_user_cannot_access_or_edit_another_households_budget_month(self) -> None:
        first = self.seed_household("One", "budget-one", "2026-06")
        second = self.seed_household("Two", "budget-two", "2026-06")

        denied_get = self.get(
            f"/budget-months/{second['budget_month_id']}/budget-detail",
            first["token"],
            expect_status=403,
        )
        denied_patch = self.patch(
            f"/budget-months/{second['budget_month_id']}",
            {"month": "2026-07"},
            first["token"],
            expect_status=403,
        )

        self.assertIn("Budget month", denied_get["error"])
        self.assertIn("Budget month", denied_patch["error"])

    def test_budget_setup_routes_require_authentication(self) -> None:
        self.get("/budget-months", "", expect_status=401)
        self.post("/budget-months", {"household_id": 1, "month": "2026-06"}, "", expect_status=401)
        self.post("/income", {"budget_month_id": 1, "name": "Paycheck", "kind": "main"}, "", expect_status=401)
        self.post("/budget-groups", {"budget_month_id": 1, "name": "Food"}, "", expect_status=401)
        self.post("/categories", {"budget_group_id": 1, "name": "Groceries"}, "", expect_status=401)
        self.post("/expected-bills", {"budget_month_id": 1, "name": "Rent", "amount_cents": 1, "due_on": "2026-06-01"}, "", expect_status=401)
        self.post("/paydays", {"household_id": 1, "payday_date": "2026-06-15"}, "", expect_status=401)
        self.patch("/income/1", {"planned_cents": 1}, "", expect_status=401)
        self.patch("/categories/1", {"planned_cents": 1}, "", expect_status=401)
        self.patch("/expected-bills/1", {"amount_cents": 1}, "", expect_status=401)
        self.patch("/paydays/1", {"payday_date": "2026-06-15"}, "", expect_status=401)
        self.delete("/income/1", "", expect_status=401)
        self.delete("/expected-bills/1", "", expect_status=401)
        self.delete("/paydays/1", "", expect_status=401)

    def test_user_cannot_create_or_edit_another_households_budget_setup_data(self) -> None:
        first = self.seed_household("Guard One", "guard-one", "2026-06")
        second = self.seed_household("Guard Two", "guard-two", "2026-06")
        income = self.post(
            "/income",
            {"budget_month_id": second["budget_month_id"], "name": "Paycheck", "kind": "main", "planned_cents": 300_000},
            second["token"],
            201,
        )
        group = self.post("/budget-groups", {"budget_month_id": second["budget_month_id"], "name": "Food"}, second["token"], 201)
        category = self.post(
            "/categories",
            {"budget_group_id": group["id"], "name": "Groceries", "planned_cents": 50_000},
            second["token"],
            201,
        )
        bill = self.post(
            "/expected-bills",
            {"budget_month_id": second["budget_month_id"], "name": "Rent", "amount_cents": 100_000, "due_on": "2026-06-05"},
            second["token"],
            201,
        )
        payday = self.post("/paydays", {"household_id": second["household_id"], "payday_date": "2026-06-15"}, second["token"], 201)

        self.post("/budget-months", {"household_id": second["household_id"], "month": "2026-07"}, first["token"], expect_status=403)
        self.post("/income", {"budget_month_id": second["budget_month_id"], "name": "Bonus", "kind": "sporadic"}, first["token"], expect_status=403)
        self.post("/budget-groups", {"budget_month_id": second["budget_month_id"], "name": "Bills"}, first["token"], expect_status=403)
        self.post("/categories", {"budget_group_id": group["id"], "name": "Restaurants"}, first["token"], expect_status=403)
        self.post("/expected-bills", {"budget_month_id": second["budget_month_id"], "name": "Utilities", "amount_cents": 20_000, "due_on": "2026-06-10"}, first["token"], expect_status=403)
        self.post("/paydays", {"household_id": second["household_id"], "payday_date": "2026-06-30"}, first["token"], expect_status=403)
        self.patch(f"/income/{income['id']}", {"planned_cents": 325_000}, first["token"], expect_status=403)
        self.patch(f"/categories/{category['id']}", {"planned_cents": 60_000}, first["token"], expect_status=403)
        self.patch(f"/expected-bills/{bill['id']}", {"amount_cents": 110_000}, first["token"], expect_status=403)
        self.patch(f"/paydays/{payday['id']}", {"payday_date": "2026-06-20"}, first["token"], expect_status=403)
        self.delete(f"/income/{income['id']}", first["token"], expect_status=403)
        self.delete(f"/expected-bills/{bill['id']}", first["token"], expect_status=403)
        self.delete(f"/paydays/{payday['id']}", first["token"], expect_status=403)

    def test_api_responses_remain_sanitized(self) -> None:
        seeded = self.seed_household("Sanitized", "budget-safe", "2026-06")
        notification_id = ApiHandler.repository.create_notification_event(
            household_id=seeded["household_id"],
            budget_month_id=seeded["budget_month_id"],
            event_type="manual_sanitized_test",
            actor_user_id=seeded["user_id"],
            affected_entity_type="budget",
            affected_entity_id=seeded["budget_month_id"],
            title="Manual",
            message="Manual",
            metadata={"access_token_ref": "secret", "note": "no raw_provider here"},
        )

        detail = self.get(f"/budget-months/{seeded['budget_month_id']}/budget-detail", seeded["token"])
        notifications = self.get(f"/budget-months/{seeded['budget_month_id']}/notifications", seeded["token"])
        serialized = json.dumps({"detail": detail, "notifications": notifications, "notification_id": notification_id})

        self.assertNotIn("access_token_ref", serialized)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("raw_provider", serialized)

    def seed_household(self, name: str, username: str, month: str) -> dict[str, object]:
        household_id = ApiHandler.repository.create_household(
            name,
            spouses=[{"name": username, "username": username, "password": "password"}],
        )
        token = self.login(username, "password")
        with ApiHandler.repository.connect() as connection:
            user_id = int(
                connection.execute(
                    "SELECT id FROM users WHERE household_id = ? ORDER BY id LIMIT 1",
                    (household_id,),
                ).fetchone()["id"]
            )
        budget = self.post(
            "/budget-months",
            {"household_id": household_id, "month": month},
            token,
            201,
        )
        self.post("/paydays", {"household_id": household_id, "payday_date": "2026-06-28"}, token, 201)
        return {
            "household_id": household_id,
            "user_id": user_id,
            "budget_month_id": budget["id"],
            "token": token,
        }

    def login(self, username: str, password: str) -> str:
        return str(self.post("/auth/login", {"username": username, "password": password}, "", 200)["token"])

    def get(self, path: str, token: str, expect_status: int = 200) -> dict[str, object]:
        request = Request(f"{self.base_url}{path}", headers=self.auth_headers(token), method="GET")
        return self.open_json(request, expect_status)

    def post(self, path: str, payload: dict[str, object], token: str, expect_status: int = 200) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=self.auth_headers(token) | {"Content-Type": "application/json"},
            method="POST",
        )
        return self.open_json(request, expect_status)

    def patch(self, path: str, payload: dict[str, object], token: str, expect_status: int = 200) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=self.auth_headers(token) | {"Content-Type": "application/json"},
            method="PATCH",
        )
        return self.open_json(request, expect_status)

    def delete(self, path: str, token: str, expect_status: int = 200) -> dict[str, object]:
        request = Request(f"{self.base_url}{path}", headers=self.auth_headers(token), method="DELETE")
        return self.open_json(request, expect_status)

    def open_json(self, request: Request, expect_status: int) -> dict[str, object]:
        try:
            with urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8")
                self.assertEqual(expect_status, response.status)
                return json.loads(body)
        except HTTPError as error:
            body = error.read().decode("utf-8")
            self.assertEqual(expect_status, error.code)
            return json.loads(body)

    def auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"} if token else {}


if __name__ == "__main__":
    unittest.main()
