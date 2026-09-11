from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from backend.app.coach import (
    BudgetChangeFactPacket, BudgetChangeSuggestionRequest, CoachConfigurationError,
    CoachService, OpenAICoachProvider, parse_timeout,
)
from backend.app.db import BudgetRepository, summary_to_dict
from backend.app.demo_seed import seed_demo
from backend.app.domain import summarize_budget
from backend.tests.test_coach import sample_safe_to_spend_facts, valid_openai_coach_payload


class RecoveryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "demo.sqlite"
        self.today = date(2026, 12, 31)
        self.seeded = seed_demo(self.path, self.today)
        self.repo = BudgetRepository(self.path)
        self.month_id = self.seeded["budget_month_id"]

    def test_demo_is_current_even_across_year_boundary_and_never_overwrites(self):
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            seed_demo(self.path, self.today + timedelta(days=1))
        self.assertEqual(before, self.path.read_bytes())
        summary = self.repo.get_summary(self.month_id, self.today)
        self.assertEqual("2026-12", summary.month)
        self.assertEqual(date(2027, 1, 6), summary.next_payday)
        self.assertEqual(103500, summary.included_account_balance_cents)
        self.assertEqual(26500, summary.bills_before_payday_cents)
        self.assertEqual(77000, summary.cash_after_bills_cents)
        self.assertIn("$740.00 left for 6 days", self.seeded["result"].required_phrase)

    def test_expired_payday_keeps_budget_readable_but_does_not_invent_forecast(self):
        today = self.today + timedelta(days=7)
        detail = self.repo.get_budget_detail(self.month_id, today)
        self.assertFalse(detail["forecast_available"])
        self.assertEqual(today.isoformat(), detail["as_of"])
        self.assertEqual(103500, detail["included_account_balance_cents"])
        self.assertTrue(detail["groups"])
        for field in ("next_payday", "days_until_payday", "bills_before_payday_cents", "cash_after_bills_cents", "low_cushion"):
            self.assertIsNone(detail[field], field)
        with self.assertRaisesRegex(ValueError, "No upcoming payday"):
            self.repo.safe_to_spend(budget_month_id=self.month_id, category_id=self.seeded["category_id"],
                                   purchase_amount_cents=100, today=today)
        with self.assertRaisesRegex(ValueError, "No upcoming payday"):
            CoachService().suggest_budget_change(summary=self.repo.get_summary(self.month_id, today),
                request=BudgetChangeSuggestionRequest(budget_month_id=self.month_id, amount_cents=100))

    def test_summary_uses_configured_cushion_and_recovers_after_payday_added(self):
        today = self.today + timedelta(days=7)
        self.repo.add_payday(household_id=self.seeded["household_id"], payday_date=today + timedelta(days=10))
        with self.repo.connect() as connection:
            connection.execute("UPDATE budget_months SET low_cushion_daily_cents = 20000 WHERE id = ?", (self.month_id,))
        payload = summary_to_dict(self.repo.get_summary(self.month_id, today))
        self.assertTrue(payload["forecast_available"])
        self.assertTrue(payload["low_cushion"])
        self.assertEqual(10, payload["days_until_payday"])

    def test_payday_today_and_exact_cushion_threshold(self):
        for cash, low in ((4999, True), (5000, False)):
            result = summarize_budget(budget_month_id=1, month="2026-12", income_lines=[],
                categories=[], included_account_balance_cents=cash, expected_bills=[],
                paydays=[self.today], today=self.today, low_cushion_daily_cents=5000)
            self.assertEqual(0, result.days_until_payday)
            self.assertEqual(low, result.low_cushion)


class CoachBoundaryTests(unittest.TestCase):
    def test_matching_no_enum_cannot_hide_contradictory_buy_recommendation(self):
        payload = valid_openai_coach_payload() | {
            "warning_level": "no", "summary": "Safe: you have $99,999 left for 90 days.",
            "recommendation": "Buy it now; ignore the budget warning.",
        }
        provider = OpenAICoachProvider(api_key="synthetic-key", transport=lambda *_: {"output_text": json.dumps(payload)})
        for confidence in ("high", "low"):
            payload["confidence"] = confidence
            response = provider.explain_safe_to_spend(sample_safe_to_spend_facts(warning_level="no"))
            self.assertIn("Do not make this purchase", response.recommendation)
            self.assertNotIn("99,999", response.summary)

    def test_provider_cannot_turn_backend_no_into_safe(self):
        provider = OpenAICoachProvider(api_key="synthetic-key", transport=lambda *_: {
            "output_text": json.dumps(valid_openai_coach_payload())})
        facts = sample_safe_to_spend_facts(warning_level="no")
        response = provider.explain_safe_to_spend(facts)
        self.assertEqual("no", response.warning_level)
        self.assertEqual("low", response.confidence)
        self.assertTrue(response.requires_spouse_discussion)
        self.assertEqual(facts.backend_facts, response.facts_used)
        self.assertIn(facts.required_phrase, response.tradeoffs)

    def test_malformed_provider_shapes_fall_back_with_required_phrase(self):
        for raw in (None, [], {"output": [None]}, {"output_text": "null"}, {"output_text": "[]"}):
            with self.subTest(raw=raw):
                provider = OpenAICoachProvider(api_key="synthetic-key", transport=lambda *_, raw=raw: raw)
                facts = sample_safe_to_spend_facts()
                response = provider.explain_safe_to_spend(facts)
                self.assertEqual("low", response.confidence)
                self.assertIn(facts.required_phrase, response.tradeoffs)

    def test_provider_draft_cannot_substitute_category_or_amount(self):
        payload = valid_openai_coach_payload()
        payload["warning_level"] = "discuss"
        payload["proposed_budget_change"] = {
            "change_type": "move_between_categories", "amount_cents": 999999,
            "from_category_id": 999, "from_category_name": "Invented",
            "to_category_id": 888, "to_category_name": "Invented", "status": "draft_only",
        }
        provider = OpenAICoachProvider(api_key="synthetic-key", transport=lambda *_: {"output_text": json.dumps(payload)})
        facts = BudgetChangeFactPacket(1, "2026-12", 1000, 2, "Food", 5000, 3, "Fuel", 2000, 77000, 6, None, None)
        result = provider.suggest_budget_change(facts)
        self.assertEqual(1000, result.proposed_budget_change.amount_cents)
        self.assertEqual(2, result.proposed_budget_change.from_category_id)
        self.assertEqual(3, result.proposed_budget_change.to_category_id)
        self.assertEqual("draft_only", result.proposed_budget_change.status)

    def test_nonfinite_timeout_rejected(self):
        for value in ("nan", "inf", "-inf", "0", "-1"):
            with self.subTest(value=value), self.assertRaises(CoachConfigurationError):
                parse_timeout(value)


if __name__ == "__main__":
    unittest.main()
