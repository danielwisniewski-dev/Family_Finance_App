from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .domain import BudgetSummary, SafeToSpendResult, WarningLevel, format_money


CoachWarningLevel = str
OpenAITransport = Callable[[dict[str, Any], str, float], dict[str, Any]]


class CoachConfigurationError(RuntimeError):
    pass


class CoachProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProposedBudgetChange:
    change_type: str
    amount_cents: int
    from_category_id: int | None
    from_category_name: str | None
    to_category_id: int | None
    to_category_name: str | None
    status: str = "draft_only"


@dataclass(frozen=True)
class CoachResponse:
    summary: str
    recommendation: str
    tone: str
    warning_level: CoachWarningLevel
    facts_used: tuple[str, ...]
    tradeoffs: tuple[str, ...]
    suggested_actions: tuple[str, ...]
    requires_spouse_discussion: bool
    proposed_budget_change: ProposedBudgetChange | None
    confidence: str
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class SafeToSpendCoachRequest:
    amount_cents: int
    category_id: int
    note: str | None = None
    purpose: str | None = None


@dataclass(frozen=True)
class SafeToSpendFactPacket:
    amount_cents: int
    category_id: int
    category_name: str
    warning_level: CoachWarningLevel
    budget_line_fits: bool
    category_remaining_before_cents: int
    category_remaining_after_cents: int
    included_account_balance_cents: int
    bills_before_payday_cents: int
    cash_after_bills_before_purchase_cents: int
    cash_after_purchase_and_bills_cents: int
    days_until_payday: int
    required_phrase: str
    backend_facts: tuple[str, ...]
    note: str | None
    purpose: str | None


@dataclass(frozen=True)
class BudgetChangeSuggestionRequest:
    budget_month_id: int
    amount_cents: int
    to_category_id: int | None = None
    from_category_id: int | None = None
    note: str | None = None
    purpose: str | None = None


@dataclass(frozen=True)
class BudgetChangeFactPacket:
    budget_month_id: int
    month: str
    amount_cents: int
    from_category_id: int | None
    from_category_name: str | None
    from_category_remaining_cents: int | None
    to_category_id: int | None
    to_category_name: str | None
    to_category_remaining_cents: int | None
    cash_after_bills_cents: int
    days_until_payday: int
    note: str | None
    purpose: str | None


class CoachProvider(Protocol):
    def explain_safe_to_spend(self, facts: SafeToSpendFactPacket) -> CoachResponse:
        """Return an advisory explanation from backend-calculated facts."""

    def suggest_budget_change(self, facts: BudgetChangeFactPacket) -> CoachResponse:
        """Return a draft budget change suggestion without applying it."""


