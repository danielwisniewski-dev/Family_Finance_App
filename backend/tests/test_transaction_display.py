"""Synthetic transaction ordering and quiet review-confirmation regressions."""
from datetime import date
from pathlib import Path
import tempfile
import unittest

from backend.app.db import BudgetRepository


class TransactionDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = BudgetRepository(Path(self.temp.name)/"synthetic-display.sqlite")
        self.repo.initialize()
        self.household = self.repo.create_household("Synthetic transaction household", [
            {"name": "Member A"}, {"name": "Member B"}])
        with self.repo.connect() as connection:
            self.actors = [row[0] for row in connection.execute("SELECT id FROM users WHERE household_id=? ORDER BY id", (self.household,))]
        self.month = self.repo.create_budget_month(household_id=self.household, month="2026-06")
        self.account = self.repo.add_cash_account(budget_month_id=self.month, name="Synthetic checking", account_type="checking", balance_cents=100_000)
        group = self.repo.add_budget_group(budget_month_id=self.month, name="Everyday")
        self.first_category = self.repo.add_category(budget_group_id=group, name="Food", planned_cents=20_000)
        self.second_category = self.repo.add_category(budget_group_id=group, name="Other", planned_cents=20_000)
        self.serial = 0

    def transaction(self, day, *, amount=-1_000, category=None, reviewed=False, account=None, hint=None):
        self.serial += 1
        transaction = self.repo.upsert_plaid_transaction(cash_account_id=account or self.account,
            plaid_transaction_id=f"synthetic-display-{self.serial}", amount_cents=amount,
            occurred_on=date(2026, 6, day), name=f"Synthetic transaction {self.serial}", category_hint=hint).transaction_id
        if category is not None:
            self.repo.assign_transaction_category(transaction_id=transaction, category_id=category,
                                                  reviewed=reviewed, actor_user_id=self.actors[0])
        elif reviewed:
            self.repo.mark_transaction_reviewed(transaction, actor_user_id=self.actors[0])
        return transaction

    @staticmethod
    def ids(details):
        return [detail.transaction.id for detail in details]

    def notification_ids(self, user_id):
        return [event.id for event in self.repo.list_notification_events(household_id=self.household, user_id=user_id)]

    def test_transaction_details_are_newest_first_with_deterministic_id_tiebreaks(self):
        latest_first_id = self.transaction(20)
        oldest = self.transaction(5)
        latest_second_id = self.transaction(20)
        middle = self.transaction(12)
        expected = [latest_second_id, latest_first_id, middle, oldest]
        self.assertEqual(self.ids(self.repo.list_budget_transactions(self.month)), expected)
        self.assertEqual(self.ids(self.repo.list_review_transactions(self.month, status="all")), expected)

    def test_ready_category_split_and_refund_reviews_precede_uncategorized_spending(self):
        uncategorized_newest = self.transaction(28)
        categorized_oldest = self.transaction(3, category=self.first_category)
        split = self.transaction(10)
        self.repo.split_transaction(transaction_id=split, splits=[
            {"category_id": self.first_category, "amount_cents": 600},
            {"category_id": self.second_category, "amount_cents": 400}], reviewed=False, actor_user_id=self.actors[0])
        refund = self.transaction(10, amount=500)
        self.repo.assign_transaction_refund(refund, self.first_category, self.actors[0])
        self.repo.mark_transaction_reviewed(refund, reviewed=False, actor_user_id=self.actors[0])
        categorized_same_date = self.transaction(10, category=self.second_category)
        uncategorized_older = self.transaction(19)
        expected = [categorized_same_date, refund, split, categorized_oldest, uncategorized_newest, uncategorized_older]
        self.assertEqual(self.ids(self.repo.list_transaction_review_queue(self.month)), expected)
        self.assertEqual(self.ids(self.repo.list_review_transactions(self.month, status="needs_review")), expected)
        # General history still sorts by date, independently of review readiness.
        self.assertEqual(self.ids(self.repo.list_review_transactions(self.month, status="all")),
                         [uncategorized_newest, uncategorized_older, categorized_same_date, refund, split, categorized_oldest])

    def test_suggestion_without_actual_assignment_does_not_jump_ahead_of_confirmable_spending(self):
        hint_only = self.transaction(29, hint="Food and drink")
        assigned = self.transaction(2, category=self.first_category)
        plain = self.transaction(27)
        self.assertEqual(self.ids(self.repo.list_transaction_review_queue(self.month)), [assigned, hint_only, plain])
        self.assertEqual(self.repo.get_transaction_detail(hint_only).assignments, ())

    def test_plain_inflows_and_zero_amounts_remain_in_unassigned_date_order(self):
        inflow = self.transaction(30, amount=5_000)
        zero = self.transaction(29, amount=0)
        assigned = self.transaction(1, category=self.first_category)
        unassigned_spending = self.transaction(28)
        self.assertEqual(self.ids(self.repo.list_transaction_review_queue(self.month)),
                         [assigned, inflow, zero, unassigned_spending])
        self.assertTrue(self.repo.get_transaction_detail(inflow).needs_review)
        self.assertTrue(self.repo.get_transaction_detail(zero).needs_review)

    def test_superseded_assignment_history_does_not_grant_review_priority(self):
        formerly_assigned = self.transaction(2, category=self.first_category)
        self.repo.remove_transaction_category(formerly_assigned, reviewed=False, actor_user_id=self.actors[0])
        assigned = self.transaction(1, category=self.first_category)
        plain = self.transaction(3)
        self.assertEqual(self.ids(self.repo.list_transaction_review_queue(self.month)), [assigned, plain, formerly_assigned])
        self.assertEqual(self.repo.get_transaction_detail(formerly_assigned).assignments, ())

    def test_ordering_preserves_review_ignored_and_uncategorized_filter_membership(self):
        ready = self.transaction(1, category=self.first_category)
        done = self.transaction(29, category=self.first_category, reviewed=True)
        ignored = self.transaction(28)
        self.repo.set_transaction_ignored(transaction_id=ignored, ignored=True, reason="Synthetic transfer", actor_user_id=self.actors[0])
        unassigned_but_reviewed = self.transaction(25, reviewed=True)
        unassigned = self.transaction(24)
        queue = self.ids(self.repo.list_transaction_review_queue(self.month))
        self.assertEqual(queue, [ready, unassigned_but_reviewed, unassigned])
        self.assertNotIn(done, queue)
        self.assertNotIn(ignored, queue)
        self.assertEqual(self.ids(self.repo.list_review_transactions(self.month, status="uncategorized")),
                         [unassigned_but_reviewed, unassigned])
        self.assertEqual(self.ids(self.repo.list_review_transactions(self.month, status="reviewed")),
                         [done, unassigned_but_reviewed])
        self.assertEqual(self.ids(self.repo.list_review_transactions(self.month, status="ignored")), [ignored])

    def test_date_and_account_filters_are_applied_before_review_ordering(self):
        other_account = self.repo.add_cash_account(budget_month_id=self.month, name="Other synthetic account",
                                                   account_type="checking", balance_cents=20_000)
        self.transaction(15, category=self.first_category, account=other_account)
        self.transaction(1, category=self.first_category)
        self.transaction(29)
        plain = self.transaction(20)
        assigned = self.transaction(10, category=self.first_category)
        rows = self.repo.list_review_transactions(self.month, status="needs_review",
            start_date=date(2026, 6, 10), end_date=date(2026, 6, 20), account_id=self.account)
        self.assertEqual(self.ids(rows), [assigned, plain])

    def test_marking_reviewed_changes_flag_and_audit_without_notifying_either_member(self):
        transaction = self.transaction(20, category=self.first_category)
        before_events = [self.notification_ids(actor) for actor in self.actors]
        before_counts = [self.repo.unread_notification_count(household_id=self.household, user_id=actor) for actor in self.actors]
        self.repo.mark_transaction_reviewed(transaction, reviewed=True, actor_user_id=self.actors[0])
        self.repo.mark_transaction_reviewed(transaction, reviewed=True, actor_user_id=self.actors[0])
        detail = self.repo.get_transaction_detail(transaction)
        self.assertTrue(detail.transaction.reviewed)
        self.assertFalse(detail.needs_review)
        self.assertIn("marked_reviewed", [event["event_type"] for event in detail.audit_events])
        self.assertEqual([self.notification_ids(actor) for actor in self.actors], before_events)
        self.assertEqual([self.repo.unread_notification_count(household_id=self.household, user_id=actor) for actor in self.actors], before_counts)
        with self.repo.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM notification_events WHERE event_type='transaction_marked_reviewed'").fetchone()[0], 0)

    def test_marking_unreviewed_keeps_its_notification_and_returns_item_to_queue(self):
        transaction = self.transaction(20, category=self.first_category, reviewed=True)
        before = self.notification_ids(self.actors[1])
        self.repo.mark_transaction_reviewed(transaction, reviewed=False, actor_user_id=self.actors[0])
        detail = self.repo.get_transaction_detail(transaction)
        self.assertFalse(detail.transaction.reviewed)
        self.assertTrue(detail.needs_review)
        self.assertIn(transaction, self.ids(self.repo.list_transaction_review_queue(self.month)))
        events = self.repo.list_notification_events(household_id=self.household, user_id=self.actors[1],
                                                   event_type="transaction_marked_unreviewed")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].actor_user_id, self.actors[0])
        self.assertEqual(events[0].affected_entity_id, transaction)
        self.assertEqual(len(self.notification_ids(self.actors[1])), len(before)+1)

    def test_recategorization_and_ignore_still_notify_the_other_member(self):
        transaction = self.transaction(20, category=self.first_category, reviewed=True)
        self.repo.assign_transaction_category(transaction_id=transaction, category_id=self.second_category, actor_user_id=self.actors[0])
        self.repo.set_transaction_ignored(transaction_id=transaction, ignored=True, reason="Synthetic transfer", actor_user_id=self.actors[0])
        events = self.repo.list_notification_events(household_id=self.household, user_id=self.actors[1])
        relevant = [event for event in events if event.affected_entity_type == "transaction" and event.affected_entity_id == transaction]
        self.assertEqual({event.event_type for event in relevant}, {"transaction_recategorized", "transaction_ignored"})
        self.assertTrue(all(event.actor_user_id == self.actors[0] for event in relevant))

    def test_silent_review_confirmation_still_rejects_foreign_actor_atomically(self):
        transaction = self.transaction(20, category=self.first_category)
        foreign_household = self.repo.create_household("Foreign synthetic household", [{"name": "Foreign actor"}])
        with self.repo.connect() as connection:
            foreign_actor = connection.execute("SELECT id FROM users WHERE household_id=?", (foreign_household,)).fetchone()[0]
        before = self.repo.get_transaction_detail(transaction)
        with self.assertRaises((ValueError, PermissionError)):
            self.repo.mark_transaction_reviewed(transaction, reviewed=True, actor_user_id=foreign_actor)
        after = self.repo.get_transaction_detail(transaction)
        self.assertEqual(after.transaction.reviewed, before.transaction.reviewed)
        self.assertEqual(after.audit_events, before.audit_events)


if __name__ == "__main__":
    unittest.main()
