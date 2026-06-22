from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Iterable, Literal


IncomeKind = Literal["main", "sporadic"]
Urgency = Literal["need", "planned_want", "impulse_want", "household_discussion"]
AccountType = Literal["checking", "savings"]
PlaidSyncKind = Literal["balance", "transaction", "connection"]
CategorizationSource = Literal["manual", "rule", "plaid_hint", "split"]


class WarningLevel(str, Enum):
    SAFE = "safe"
    CAUTION = "caution"
    NO = "no"
    DISCUSS_WITH_SPOUSE = "discuss_with_spouse"


@dataclass(frozen=True)
class IncomeLine:
    name: str
    kind: IncomeKind
    planned_cents: int
    received_cents: int = 0


@dataclass(frozen=True)
class CategoryLine:
    id: int
    name: str
    planned_cents: int
    spent_cents: int
    archived: bool = False

    @property
    def remaining_cents(self) -> int:
        return self.planned_cents - self.spent_cents


@dataclass(frozen=True)
class ExpectedBill:
    name: str
    amount_cents: int
    due_on: date
    paid: bool = False


@dataclass(frozen=True)
class AccountLine:
    id: int
    budget_month_id: int
    name: str
    account_type: AccountType
    balance_cents: int
    included_in_cash_reality: bool
    plaid_item_id: int | None = None
    plaid_account_id: str | None = None
    mask: str | None = None
    official_name: str | None = None
    subtype: str | None = None
    available_balance_cents: int | None = None
    current_balance_cents: int | None = None


@dataclass(frozen=True)
class PlaidItemLine:
    id: int
    household_id: int
    plaid_item_id: str
    access_token_ref: str
    institution_id: str | None
    institution_name: str | None
    sync_cursor: str | None
    status: str
    last_error_code: str | None
    last_error_message: str | None


@dataclass(frozen=True)
class TransactionLine:
    id: int
    cash_account_id: int
    plaid_transaction_id: str | None
    amount_cents: int
    occurred_on: date
    name: str
    merchant_name: str | None
    pending: bool
    category_hint: str | None
    reviewed: bool = False
    ignored: bool = False
    ignored_reason: str | None = None


@dataclass(frozen=True)
class TransactionCategoryAssignment:
    id: int
    transaction_id: int
    category_id: int
    amount_cents: int
    source: CategorizationSource
    active: bool = True


@dataclass(frozen=True)
class TransactionDetail:
    transaction: TransactionLine
    assignments: tuple[TransactionCategoryAssignment, ...]
    audit_events: tuple[dict[str, object], ...]

    @property
    def final_category_id(self) -> int | None:
        if len(self.assignments) == 1:
            return self.assignments[0].category_id
        return None

    @property
    def categorization_status(self) -> str:
        if self.transaction.ignored:
            return "ignored"
        if len(self.assignments) > 1:
            return "split"
        if len(self.assignments) == 1:
            return self.assignments[0].source
        return "uncategorized"

    @property
    def needs_review(self) -> bool:
        return not self.transaction.reviewed or (not self.transaction.ignored and not self.assignments)


@dataclass(frozen=True)
class TransactionUpsertResult:
    transaction_id: int
    created: bool


@dataclass(frozen=True)
class BudgetSummary:
    budget_month_id: int
    month: str
    income_available_cents: int
    planned_cents: int
    unassigned_cents: int
    included_account_balance_cents: int
    next_payday: date
    days_until_payday: int
    bills_before_payday_cents: int
    cash_after_bills_cents: int
    categories: tuple[CategoryLine, ...]


@dataclass(frozen=True)
class SafeToSpendResult:
    warning_level: WarningLevel
    purchase_amount_cents: int
    category_id: int
    category_name: str
    category_remaining_before_cents: int
    category_remaining_after_cents: int
    included_account_balance_cents: int
    bills_before_payday_cents: int
    cash_after_bills_before_purchase_cents: int
    cash_after_purchase_and_bills_cents: int
    next_payday: date
    days_until_payday: int
    daily_cash_cushion_cents: int
    low_cushion: bool
    budget_line_fits: bool
    required_phrase: str
    facts: tuple[str, ...]


def available_income_cents(income_lines: Iterable[IncomeLine]) -> int:
    total = 0
    for line in income_lines:
        if line.kind == "main":
            total += line.planned_cents
        elif line.kind == "sporadic":
            total += line.received_cents
        else:
            raise ValueError(f"Unsupported income kind: {line.kind}")
    return total