class MockCoachProvider:
    """Deterministic provider used until a real AI provider is explicitly added."""

    def explain_safe_to_spend(self, facts: SafeToSpendFactPacket) -> CoachResponse:
        if facts.warning_level == "safe":
            recommendation = "This is reasonable if the purchase is still needed."
            actions = ("Proceed only for the stated purpose.",)
            discussion = False
        elif facts.warning_level == "caution":
            recommendation = "Use caution and trim optional spending elsewhere."
            actions = ("Check whether a smaller purchase would work.", "Avoid another optional purchase before payday.")
            discussion = False
        elif facts.warning_level == "no":
            recommendation = "Do not make this purchase from the current plan."
            actions = ("Wait until payday or choose a lower-cost option.", "Do not move money without approval.")
            discussion = True
        else:
            recommendation = "Discuss this with your spouse before spending."
            actions = ("Discuss the tradeoff before spending.", "Agree on any budget move before changing the plan.")
            discussion = True

        tradeoffs = (
            f"{format_money(facts.category_remaining_after_cents)} would remain in {facts.category_name}.",
            facts.required_phrase,
        )
        if not facts.budget_line_fits:
            tradeoffs += ("This purchase does not fit the selected budget line.",)

        return CoachResponse(
            summary=f"{facts.warning_level.title()}: {facts.required_phrase}",
            recommendation=recommendation,
            tone="firm_practical_not_shaming",
            warning_level=facts.warning_level,
            facts_used=facts.backend_facts,
            tradeoffs=tradeoffs,
            suggested_actions=actions,
            requires_spouse_discussion=discussion,
            proposed_budget_change=None,
            confidence="high",
            limitations=(
                "This uses backend-calculated budget and cash facts only.",
                "This is not investment, tax, legal, or professional financial advice.",
            ),
        )

    def suggest_budget_change(self, facts: BudgetChangeFactPacket) -> CoachResponse:
        from_name = facts.from_category_name
        to_name = facts.to_category_name
        proposed_change: ProposedBudgetChange | None = None
        actions: tuple[str, ...]
        discussion = True

        if facts.amount_cents <= 0:
            warning_level = "no"
            summary = "No budget change can be drafted because the amount is invalid."
            recommendation = "Use a positive amount for any proposed budget move."
            actions = ("Correct the amount and try again.",)
        elif to_name is None:
            warning_level = "no"
            summary = "No destination category was provided for a budget move."
            recommendation = "Choose the category that needs more money before drafting a change."
            actions = ("Pick a destination category.",)
        elif from_name is None:
            warning_level = "discuss"
            summary = f"Draft only: consider adding {format_money(facts.amount_cents)} to {to_name}."
            recommendation = "Discuss where the money should come from before changing the budget."
            actions = ("Discuss with your spouse.", "Wait until payday if there is no clear source.")
            proposed_change = ProposedBudgetChange(
                change_type="increase_category_requires_source",
                amount_cents=facts.amount_cents,
                from_category_id=None,
                from_category_name=None,
                to_category_id=facts.to_category_id,
                to_category_name=to_name,
            )
        elif (facts.from_category_remaining_cents or 0) < facts.amount_cents:
            warning_level = "no"
            summary = f"Draft only: {from_name} does not have enough remaining to move {format_money(facts.amount_cents)}."
            recommendation = "Do not move this money unless the source category is changed or the amount is reduced."
            actions = ("Reduce the amount.", "Choose a different source category.", "Discuss with your spouse.")
            proposed_change = ProposedBudgetChange(
                change_type="move_between_categories",
                amount_cents=facts.amount_cents,
                from_category_id=facts.from_category_id,
                from_category_name=from_name,
                to_category_id=facts.to_category_id,
                to_category_name=to_name,
            )
        else:
            warning_level = "discuss"
            summary = (
                f"Draft only: move {format_money(facts.amount_cents)} from {from_name} "
                f"to {to_name} if both of you agree."
            )
            recommendation = "This can be proposed, but it should not be applied without user approval."
            actions = ("Review the tradeoff together.", "Approve the budget change in a later workflow.")
            proposed_change = ProposedBudgetChange(
                change_type="move_between_categories",
                amount_cents=facts.amount_cents,
                from_category_id=facts.from_category_id,
                from_category_name=from_name,
                to_category_id=facts.to_category_id,
                to_category_name=to_name,
            )

        return CoachResponse(
            summary=summary,
            recommendation=recommendation,
            tone="firm_practical_not_shaming",
            warning_level=warning_level,
            facts_used=budget_change_facts_used(facts),
            tradeoffs=budget_change_tradeoffs(facts),
            suggested_actions=actions,
            requires_spouse_discussion=discussion,
            proposed_budget_change=proposed_change,
            confidence="medium",
            limitations=(
                "This is a draft suggestion only and does not apply any budget change.",
                "This uses backend-calculated budget facts only.",
                "This is not investment, tax, legal, or professional financial advice.",
            ),
        )


