from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Literal


IncomeKind = Literal["main", "sporadic"]
AccountType = Literal["checking", "savings"]
PlaidSyncKind = Literal["balance", "transaction", "connection"]
CategorizationSource = Literal["manual", "rule", "plaid_hint", "split"]
NotificationSeverity = Literal["info", "caution", "important"]


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
    reserve_fund_id: int | None = None
    fund_balance_cents: int | None = None
    contributed_cents: int = 0

    @property
    def remaining_cents(self) -> int:
        if self.reserve_fund_id is not None:
            return self.fund_balance_cents or 0
        return self.planned_cents - self.spent_cents


@dataclass(frozen=True)
class ExpectedBill:
    name: str
    amount_cents: int
    due_on: date
    paid: bool = False
    reserve_fund_id: int | None = None


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
    last_balance_synced_at: str | None = None


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
    account_name: str | None = None


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
    suggested_category_id: int | None = None
    suggestion_source: str | None = None
    suggestion_reason: str | None = None
    matching_rule_id: int | None = None
    refund_category_id: int | None = None
    budget_month_id: int | None = None
    budget_month: str | None = None
    income_id: int | None = None
    income_name: str | None = None

    @property
    def final_category_id(self) -> int | None:
        if self.refund_category_id is not None:
            return self.refund_category_id
        if len(self.assignments) == 1:
            return self.assignments[0].category_id
        return None

    @property
    def categorization_status(self) -> str:
        if self.transaction.ignored:
            return "ignored"
        if self.refund_category_id is not None:
            return "refund"
        if self.income_id is not None:
            return "income"
        if len(self.assignments) > 1:
            return "split"
        if len(self.assignments) == 1:
            return self.assignments[0].source
        if self.transaction.amount_cents >= 0 and self.transaction.reviewed:
            return "reviewed_inflow"
        return "uncategorized"

    @property
    def needs_review(self) -> bool:
        return not self.transaction.reviewed or (not self.transaction.ignored and self.transaction.amount_cents < 0 and not self.assignments)


@dataclass(frozen=True)
class TransactionUpsertResult:
    transaction_id: int
    created: bool


@dataclass(frozen=True)
class MerchantRule:
    id: int
    household_id: int
    category_id: int
    merchant_match_text: str
    priority: int
    active: bool
    category_name: str
    created_at: str
    updated_at: str | None = None


@dataclass(frozen=True)
class NotificationEvent:
    id: int
    household_id: int
    budget_month_id: int | None
    event_type: str
    actor_user_id: int | None
    affected_entity_type: str
    affected_entity_id: int | None
    title: str
    message: str
    severity: NotificationSeverity
    metadata: dict[str, object]
    read_at: str | None
    read_by_user_id: int | None
    created_at: str


@dataclass(frozen=True)
class BudgetSummary:
    budget_month_id: int
    month: str
    income_available_cents: int
    planned_cents: int
    unassigned_cents: int
    included_account_balance_cents: int
    next_payday: date | None
    days_until_payday: int | None
    bills_before_payday_cents: int | None
    cash_after_bills_cents: int | None
    categories: tuple[CategoryLine, ...]
    as_of: date | None = None
    low_cushion: bool | None = None
    reserved_cash_cents: int = 0
    reserve_covered_bills_cents: int = 0
    reserve_issues: tuple[str, ...] = ()

    @property
    def forecast_available(self) -> bool:
        return self.next_payday is not None


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
    low_cushion_daily_cents: int = 5_000,
    reserved_cash_cents: int = 0,
    reserve_covered_bills_cents: int = 0,
    reserve_issues: tuple[str, ...] = (),
) -> BudgetSummary:
    category_tuple = tuple(category for category in categories if not category.archived)
    planned_cents = sum(category.planned_cents for category in category_tuple)
    income_available = available_income_cents(income_lines)
    next_payday = min((payday for payday in paydays if payday >= today), default=None)
    days_until_payday = (next_payday - today).days if next_payday is not None else None
    bills_before_payday = (
        sum_bills_before_payday(expected_bills, today, next_payday) if next_payday is not None else None
    )
    cash_after_bills = (
        included_account_balance_cents - reserved_cash_cents - bills_before_payday + reserve_covered_bills_cents if bills_before_payday is not None else None
    )
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
        reserved_cash_cents=reserved_cash_cents,
        reserve_covered_bills_cents=reserve_covered_bills_cents,
        reserve_issues=reserve_issues,
        as_of=today,
        low_cushion=(
            cash_after_bills // max(days_until_payday, 1) < low_cushion_daily_cents
            if cash_after_bills is not None and days_until_payday is not None else None
        ),
    )


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