def summarize_budget(
    *,
    budget_month_id: int,
    month: str,
    income_lines: Iterable[IncomeLine],
    categories: Iterable[CategoryLine],
    included_account_balance_cents: int,
    expected_bills: Iterable[ExpectedBill],
    paydays: Iterable[date],
    today: date,
) -> BudgetSummary:
    category_tuple = tuple(category for category in categories if not category.archived)
    planned_cents = sum(category.planned_cents for category in category_tuple)
    income_available = available_income_cents(income_lines)
    next_payday = find_next_payday(paydays, today)
    days_until_payday = max((next_payday - today).days, 0)
    bills_before_payday = sum_bills_before_payday(expected_bills, today, next_payday)
    cash_after_bills = included_account_balance_cents - bills_before_payday
    return BudgetSummary(
        budget_month_id=budget_month_id,
        month=month,
        income_available_cents=income_available,
        planned_cents=planned_cents,
        unassigned_cents=income_available - planned_cents,
        included_account_balance_cents=included_account_balance_cents,
        next_payday=next_payday,
        days_until_payday=days_until_payday,
        bills_before_payday_cents=bills_before_payday,
        cash_after_bills_cents=cash_after_bills,
        categories=category_tuple,
    )


def calculate_safe_to_spend(
    *,
    category: CategoryLine,
    purchase_amount_cents: int,
    included_account_balance_cents: int,
    expected_bills: Iterable[ExpectedBill],
    paydays: Iterable[date],
    today: date,
    urgency: Urgency = "planned_want",
    low_cushion_daily_cents: int = 5_000,
) -> SafeToSpendResult:
    if purchase_amount_cents <= 0:
        raise ValueError("purchase_amount_cents must be positive")
    if category.archived:
        raise ValueError("Cannot spend from an archived category")

    next_payday = find_next_payday(paydays, today)
    days_until_payday = max((next_payday - today).days, 0)
    bills_before_payday = sum_bills_before_payday(expected_bills, today, next_payday)
    cash_after_bills_before_purchase = included_account_balance_cents - bills_before_payday
    cash_after_purchase_and_bills = cash_after_bills_before_purchase - purchase_amount_cents
    divisor_days = max(days_until_payday, 1)
    daily_cash_cushion = cash_after_purchase_and_bills // divisor_days

    category_remaining_before = category.remaining_cents
    category_remaining_after = category_remaining_before - purchase_amount_cents
    budget_line_fits = category_remaining_after >= 0
    low_cushion = daily_cash_cushion < low_cushion_daily_cents

    if not budget_line_fits or cash_after_purchase_and_bills < 0:
        warning_level = WarningLevel.NO
    elif urgency == "household_discussion":
        warning_level = WarningLevel.DISCUSS_WITH_SPOUSE
    elif low_cushion:
        warning_level = WarningLevel.DISCUSS_WITH_SPOUSE if urgency == "impulse_want" else WarningLevel.CAUTION
    else:
        warning_level = WarningLevel.SAFE

    phrase = (
        "After upcoming bills, you would have about "
        f"{format_money(cash_after_purchase_and_bills)} left for "
        f"{days_until_payday} days until payday."
    )
    facts = (
        "The purchase fits the budget line." if budget_line_fits else "The purchase does not fit the budget line.",
        f"{format_money(category_remaining_after)} would remain in {category.name}.",
        phrase,
        "The remaining cash cushion is low." if low_cushion else "The remaining cash cushion is not low.",
    )

    return SafeToSpendResult(
        warning_level=warning_level,
        purchase_amount_cents=purchase_amount_cents,
        category_id=category.id,
        category_name=category.name,
        category_remaining_before_cents=category_remaining_before,
        category_remaining_after_cents=category_remaining_after,
        included_account_balance_cents=included_account_balance_cents,
        bills_before_payday_cents=bills_before_payday,
        cash_after_bills_before_purchase_cents=cash_after_bills_before_purchase,
        cash_after_purchase_and_bills_cents=cash_after_purchase_and_bills,
        next_payday=next_payday,
        days_until_payday=days_until_payday,
        daily_cash_cushion_cents=daily_cash_cushion,
        low_cushion=low_cushion,
        budget_line_fits=budget_line_fits,
        required_phrase=phrase,
        facts=facts,
    )


def find_next_payday(paydays: Iterable[date], today: date) -> date:
    future_paydays = sorted(payday for payday in paydays if payday >= today)
    if not future_paydays:
        raise ValueError("No upcoming payday configured")
    return future_paydays[0]


def sum_bills_before_payday(expected_bills: Iterable[ExpectedBill], today: date, next_payday: date) -> int:
    return sum(
        bill.amount_cents
        for bill in expected_bills
        if not bill.paid and today <= bill.due_on < next_payday
    )


def format_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents_abs = abs(cents)
    dollars, remainder = divmod(cents_abs, 100)
    return f"{sign}${dollars:,}.{remainder:02d}"


def cents_from_decimal_string(value: str) -> int:
    stripped = value.strip().replace(",", "")
    if not stripped:
        raise ValueError("Money value cannot be blank")
    if stripped.startswith("$"):
        stripped = stripped[1:]
    sign = -1 if stripped.startswith("-") else 1
    if stripped[0] in "+-":
        stripped = stripped[1:]
    parts = stripped.split(".")
    if len(parts) > 2:
        raise ValueError(f"Invalid money value: {value}")
    dollars = int(parts[0] or "0")
    cents = int((parts[1] if len(parts) == 2 else "0").ljust(2, "0")[:2])
    return sign * ((dollars * 100) + cents)