class OpenAICoachProvider:
    """Production-shaped OpenAI provider. Disabled unless explicitly configured."""

    api_url = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 10.0,
        transport: OpenAITransport | None = None,
    ):
        if not api_key:
            raise CoachConfigurationError("OPENAI_API_KEY is required when COACH_PROVIDER=openai")
        if timeout_seconds <= 0:
            raise CoachConfigurationError("OPENAI_TIMEOUT_SECONDS must be positive")
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._transport = transport or self._post_response

    def explain_safe_to_spend(self, facts: SafeToSpendFactPacket) -> CoachResponse:
        payload = self._build_payload(
            task="safe_to_spend",
            facts=safe_to_spend_facts_for_provider(facts),
        )
        return self._call_or_fallback(payload, fallback_warning_level=facts.warning_level)

    def suggest_budget_change(self, facts: BudgetChangeFactPacket) -> CoachResponse:
        payload = self._build_payload(
            task="budget_change_suggestion",
            facts=budget_change_facts_for_provider(facts),
        )
        return self._call_or_fallback(payload, fallback_warning_level="discuss")

    def _build_payload(self, *, task: str, facts: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are a household finance coach. Use only the provided backend facts. "
                                "Do not invent balances, bills, payday dates, transactions, or professional advice. "
                                "Do not suggest direct mutations. Keep wording short, firm, practical, and not shaming."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps({"task": task, "facts": facts}, sort_keys=True),
                        }
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "coach_response",
                    "strict": True,
                    "schema": coach_response_json_schema(),
                }
            },
        }

    def _call_or_fallback(self, payload: dict[str, Any], *, fallback_warning_level: str) -> CoachResponse:
        try:
            raw_response = self._transport(payload, self._api_key, self.timeout_seconds)
            return coach_response_from_provider_payload(extract_response_json(raw_response))
        except (CoachProviderError, HTTPError, TimeoutError, URLError, socket.timeout, OSError, ValueError, KeyError):
            return unavailable_provider_response(fallback_warning_level)

    def _post_response(self, payload: dict[str, Any], api_key: str, timeout_seconds: float) -> dict[str, Any]:
        request = Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


class CoachService:
    def __init__(self, provider: CoachProvider | None = None):
        self.provider = provider or MockCoachProvider()

    def explain_safe_to_spend(
        self,
        *,
        result: SafeToSpendResult,
        request: SafeToSpendCoachRequest,
    ) -> CoachResponse:
        facts = SafeToSpendFactPacket(
            amount_cents=request.amount_cents,
            category_id=request.category_id,
            category_name=result.category_name,
            warning_level=normalize_warning_level(result.warning_level),
            budget_line_fits=result.budget_line_fits,
            category_remaining_before_cents=result.category_remaining_before_cents,
            category_remaining_after_cents=result.category_remaining_after_cents,
            included_account_balance_cents=result.included_account_balance_cents,
            bills_before_payday_cents=result.bills_before_payday_cents,
            cash_after_bills_before_purchase_cents=result.cash_after_bills_before_purchase_cents,
            cash_after_purchase_and_bills_cents=result.cash_after_purchase_and_bills_cents,
            days_until_payday=result.days_until_payday,
            required_phrase=result.required_phrase,
            backend_facts=result.facts,
            note=request.note,
            purpose=request.purpose,
        )
        return self.provider.explain_safe_to_spend(facts)

    def suggest_budget_change(
        self,
        *,
        summary: BudgetSummary,
        request: BudgetChangeSuggestionRequest,
    ) -> CoachResponse:
        if request.amount_cents <= 0:
            raise ValueError("amount_cents must be positive")
        from_category = find_category(summary, request.from_category_id)
        to_category = find_category(summary, request.to_category_id)
        facts = BudgetChangeFactPacket(
            budget_month_id=request.budget_month_id,
            month=summary.month,
            amount_cents=request.amount_cents,
            from_category_id=request.from_category_id,
            from_category_name=from_category.name if from_category is not None else None,
            from_category_remaining_cents=from_category.remaining_cents if from_category is not None else None,
            to_category_id=request.to_category_id,
            to_category_name=to_category.name if to_category is not None else None,
            to_category_remaining_cents=to_category.remaining_cents if to_category is not None else None,
            cash_after_bills_cents=summary.cash_after_bills_cents,
            days_until_payday=summary.days_until_payday,
            note=request.note,
            purpose=request.purpose,
        )
        return self.provider.suggest_budget_change(facts)


def normalize_warning_level(warning_level: WarningLevel) -> CoachWarningLevel:
    if warning_level == WarningLevel.DISCUSS_WITH_SPOUSE:
        return "discuss"
    return warning_level.value


def find_category(summary: BudgetSummary, category_id: int | None):
    if category_id is None:
        return None
    category = next((item for item in summary.categories if item.id == category_id), None)
    if category is None:
        raise LookupError(f"Category {category_id} is not part of budget month {summary.budget_month_id}")
    return category


