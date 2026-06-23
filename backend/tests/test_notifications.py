from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend.app.db import BudgetRepository, notification_event_to_dict


class NotificationEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = BudgetRepository(Path(self.temp_dir.name) / "notifications.sqlite")
        self.repository.initialize()

        self.household_id = self.repository.create_household(
            "Notification Household",
            spouses=({"name": "One"}, {"name": "Two"}),
        )
        with self.repository.connect() as connection:
            users = connection.execute(
                "SELECT id FROM users WHERE household_id = ? ORDER BY id",
                (self.household_id,),
            ).fetchall()
        self.spouse_one_id = int(users[0]["id"])
        self.spouse_two_id = int(users[1]["id"])
        self.budget_month_id = self.repository.create_budget_month(
            household_id=self.household_id,
            month="2026-06",
            included_account_balance_cents=100_000,
            low_cushion_daily_cents=5_000,
        )
        self.repository.add_income(
            budget_month_id=self.budget_month_id,
            name="Paycheck",
            kind="main",
            planned_cents=300_000,
        )
        self.group_id = self.repository.add_budget_group(
            budget_month_id=self.budget_month_id,
            name="Everyday",
        )
        self.groceries_id = self.repository.add_category(
            budget_group_id=self.group_id,
            name="Groceries",
            planned_cents=50_000,
        )
        self.dining_id = self.repository.add_category(
            budget_group_id=self.group_id,
            name="Eating Out",
            planned_cents=20_000,
        )
        self.account_id = self.repository.add_cash_account(
            budget_month_id=self.budget_month_id,
            name="Main Checking",
            account_type="checking",
            balance_cents=100_000,
        )
        self.repository.add_payday(
            household_id=self.household_id,
            payday_date=date(2026, 6, 28),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def import_transaction(self, plaid_transaction_id: str = "txn-1", amount_cents: int = -2_500) -> int:
        return self.repository.upsert_plaid_transaction(
            cash_account_id=self.account_id,
            plaid_transaction_id=plaid_transaction_id,
            amount_cents=amount_cents,
            occurred_on=date(2026, 6, 21),
            name="Fresh Market",
            merchant_name="Fresh Market",
            category_hint="Shops",
        ).transaction_id

    def events(self, event_type: str | None = None, user_id: int | None = None) -> list[dict[str, object]]:
        return [
            notification_event_to_dict(event)
            for event in self.repository.list_notification_events(
                budget_month_id=self.budget_month_id,
                user_id=user_id,
                event_type=event_type,
            )
        ]

    def test_category_assignment_creates_notification_event(self) -> None:
        transaction_id = self.import_transaction()

        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )

        events = self.events("transaction_category_assigned")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["affected_entity_id"], transaction_id)
        self.assertEqual(events[0]["severity"], "info")
        self.assertIn("Fresh Market", events[0]["message"])

    def test_recategorization_creates_notification_event(self) -> None:
        transaction_id = self.import_transaction()
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )

        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.dining_id,
        )

        events = self.events("transaction_recategorized")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["affected_entity_id"], transaction_id)
        self.assertEqual(events[0]["metadata"]["previous_category_ids"], [self.groceries_id])

    def test_ignore_and_unignore_create_notification_events(self) -> None:
        transaction_id = self.import_transaction()

        self.repository.set_transaction_ignored(
            transaction_id=transaction_id,
            ignored=True,
            reason="Transfer",
        )
        self.repository.set_transaction_ignored(transaction_id=transaction_id, ignored=False)

        ignored = self.events("transaction_ignored")
        unignored = self.events("transaction_unignored")
        self.assertEqual(len(ignored), 1)
        self.assertEqual(ignored[0]["severity"], "important")
        self.assertEqual(len(unignored), 1)
        self.assertEqual(unignored[0]["severity"], "caution")

    def test_risky_safe_to_spend_results_create_notification_events(self) -> None:
        self.repository.update_cash_account(account_id=self.account_id, balance_cents=45_000)
        self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Utilities",
            amount_cents=15_000,
            due_on=date(2026, 6, 23),
        )

        self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.groceries_id,
            purchase_amount_cents=5_000,
            today=date(2026, 6, 21),
            urgency="need",
        )
        self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.dining_id,
            purchase_amount_cents=25_000,
            today=date(2026, 6, 21),
            urgency="planned_want",
        )
        self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.groceries_id,
            purchase_amount_cents=1_000,
            today=date(2026, 6, 21),
            urgency="household_discussion",
        )

        self.assertEqual(len(self.events("safe_to_spend_caution")), 1)
        self.assertEqual(len(self.events("safe_to_spend_no")), 1)
        self.assertEqual(len(self.events("safe_to_spend_discuss")), 1)

    def test_safe_safe_to_spend_result_does_not_create_notification_event(self) -> None:
        before = self.repository.unread_notification_count(
            budget_month_id=self.budget_month_id,
            user_id=self.spouse_one_id,
        )

        self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=self.groceries_id,
            purchase_amount_cents=1_000,
            today=date(2026, 6, 21),
            urgency="planned_want",
        )

        after = self.repository.unread_notification_count(
            budget_month_id=self.budget_month_id,
            user_id=self.spouse_one_id,
        )
        self.assertEqual(after, before)
        self.assertEqual(len(self.events("safe_to_spend_safe")), 0)

    def test_event_list_returns_newest_events_first(self) -> None:
        first_id = self.repository.create_notification_event(
            household_id=self.household_id,
            budget_month_id=self.budget_month_id,
            event_type="manual_test",
            actor_user_id=None,
            affected_entity_type="test",
            affected_entity_id=1,
            title="First",
            message="First event",
            severity="info",
        )
        second_id = self.repository.create_notification_event(
            household_id=self.household_id,
            budget_month_id=self.budget_month_id,
            event_type="manual_test",
            actor_user_id=None,
            affected_entity_type="test",
            affected_entity_id=2,
            title="Second",
            message="Second event",
            severity="info",
        )

        events = self.events("manual_test")
        self.assertEqual([event["id"] for event in events], [second_id, first_id])

    def test_events_can_be_marked_read_for_one_spouse(self) -> None:
        transaction_id = self.import_transaction()
        before = self.repository.unread_notification_count(
            budget_month_id=self.budget_month_id,
            user_id=self.spouse_one_id,
        )
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )
        created = self.events("transaction_category_assigned", user_id=self.spouse_one_id)[0]

        self.assertEqual(
            self.repository.unread_notification_count(
                budget_month_id=self.budget_month_id,
                user_id=self.spouse_one_id,
            ),
            before + 1,
        )
        self.repository.mark_notification_read(int(created["id"]), user_id=self.spouse_one_id)
        self.assertEqual(
            self.repository.unread_notification_count(
                budget_month_id=self.budget_month_id,
                user_id=self.spouse_one_id,
            ),
            before,
        )
        reread = self.events("transaction_category_assigned", user_id=self.spouse_one_id)[0]
        self.assertIsNotNone(reread["read_at"])
        self.assertEqual(reread["read_by_user_id"], self.spouse_one_id)

    def test_marking_read_for_one_spouse_does_not_mark_read_for_other_spouse(self) -> None:
        transaction_id = self.import_transaction()
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )
        spouse_one_event = self.events("transaction_category_assigned", user_id=self.spouse_one_id)[0]
        spouse_two_event = self.events("transaction_category_assigned", user_id=self.spouse_two_id)[0]

        self.assertIsNone(spouse_one_event["read_at"])
        self.assertIsNone(spouse_two_event["read_at"])

        self.repository.mark_notification_read(int(spouse_one_event["id"]), user_id=self.spouse_one_id)

        spouse_one_after = self.events("transaction_category_assigned", user_id=self.spouse_one_id)[0]
        spouse_two_after = self.events("transaction_category_assigned", user_id=self.spouse_two_id)[0]
        self.assertIsNotNone(spouse_one_after["read_at"])
        self.assertIsNone(spouse_two_after["read_at"])

    def test_unread_count_differs_per_spouse(self) -> None:
        transaction_id = self.import_transaction()
        spouse_one_before = self.repository.unread_notification_count(
            budget_month_id=self.budget_month_id,
            user_id=self.spouse_one_id,
        )
        spouse_two_before = self.repository.unread_notification_count(
            budget_month_id=self.budget_month_id,
            user_id=self.spouse_two_id,
        )
        self.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=self.groceries_id,
        )
        event = self.events("transaction_category_assigned", user_id=self.spouse_one_id)[0]

        self.repository.mark_notification_read(int(event["id"]), user_id=self.spouse_one_id)

        self.assertEqual(
            self.repository.unread_notification_count(
                budget_month_id=self.budget_month_id,
                user_id=self.spouse_one_id,
            ),
            spouse_one_before,
        )
        self.assertEqual(
            self.repository.unread_notification_count(
                budget_month_id=self.budget_month_id,
                user_id=self.spouse_two_id,
            ),
            spouse_two_before + 1,
        )

    def test_notification_payloads_redact_sensitive_metadata(self) -> None:
        self.repository.create_notification_event(
            household_id=self.household_id,
            budget_month_id=self.budget_month_id,
            event_type="sensitive_test",
            actor_user_id=None,
            affected_entity_type="test",
            affected_entity_id=None,
            title="Sensitive metadata test",
            message="Metadata is sanitized.",
            severity="info",
            metadata={
                "access_token": "plaid-access-token",
                "access_token_ref": "token-reference",
                "openai_api_key": "sk-test",
                "raw_provider_error": {"message": "upstream secret"},
                "safe_note": "OpenAI API key should not leak",
                "nested": {"secret": "value", "ok": "visible"},
            },
        )

        payload = json.dumps(self.events("sensitive_test"))
        self.assertNotIn("plaid-access-token", payload)
        self.assertNotIn("token-reference", payload)
        self.assertNotIn("sk-test", payload)
        self.assertNotIn("OpenAI API key", payload)
        self.assertNotIn("raw_provider_error", payload)
        self.assertNotIn("access_token", payload)
        self.assertNotIn("secret", payload)
        self.assertIn("visible", payload)


if __name__ == "__main__":
    unittest.main()
