from __future__ import annotations

from datetime import date
from pathlib import Path

from .db import BudgetRepository, safe_to_spend_to_dict
from .domain import format_money


def main() -> None:
    db_path = Path("work/demo_family_finance.sqlite")
    if db_path.exists():
        db_path.unlink()

    repository = BudgetRepository(db_path)
    repository.initialize()

    household_id = repository.create_household(
        "Demo Household",
        spouses=(
            {"name": "Alex", "email": "alex@example.test"},
            {"name": "Jordan", "email": "jordan@example.test"},
        ),
    )
    budget_month_id = repository.create_budget_month(
        household_id=household_id,
        month="2026-06",
        included_account_balance_cents=72_500,
        low_cushion_daily_cents=5_000,
    )
    repository.add_income(
        budget_month_id=budget_month_id,
        name="Main paycheck",
        kind="main",
        planned_cents=420_000,
    )
    repository.add_income(
        budget_month_id=budget_month_id,
        name="Yard sale",
        kind="sporadic",
        planned_cents=20_000,
        received_cents=0,
    )
    food_group_id = repository.add_budget_group(budget_month_id=budget_month_id, name="Food", display_order=1)
    eating_out_id = repository.add_category(
        budget_group_id=food_group_id,
        name="Eating Out",
        planned_cents=16_000,
    )
    repository.record_spending(
        category_id=eating_out_id,
        amount_cents=9_600,
        occurred_on=date(2026, 6, 18),
        note="Pizza night",
    )
    repository.add_expected_bill(
        budget_month_id=budget_month_id,
        name="Electric",
        amount_cents=18_500,
        due_on=date(2026, 6, 24),
    )
    repository.add_expected_bill(
        budget_month_id=budget_month_id,
        name="Internet",
        amount_cents=8_000,
        due_on=date(2026, 6, 25),
    )
    repository.add_payday(household_id=household_id, payday_date=date(2026, 6, 27))

    result = repository.safe_to_spend(
        budget_month_id=budget_month_id,
        category_id=eating_out_id,
        purchase_amount_cents=3_000,
        today=date(2026, 6, 21),
        urgency="planned_want",
    )

    print("Safe-to-spend result")
    print(f"Decision: {result.warning_level.value}")
    print(f"Budget line remaining after purchase: {format_money(result.category_remaining_after_cents)}")
    print(result.required_phrase)
    print(safe_to_spend_to_dict(result))


if __name__ == "__main__":
    main()