def budget_change_facts_used(facts: BudgetChangeFactPacket) -> tuple[str, ...]:
    items = [
        f"Budget month: {facts.month}.",
        f"Cash after upcoming bills: {format_money(facts.cash_after_bills_cents)}.",
        f"Days until payday: {facts.days_until_payday}.",
    ]
    if facts.from_category_name is not None:
        items.append(
            f"{facts.from_category_name} has {format_money(facts.from_category_remaining_cents or 0)} remaining."
        )
    if facts.to_category_name is not None:
        items.append(f"{facts.to_category_name} has {format_money(facts.to_category_remaining_cents or 0)} remaining.")
    return tuple(items)


def budget_change_tradeoffs(facts: BudgetChangeFactPacket) -> tuple[str, ...]:
    tradeoffs = [
        f"Moving {format_money(facts.amount_cents)} would reduce the source category by that amount.",
        "The backend has not changed any category funding.",
    ]
    if facts.days_until_payday > 0:
        tradeoffs.append(f"There are {facts.days_until_payday} days until payday.")
    return tuple(tradeoffs)


def coach_response_to_dict(response: CoachResponse) -> dict[str, Any]:
    payload = asdict(response)
    payload["facts_used"] = list(response.facts_used)
    payload["tradeoffs"] = list(response.tradeoffs)
    payload["suggested_actions"] = list(response.suggested_actions)
    payload["limitations"] = list(response.limitations)
    return payload


