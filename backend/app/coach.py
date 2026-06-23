from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from .domain import BudgetSummary, SafeToSpendResult, WarningLevel, format_money


CoachWarningLevel = str


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
    """Placeholder for a future real provider. It intentionally makes no API calls."""

    def explain_safe_to_spend(self, facts: SafeToSpendFactPacket) -> CoachResponse:
        raise NotImplementedError("Real AI provider integration is deferred beyond Milestone 5A")

    def suggest_budget_change(self, facts: BudgetChangeFactPacket) -> CoachResponse:
        raise NotImplementedError("Real AI provider integration is deferred beyond Milestone 5A")


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
