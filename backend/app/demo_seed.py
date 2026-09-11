from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from .db import BudgetRepository, safe_to_spend_to_dict
from .domain import format_money


DEMO_DANIEL_PASSWORD = "daniel-local-demo-only"
DEMO_KARA_PASSWORD = "kara-local-demo-only"


def seed_demo(db_path: Path, today: date) -> dict[str, object]:
    """Create synthetic data in a new file; never replace household data."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.touch(exist_ok=False)
    repository = BudgetRepository(db_path)
    repository.initialize()

    household_id = repository.create_household(
        "Daniel and Kara Household",
        spouses=(
            {
                "name": "Daniel",
                "username": "daniel",
                "email": "daniel@example.test",
                "password": DEMO_DANIEL_PASSWORD,
            },
            {
                "name": "Kara",
                "username": "kara",
                "email": "kara@example.test",
                "password": DEMO_KARA_PASSWORD,
            },
        ),
    )
    with repository.connect() as connection:
        daniel_user_id = int(
            connection.execute(
                "SELECT id FROM users WHERE username = ?",
                ("daniel",),
            ).fetchone()["id"]
        )
    budget_month_id = repository.create_budget_month(
        household_id=household_id,
        month=today.strftime("%Y-%m"),
        included_account_balance_cents=0,
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
    checking_id = repository.add_cash_account(
        budget_month_id=budget_month_id,
        name="Main Checking",
        account_type="checking",
        balance_cents=72_500,
        included_in_cash_reality=True,
    )
    repository.add_cash_account(
        budget_month_id=budget_month_id,
        name="Bills Checking",
        account_type="checking",
        balance_cents=31_000,
        included_in_cash_reality=True,
    )
    repository.add_cash_account(
        budget_month_id=budget_month_id,
        name="Emergency Savings",
        account_type="savings",
        balance_cents=250_000,
        included_in_cash_reality=False,
    )

    food_group_id = repository.add_budget_group(budget_month_id=budget_month_id, name="Food", display_order=1)
    groceries_id = repository.add_category(
        budget_group_id=food_group_id,
        name="Groceries",
        planned_cents=55_000,
        display_order=1,
    )
    eating_out_id = repository.add_category(
        budget_group_id=food_group_id,
        name="Eating Out",
        planned_cents=16_000,
        display_order=2,
    )
    household_group_id = repository.add_budget_group(
        budget_month_id=budget_month_id,
        name="Household",
        display_order=2,
    )
    household_supplies_id = repository.add_category(
        budget_group_id=household_group_id,
        name="Household Supplies",
        planned_cents=12_000,
        display_order=1,
    )
    gas_id = repository.add_category(
        budget_group_id=household_group_id,
        name="Gas",
        planned_cents=18_000,
        display_order=2,
    )
    repository.record_spending(
        category_id=eating_out_id,
        amount_cents=9_600,
        occurred_on=today,
        note="Pizza night",
    )
    grocery_transaction_id = repository.upsert_plaid_transaction(
        cash_account_id=checking_id,
        plaid_transaction_id="demo-txn-groceries",
        amount_cents=-8_432,
        occurred_on=today,
        name="Fresh Market",
        merchant_name="Fresh Market",
        category_hint="Shops",
    ).transaction_id
    repository.assign_transaction_category(
        transaction_id=grocery_transaction_id,
        category_id=groceries_id,
        reviewed=True,
    )
    repository.upsert_plaid_transaction(
        cash_account_id=checking_id,
        plaid_transaction_id="demo-txn-uncategorized",
        amount_cents=-2_147,
        occurred_on=today,
        name="Corner Store",
        merchant_name="Corner Store",
        category_hint="Food and Drink",
    )
    gas_transaction_id = repository.upsert_plaid_transaction(
        cash_account_id=checking_id,
        plaid_transaction_id="demo-txn-gas",
        amount_cents=-4_050,
        occurred_on=today,
        name="Fuel Stop",
        merchant_name="Fuel Stop",
        category_hint="Travel",
    ).transaction_id
    repository.assign_transaction_category(
        transaction_id=gas_transaction_id,
        category_id=gas_id,
        reviewed=False,
    )
    repository.upsert_plaid_transaction(
        cash_account_id=checking_id,
        plaid_transaction_id="demo-txn-household",
        amount_cents=-1_899,
        occurred_on=today,
        name="Home Goods",
        merchant_name="Home Goods",
        category_hint="Shops",
    )
    repository.add_expected_bill(
        budget_month_id=budget_month_id,
        name="Electric",
        amount_cents=18_500,
        due_on=today + timedelta(days=3),
    )
    repository.add_expected_bill(
        budget_month_id=budget_month_id,
        name="Internet",
        amount_cents=8_000,
        due_on=today + timedelta(days=4),
    )
    repository.add_payday(household_id=household_id, payday_date=today + timedelta(days=6))

    result = repository.safe_to_spend(
        budget_month_id=budget_month_id,
        category_id=eating_out_id,
        purchase_amount_cents=3_000,
        today=today,
        urgency="planned_want",
        actor_user_id=daniel_user_id,
    )

    return {
        "budget_month_id": budget_month_id,
        "household_id": household_id,
        "category_id": eating_out_id,
        "result": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new synthetic household demo without overwriting data")
    parser.add_argument("--db", type=Path, default=Path("work/demo_family_finance.sqlite"))
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(), help="Demo date (YYYY-MM-DD); defaults to today")
    args = parser.parse_args()
    try:
        seeded = seed_demo(args.db, args.today)
    except FileExistsError:
        parser.error("Database already exists. It was not changed. Choose a new --db path.")
    result = seeded["result"]
    print("Safe-to-spend result")
    print(f"Decision: {result.warning_level.value}")
    print(f"Budget line remaining after purchase: {format_money(result.category_remaining_after_cents)}")
    print(result.required_phrase)
    print(f"Demo database: {args.db}")
    print(f"Budget month ID: {seeded['budget_month_id']}")
    print("Local-only demo credentials:")
    print(f"  Daniel: username daniel / password {DEMO_DANIEL_PASSWORD}")
    print(f"  Kara: username kara / password {DEMO_KARA_PASSWORD}")
    print("Android emulator backend URL: http://10.0.2.2:8080")
    print("Seed includes Daniel/Kara users, categories, accounts, assigned transactions, and uncategorized review items.")
    print(safe_to_spend_to_dict(result))


if __name__ == "__main__":
    main()

