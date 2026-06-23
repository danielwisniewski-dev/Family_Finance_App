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
from backend.app.coach import (
    CoachConfigurationError,
    CoachService,
    MockCoachProvider,
    OpenAICoachProvider,
    SafeToSpendFactPacket,
    build_coach_service_from_env,
)


class CoachApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = build_server(Path(self.temp_dir.name) / "coach.sqlite", "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.auth_token: str | None = None

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp_dir.cleanup()

    def test_coach_safe_to_spend_returns_deterministic_facts_and_phrase(self) -> None:
        fixture = self.seed_budget(balance_cents=100_000, grocery_planned_cents=50_000)

        result = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 7_500,
                "today": "2026-06-21",
                "urgency": "planned_want",
                "purpose": "weekly groceries",
            },
        )

        safe_to_spend = result["safe_to_spend"]
        coach = result["coach"]
        self.assertEqual(safe_to_spend["warning_level"], "safe")
        self.assertEqual(coach["warning_level"], "safe")
        self.assertEqual(safe_to_spend["cash_after_purchase_and_bills_cents"], 72_500)
        self.assertIn(
            "After upcoming bills, you would have about $725.00 left for 7 days until payday.",
            coach["summary"],
        )
        self.assertIn(safe_to_spend["required_phrase"], coach["tradeoffs"])
        self.assertIn("This uses backend-calculated budget and cash facts only.", coach["limitations"])

    def test_coach_warning_level_matches_backend_result(self) -> None:
        fixture = self.seed_budget(balance_cents=60_000, grocery_planned_cents=50_000)

        caution = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 10_000,
                "today": "2026-06-21",
            },
        )
        no = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 60_000,
                "today": "2026-06-21",
            },
        )
        discuss = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 1_000,
                "today": "2026-06-21",
                "urgency": "household_discussion",
            },
        )

        self.assertEqual(caution["safe_to_spend"]["warning_level"], "caution")
        self.assertEqual(caution["coach"]["warning_level"], "caution")
        self.assertEqual(no["safe_to_spend"]["warning_level"], "no")
        self.assertEqual(no["coach"]["warning_level"], "no")
        self.assertEqual(discuss["safe_to_spend"]["warning_level"], "discuss_with_spouse")
        self.assertEqual(discuss["coach"]["warning_level"], "discuss")

    def test_coach_endpoints_do_not_mutate_budget_category_or_transaction_data(self) -> None:
        fixture = self.seed_budget(balance_cents=100_000, grocery_planned_cents=50_000)
        account_id = ApiHandler.repository.add_cash_account(
            budget_month_id=fixture["budget_month_id"],
            name="Main Checking",
            account_type="checking",
            balance_cents=100_000,
        )
        transaction_id = ApiHandler.repository.upsert_plaid_transaction(
            cash_account_id=account_id,
            plaid_transaction_id="coach-mutation-check",
            amount_cents=-2_500,
            occurred_on=date(2026, 6, 21),
            name="Corner Store",
            merchant_name="Corner Store",
            category_hint="Shops",
        ).transaction_id
        ApiHandler.repository.assign_transaction_category(
            transaction_id=transaction_id,
            category_id=fixture["groceries_id"],
            reviewed=True,
        )

        summary_before = self.get(f"/budget-months/{fixture['budget_month_id']}/summary?today=2026-06-21")
        transaction_before = self.get(f"/transactions/{transaction_id}")

        self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 7_500,
                "today": "2026-06-21",
            },
        )
        proposal = self.post(
            "/coach/budget-change-suggestion",
            {
                "budget_month_id": fixture["budget_month_id"],
                "from_category_id": 999_999,
                "to_category_id": fixture["groceries_id"],
                "amount_cents": 5_000,
                "today": "2026-06-21",
            },
            expect_error=True,
        )
        self.assertIn("Category", proposal["error"])
        self.post(
            "/coach/budget-change-suggestion",
            {
                "budget_month_id": fixture["budget_month_id"],
                "from_category_id": fixture["household_supplies_id"],
                "to_category_id": fixture["groceries_id"],
                "amount_cents": 5_000,
                "today": "2026-06-21",
            },
        )

        summary_after = self.get(f"/budget-months/{fixture['budget_month_id']}/summary?today=2026-06-21")
        transaction_after = self.get(f"/transactions/{transaction_id}")
        self.assertEqual(summary_before, summary_after)
        self.assertEqual(transaction_before, transaction_after)

    def test_budget_change_suggestion_returns_proposal_only(self) -> None:
        fixture = self.seed_budget(balance_cents=100_000, grocery_planned_cents=50_000)
        before = self.get(f"/budget-months/{fixture['budget_month_id']}/summary?today=2026-06-21")

        result = self.post(
            "/coach/budget-change-suggestion",
            {
                "budget_month_id": fixture["budget_month_id"],
                "from_category_id": fixture["household_supplies_id"],
                "to_category_id": fixture["groceries_id"],
                "amount_cents": 5_000,
                "today": "2026-06-21",
                "purpose": "cover grocery overage",
            },
        )

        coach = result["coach"]
        self.assertEqual(coach["warning_level"], "discuss")
        self.assertTrue(coach["requires_spouse_discussion"])
        self.assertEqual(coach["proposed_budget_change"]["status"], "draft_only")
        self.assertEqual(coach["proposed_budget_change"]["amount_cents"], 5_000)
        self.assertIn("does not apply any budget change", " ".join(coach["limitations"]))
        after = self.get(f"/budget-months/{fixture['budget_month_id']}/summary?today=2026-06-21")
        self.assertEqual(before, after)

    def test_coach_responses_do_not_expose_plaid_token_references(self) -> None:
        fixture = self.seed_budget(balance_cents=100_000, grocery_planned_cents=50_000)
        plaid_item_id = ApiHandler.repository.create_plaid_item(
            household_id=fixture["household_id"],
            plaid_item_id="plaid-item-visible-id",
            access_token_ref="dummy-token-reference-for-redaction",
        )
        ApiHandler.repository.upsert_connected_account(
            plaid_item_id=plaid_item_id,
            budget_month_id=fixture["budget_month_id"],
            plaid_account_id="plaid-account-id",
            name="Plaid Checking",
            account_type="checking",
            balance_cents=100_000,
            included_in_cash_reality=True,
        )

        safe_response = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "amount_cents": 7_500,
                "today": "2026-06-21",
            },
        )
        suggestion_response = self.post(
            "/coach/budget-change-suggestion",
            {
                "budget_month_id": fixture["budget_month_id"],
                "from_category_id": fixture["household_supplies_id"],
                "to_category_id": fixture["groceries_id"],
                "amount_cents": 5_000,
                "today": "2026-06-21",
            },
        )

        serialized = json.dumps({"safe": safe_response, "suggestion": suggestion_response})
        self.assertNotIn("access_token", serialized)
        self.assertNotIn("access_token_ref", serialized)
        self.assertNotIn("dummy-token-reference-for-redaction", serialized)
        self.assertNotIn("plaid-item-visible-id", serialized)

    def test_missing_or_invalid_inputs_return_clear_errors(self) -> None:
        fixture = self.seed_budget(balance_cents=100_000, grocery_planned_cents=50_000)

        missing_amount = self.post(
            "/coach/safe-to-spend",
            {
                "budget_month_id": fixture["budget_month_id"],
                "category_id": fixture["groceries_id"],
                "today": "2026-06-21",
            },
            expect_error=True,
        )
        invalid_amount = self.post(
            "/coach/budget-change-suggestion",
            {
                "budget_month_id": fixture["budget_month_id"],
                "to_category_id": fixture["groceries_id"],
                "amount_cents": "five dollars",
                "today": "2026-06-21",
            },
            expect_error=True,
        )

        self.assertEqual(missing_amount["error"], "amount_cents or purchase_amount_cents is required")
        self.assertEqual(invalid_amount["error"], "amount_cents must be an integer")

    def seed_budget(self, *, balance_cents: int, grocery_planned_cents: int) -> dict[str, int]:
        household_id = ApiHandler.repository.create_household(
            "Coach Household",
            spouses=[
                {
                    "name": "A",
                    "username": "coach-a",
                    "email": "coach-a@example.test",
                    "password": "coach-a-password",
                },
                {
                    "name": "B",
                    "username": "coach-b",
                    "email": "coach-b@example.test",
                    "password": "coach-b-password",
                },
            ],
        )
        self.auth_token = str(
            self.post(
                "/auth/login",
                {"username": "coach-a", "password": "coach-a-password"},
                use_auth=False,
            )["token"]
        )
        budget_month = self.post(
            "/budget-months",
            {
                "household_id": household_id,
                "month": "2026-06",
                "included_account_balance_cents": balance_cents,
            },
        )
        self.post(
            "/income",
            {
                "budget_month_id": budget_month["id"],
                "name": "Paycheck",
                "kind": "main",
                "planned_cents": 300_000,
            },
        )
        group = self.post(
            "/budget-groups",
            {
                "budget_month_id": budget_month["id"],
                "name": "Everyday",
            },
        )
        groceries = self.post(
            "/categories",
            {
                "budget_group_id": group["id"],
                "name": "Groceries",
                "planned_cents": grocery_planned_cents,
            },
        )
        household_supplies = self.post(
            "/categories",
            {
                "budget_group_id": group["id"],
                "name": "Household Supplies",
                "planned_cents": 20_000,
            },
        )
        self.post(
            "/expected-bills",
            {
                "budget_month_id": budget_month["id"],
                "name": "Water",
                "amount_cents": 20_000,
                "due_on": "2026-06-24",
            },
        )
        self.post(
            "/paydays",
            {
                "household_id": household_id,
                "payday_date": "2026-06-28",
            },
        )
        return {
            "household_id": household_id,
            "budget_month_id": budget_month["id"],
            "groceries_id": groceries["id"],
            "household_supplies_id": household_supplies["id"],
        }

    def get(self, path: str) -> dict[str, object]:
        request = Request(f"{self.base_url}{path}", headers=self.auth_headers(), method="GET")
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def post(
        self,
        path: str,
        payload: dict[str, object],
        *,
        expect_error: bool = False,
        use_auth: bool = True,
    ) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=self.auth_headers(use_auth) | {"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            result = json.loads(exc.read().decode("utf-8"))
            if not expect_error:
                raise
            return result
        if expect_error:
            self.fail(f"Expected {path} to return an error")
        return result

    def auth_headers(self, use_auth: bool = True) -> dict[str, str]:
        if not use_auth or self.auth_token is None:
            return {}
        return {"Authorization": f"Bearer {self.auth_token}"}


class OpenAICoachProviderTests(unittest.TestCase):
    def test_default_provider_remains_mock(self) -> None:
        service = build_coach_service_from_env({})

        self.assertIsInstance(service.provider, MockCoachProvider)

    def test_openai_provider_selected_when_configured(self) -> None:
        service = build_coach_service_from_env(
            {
                "COACH_PROVIDER": "openai",
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL": "test-model",
                "OPENAI_TIMEOUT_SECONDS": "3",
            }
        )

        self.assertIsInstance(service.provider, OpenAICoachProvider)
        self.assertEqual(service.provider.model, "test-model")
        self.assertEqual(service.provider.timeout_seconds, 3.0)

    def test_openai_provider_requires_api_key_when_selected(self) -> None:
        with self.assertRaisesRegex(
            CoachConfigurationError,
            "OPENAI_API_KEY is required when COACH_PROVIDER=openai",
        ):
            build_coach_service_from_env({"COACH_PROVIDER": "openai"})

    def test_openai_provider_maps_structured_response_to_coach_response(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_transport(payload: dict[str, object], api_key: str, timeout_seconds: float) -> dict[str, object]:
            captured.append(payload)
            return {"output_text": json.dumps(valid_openai_coach_payload())}

        provider = OpenAICoachProvider(api_key="test-key", model="test-model", transport=fake_transport)
        response = provider.explain_safe_to_spend(sample_safe_to_spend_facts())

        self.assertEqual(response.summary, "Safe: stay inside the grocery plan.")
        self.assertEqual(response.warning_level, "safe")
        self.assertEqual(response.proposed_budget_change, None)
        self.assertIn("json_schema", json.dumps(captured[0]))
        self.assertNotIn("test-key", json.dumps(captured[0]))

    def test_openai_provider_timeout_returns_safe_fallback(self) -> None:
        def fake_timeout(payload: dict[str, object], api_key: str, timeout_seconds: float) -> dict[str, object]:
            raise TimeoutError("network timed out with provider details")

        provider = OpenAICoachProvider(api_key="test-key", transport=fake_timeout)
        response = provider.explain_safe_to_spend(sample_safe_to_spend_facts(warning_level="caution"))

        self.assertEqual(response.warning_level, "caution")
        self.assertEqual(response.confidence, "low")
        serialized = json.dumps(response.__dict__, default=str)
        self.assertNotIn("test-key", serialized)
        self.assertNotIn("provider details", serialized)

    def test_openai_provider_malformed_response_returns_safe_fallback(self) -> None:
        def fake_malformed(payload: dict[str, object], api_key: str, timeout_seconds: float) -> dict[str, object]:
            response = valid_openai_coach_payload()
            response["requires_spouse_discussion"] = "false"
            response["warning_level"] = "maybe"
            return {"output_text": json.dumps(response)}

        provider = OpenAICoachProvider(api_key="test-key", transport=fake_malformed)
        response = provider.explain_safe_to_spend(sample_safe_to_spend_facts(warning_level="safe"))

        self.assertEqual(response.summary, "Coach explanation is temporarily unavailable.")
        self.assertEqual(response.warning_level, "safe")
        self.assertEqual(response.confidence, "low")
        serialized = json.dumps(response.__dict__, default=str)
        self.assertNotIn("test-key", serialized)
        self.assertNotIn("maybe", serialized)

    def test_openai_endpoint_does_not_mutate_data_or_call_live_network(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        captured_payloads: list[dict[str, object]] = []

        def fake_transport(payload: dict[str, object], api_key: str, timeout_seconds: float) -> dict[str, object]:
            captured_payloads.append(payload)
            return {"output_text": json.dumps(valid_openai_coach_payload())}

        server = build_server(Path(temp_dir.name) / "openai-coach.sqlite", "127.0.0.1", 0)
        ApiHandler.coach_service = CoachService(
            OpenAICoachProvider(api_key="test-key", model="test-model", transport=fake_transport)
        )
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            fixture = seed_budget_for_base_url(base_url)
            account_id = ApiHandler.repository.add_cash_account(
                budget_month_id=fixture["budget_month_id"],
                name="Main Checking",
                account_type="checking",
                balance_cents=100_000,
            )
            transaction_id = ApiHandler.repository.upsert_plaid_transaction(
                cash_account_id=account_id,
                plaid_transaction_id="openai-mutation-check",
                amount_cents=-2_500,
                occurred_on=date(2026, 6, 21),
                name="Corner Store",
                merchant_name="Corner Store",
                category_hint="Shops",
            ).transaction_id
            ApiHandler.repository.assign_transaction_category(
                transaction_id=transaction_id,
                category_id=fixture["groceries_id"],
                reviewed=True,
            )
            plaid_item_id = ApiHandler.repository.create_plaid_item(
                household_id=fixture["household_id"],
                plaid_item_id="plaid-item-visible-id",
                access_token_ref="dummy-token-reference-for-redaction",
            )
            ApiHandler.repository.upsert_connected_account(
                plaid_item_id=plaid_item_id,
                budget_month_id=fixture["budget_month_id"],
                plaid_account_id="plaid-account-id",
                name="Plaid Checking",
                account_type="checking",
                balance_cents=100_000,
                included_in_cash_reality=True,
            )

            summary_before = get_json(
                base_url,
                f"/budget-months/{fixture['budget_month_id']}/summary?today=2026-06-21",
                fixture["auth_token"],
            )
            transaction_before = get_json(base_url, f"/transactions/{transaction_id}", fixture["auth_token"])
            coach_response = post_json(
                base_url,
                "/coach/safe-to-spend",
                {
                    "budget_month_id": fixture["budget_month_id"],
                    "category_id": fixture["groceries_id"],
                    "amount_cents": 7_500,
                    "today": "2026-06-21",
                },
                fixture["auth_token"],
            )
            summary_after = get_json(
                base_url,
                f"/budget-months/{fixture['budget_month_id']}/summary?today=2026-06-21",
                fixture["auth_token"],
            )
            transaction_after = get_json(base_url, f"/transactions/{transaction_id}", fixture["auth_token"])
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            temp_dir.cleanup()

        self.assertEqual(summary_before, summary_after)
        self.assertEqual(transaction_before, transaction_after)
        self.assertEqual(coach_response["coach"]["summary"], "Safe: stay inside the grocery plan.")
        self.assertEqual(len(captured_payloads), 1)
        serialized_input = json.dumps(captured_payloads)
        serialized_output = json.dumps(coach_response)
        self.assertNotIn("access_token", serialized_input)
        self.assertNotIn("access_token_ref", serialized_input)
        self.assertNotIn("dummy-token-reference-for-redaction", serialized_input)
        self.assertNotIn("plaid-item-visible-id", serialized_input)
        self.assertNotIn("dummy-token-reference-for-redaction", serialized_output)


def sample_safe_to_spend_facts(*, warning_level: str = "safe") -> SafeToSpendFactPacket:
    return SafeToSpendFactPacket(
        amount_cents=7_500,
        category_id=1,
        category_name="Groceries",
        warning_level=warning_level,
        budget_line_fits=True,
        category_remaining_before_cents=50_000,
        category_remaining_after_cents=42_500,
        included_account_balance_cents=100_000,
        bills_before_payday_cents=20_000,
        cash_after_bills_before_purchase_cents=80_000,
        cash_after_purchase_and_bills_cents=72_500,
        days_until_payday=7,
        required_phrase="After upcoming bills, you would have about $725.00 left for 7 days until payday.",
        backend_facts=(
            "The purchase fits the budget line.",
            "$425.00 would remain in Groceries.",
            "After upcoming bills, you would have about $725.00 left for 7 days until payday.",
            "The remaining cash cushion is not low.",
        ),
        note=None,
        purpose="weekly groceries",
    )


def valid_openai_coach_payload() -> dict[str, object]:
    return {
        "summary": "Safe: stay inside the grocery plan.",
        "recommendation": "This purchase is reasonable if it is still needed.",
        "tone": "firm_practical_not_shaming",
        "warning_level": "safe",
        "facts_used": ["Backend safe-to-spend warning level was safe."],
        "tradeoffs": ["After upcoming bills, you would have about $725.00 left for 7 days until payday."],
        "suggested_actions": ["Proceed only for the stated purpose."],
        "requires_spouse_discussion": False,
        "proposed_budget_change": None,
        "confidence": "high",
        "limitations": ["Uses backend-calculated facts only."],
    }


def get_json(base_url: str, path: str, auth_token: str | None = None) -> dict[str, object]:
    request = Request(
        f"{base_url}{path}",
        headers=auth_headers(auth_token),
        method="GET",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(base_url: str, path: str, payload: dict[str, object], auth_token: str | None = None) -> dict[str, object]:
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=auth_headers(auth_token) | {"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def auth_headers(auth_token: str | None) -> dict[str, str]:
    if auth_token is None:
        return {}
    return {"Authorization": f"Bearer {auth_token}"}


def seed_budget_for_base_url(base_url: str) -> dict[str, object]:
    household_id = ApiHandler.repository.create_household(
        "OpenAI Coach Household",
        spouses=[
            {
                "name": "A",
                "username": "openai-coach-a",
                "email": "openai-coach-a@example.test",
                "password": "openai-coach-a-password",
            },
            {
                "name": "B",
                "username": "openai-coach-b",
                "email": "openai-coach-b@example.test",
                "password": "openai-coach-b-password",
            },
        ],
    )
    auth_token = str(
        post_json(
            base_url,
            "/auth/login",
            {"username": "openai-coach-a", "password": "openai-coach-a-password"},
        )["token"]
    )
    budget_month = post_json(
        base_url,
        "/budget-months",
        {
            "household_id": household_id,
            "month": "2026-06",
            "included_account_balance_cents": 100_000,
        },
        auth_token,
    )
    post_json(
        base_url,
        "/income",
        {
            "budget_month_id": budget_month["id"],
            "name": "Paycheck",
            "kind": "main",
            "planned_cents": 300_000,
        },
        auth_token,
    )
    group = post_json(
        base_url,
        "/budget-groups",
        {
            "budget_month_id": budget_month["id"],
            "name": "Everyday",
        },
        auth_token,
    )
    groceries = post_json(
        base_url,
        "/categories",
        {
            "budget_group_id": group["id"],
            "name": "Groceries",
            "planned_cents": 50_000,
        },
        auth_token,
    )
    household_supplies = post_json(
        base_url,
        "/categories",
        {
            "budget_group_id": group["id"],
            "name": "Household Supplies",
            "planned_cents": 20_000,
        },
        auth_token,
    )
    post_json(
        base_url,
        "/expected-bills",
        {
            "budget_month_id": budget_month["id"],
            "name": "Water",
            "amount_cents": 20_000,
            "due_on": "2026-06-24",
        },
        auth_token,
    )
    post_json(
        base_url,
        "/paydays",
        {
            "household_id": household_id,
            "payday_date": "2026-06-28",
        },
        auth_token,
    )
    return {
        "household_id": household_id,
        "budget_month_id": budget_month["id"],
        "groceries_id": groceries["id"],
        "household_supplies_id": household_supplies["id"],
        "auth_token": auth_token,
    }


if __name__ == "__main__":
    unittest.main()