def build_coach_service_from_env(env: dict[str, str] | None = None) -> CoachService:
    values = env if env is not None else os.environ
    provider_name = values.get("COACH_PROVIDER", "mock").strip().lower()
    if provider_name in ("", "mock"):
        return CoachService(MockCoachProvider())
    if provider_name != "openai":
        raise CoachConfigurationError("COACH_PROVIDER must be 'mock' or 'openai'")

    api_key = values.get("OPENAI_API_KEY", "")
    model = values.get("OPENAI_MODEL", "gpt-4o-mini")
    timeout_seconds = parse_timeout(values.get("OPENAI_TIMEOUT_SECONDS", "10"))
    return CoachService(
        OpenAICoachProvider(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    )


def parse_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise CoachConfigurationError("OPENAI_TIMEOUT_SECONDS must be a number") from exc
    if timeout <= 0:
        raise CoachConfigurationError("OPENAI_TIMEOUT_SECONDS must be positive")
    return timeout


def safe_to_spend_facts_for_provider(facts: SafeToSpendFactPacket) -> dict[str, Any]:
    return {
        "amount_cents": facts.amount_cents,
        "category_id": facts.category_id,
        "category_name": facts.category_name,
        "warning_level": facts.warning_level,
        "budget_line_fits": facts.budget_line_fits,
        "category_remaining_before_cents": facts.category_remaining_before_cents,
        "category_remaining_after_cents": facts.category_remaining_after_cents,
        "included_account_balance_cents": facts.included_account_balance_cents,
        "bills_before_payday_cents": facts.bills_before_payday_cents,
        "cash_after_bills_before_purchase_cents": facts.cash_after_bills_before_purchase_cents,
        "cash_after_purchase_and_bills_cents": facts.cash_after_purchase_and_bills_cents,
        "days_until_payday": facts.days_until_payday,
        "required_phrase": facts.required_phrase,
        "backend_facts": list(facts.backend_facts),
        "note": facts.note,
        "purpose": facts.purpose,
    }


def budget_change_facts_for_provider(facts: BudgetChangeFactPacket) -> dict[str, Any]:
    return {
        "budget_month_id": facts.budget_month_id,
        "month": facts.month,
        "amount_cents": facts.amount_cents,
        "from_category_id": facts.from_category_id,
        "from_category_name": facts.from_category_name,
        "from_category_remaining_cents": facts.from_category_remaining_cents,
        "to_category_id": facts.to_category_id,
        "to_category_name": facts.to_category_name,
        "to_category_remaining_cents": facts.to_category_remaining_cents,
        "cash_after_bills_cents": facts.cash_after_bills_cents,
        "days_until_payday": facts.days_until_payday,
        "note": facts.note,
        "purpose": facts.purpose,
    }


def coach_response_json_schema() -> dict[str, Any]:
    proposed_budget_change_schema = {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {
            "change_type": {"type": "string"},
            "amount_cents": {"type": "integer"},
            "from_category_id": {"type": ["integer", "null"]},
            "from_category_name": {"type": ["string", "null"]},
            "to_category_id": {"type": ["integer", "null"]},
            "to_category_name": {"type": ["string", "null"]},
            "status": {"type": "string", "enum": ["draft_only"]},
        },
        "required": [
            "change_type",
            "amount_cents",
            "from_category_id",
            "from_category_name",
            "to_category_id",
            "to_category_name",
            "status",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "recommendation": {"type": "string"},
            "tone": {"type": "string", "enum": ["firm_practical_not_shaming"]},
            "warning_level": {"type": "string", "enum": ["safe", "caution", "no", "discuss"]},
            "facts_used": {"type": "array", "items": {"type": "string"}},
            "tradeoffs": {"type": "array", "items": {"type": "string"}},
            "suggested_actions": {"type": "array", "items": {"type": "string"}},
            "requires_spouse_discussion": {"type": "boolean"},
            "proposed_budget_change": proposed_budget_change_schema,
            "confidence": {"type": "string"},
            "limitations": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "summary",
            "recommendation",
            "tone",
            "warning_level",
            "facts_used",
            "tradeoffs",
            "suggested_actions",
            "requires_spouse_discussion",
            "proposed_budget_change",
            "confidence",
            "limitations",
        ],
    }


def extract_response_json(raw_response: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_response.get("output_text"), str):
        return json.loads(raw_response["output_text"])
    for item in raw_response.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                return json.loads(text)
    raise CoachProviderError("OpenAI response did not include structured output text")


def coach_response_from_provider_payload(payload: dict[str, Any]) -> CoachResponse:
    proposed_change = payload.get("proposed_budget_change")
    return CoachResponse(
        summary=str(payload["summary"]),
        recommendation=str(payload["recommendation"]),
        tone=str(payload["tone"]),
        warning_level=validate_warning_level(str(payload["warning_level"])),
        facts_used=tuple(str(item) for item in payload.get("facts_used", ())),
        tradeoffs=tuple(str(item) for item in payload.get("tradeoffs", ())),
        suggested_actions=tuple(str(item) for item in payload.get("suggested_actions", ())),
        requires_spouse_discussion=bool(payload["requires_spouse_discussion"]),
        proposed_budget_change=proposed_budget_change_from_payload(proposed_change),
        confidence=str(payload["confidence"]),
        limitations=tuple(str(item) for item in payload.get("limitations", ())),
    )


def validate_warning_level(value: str) -> str:
    if value not in {"safe", "caution", "no", "discuss"}:
        raise ValueError("warning_level must be safe, caution, no, or discuss")
    return value


def proposed_budget_change_from_payload(payload: dict[str, Any] | None) -> ProposedBudgetChange | None:
    if payload is None:
        return None
    return ProposedBudgetChange(
        change_type=str(payload["change_type"]),
        amount_cents=int(payload["amount_cents"]),
        from_category_id=payload["from_category_id"],
        from_category_name=payload["from_category_name"],
        to_category_id=payload["to_category_id"],
        to_category_name=payload["to_category_name"],
        status=str(payload.get("status", "draft_only")),
    )


def unavailable_provider_response(warning_level: str) -> CoachResponse:
    return CoachResponse(
        summary="Coach explanation is temporarily unavailable.",
        recommendation="Use the deterministic safe-to-spend result and discuss any unclear tradeoff before acting.",
        tone="firm_practical_not_shaming",
        warning_level=validate_warning_level(warning_level),
        facts_used=("Backend financial facts were calculated, but the OpenAI provider did not return a usable response.",),
        tradeoffs=("No budget changes were made.",),
        suggested_actions=("Retry later.", "Use the backend safe-to-spend result as the source of truth."),
        requires_spouse_discussion=warning_level in {"no", "discuss"},
        proposed_budget_change=None,
        confidence="low",
        limitations=(
            "OpenAI coach provider unavailable or timed out.",
            "No provider internals, API keys, or raw errors are exposed.",
        ),
    )
