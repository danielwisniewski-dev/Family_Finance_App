"""Disposable, fictional household fixtures exercising the production domain.

Keep this fixture and its feature-parity tests in step with financial/schema/UI
changes. Never copy a real household into a demo or relax readiness checks here.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .bank_data import bank_status, reconcile_bank
from .dates import household_today
from .db import BudgetRepository
from .demo_bank import DemoBankClient, DemoBankService
from .plaid import PlaidTransactionSnapshot
from .security import RuntimeSettings


@dataclass(frozen=True)
class DemoContext:
    repository: BudgetRepository
    plaid_service: DemoBankService
    login: dict
    household_id: int
    budget_month_id: int
    user_id: int


def create_demo_context(db_path: Path, today: date | None = None) -> DemoContext:
    """Create a NEW database only. The context owner handles expiry and removal."""
    today = today or household_today()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.touch(exist_ok=False)
    repository = BudgetRepository(db_path, RuntimeSettings(hosted=True, plaid_enabled=True,
        setup_code=secrets.token_urlsafe(40), encryption_key=secrets.token_urlsafe(40), session_seconds=8 * 60 * 60))
    repository.initialize()
    password = secrets.token_urlsafe(32)
    household = repository.create_household("Morgan Demo Household", spouses=(
        {"name": "Alex Morgan", "username": "alex-demo", "email": "alex@example.test", "password": password},
        {"name": "Jamie Morgan", "username": "jamie-demo", "email": "jamie@example.test", "password": secrets.token_urlsafe(32)},
    ))
    with repository.connect() as connection:
        user_id = connection.execute("SELECT id FROM users WHERE username='alex-demo'").fetchone()[0]
    month = repository.create_budget_month(household_id=household, month=today.strftime("%Y-%m"))
    repository.add_income(budget_month_id=month, name="Alex's paychecks", kind="main", planned_cents=320_000, received_cents=200_000)
    repository.add_income(budget_month_id=month, name="Jamie's paychecks", kind="main", planned_cents=200_000)
    categories = {}
    for order, (group_name, specs) in enumerate((
        ("Home", (("Rent", 180_000), ("Utilities", 25_000), ("Internet", 8_000))),
        ("Food", (("Groceries", 70_000), ("Dining Out", 25_000))),
        ("Everyday", (("Gas", 30_000), ("Household Supplies", 22_000), ("Health", 20_000), ("Clothing", 10_000))),
        ("Giving and Goals", (("Giving", 30_000), ("Emergency Savings", 50_000), ("Fun Money", 15_000))),
    )):
        group = repository.add_budget_group(budget_month_id=month, name=group_name, display_order=order)
        for index, (name, planned) in enumerate(specs):
            categories[name] = repository.add_category(budget_group_id=group, name=name, planned_cents=planned, display_order=index)
    # Paydays remain useful even when entry happens on the last day of a month.
    for offset in (6, 20):
        repository.add_payday(household_id=household, payday_date=today + timedelta(days=offset))
    previous_day = today.replace(day=1) - timedelta(days=1)
    next_day = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    txn_date = max(today.replace(day=1), today - timedelta(days=2))

    def transaction(key, amount, name, account="demo-spending", occurred_on=txn_date):
        return PlaidTransactionSnapshot("demo-" + key, account, amount, occurred_on, name, merchant_name=name)

    seed_transactions = (
        transaction("paycheck", 200_000, "Cedar Workshop Payroll"),
        transaction("groceries", -8_432, "Maple Market"),
        transaction("dining", -19_600, "Lantern Kitchen"),
        transaction("gas", -4_050, "Juniper Fuel"),
        transaction("split", -6_200, "Meadow General Store"),
        transaction("repair", -18_500, "Oak Street Auto", "demo-bills"),
        transaction("refund", 2_500, "Oak Street Auto Refund", "demo-bills"),
        transaction("transfer-out", -25_000, "Transfer to Bills Checking"),
        transaction("transfer-in", 25_000, "Transfer from Everyday Checking", "demo-bills"),
        transaction("prior-groceries", -15_000, "Maple Market", occurred_on=previous_day),
    )
    new_transactions = (transaction("new-groceries", -7_640, "Maple Market", occurred_on=today),
                        transaction("new-household", -2_399, "Willow Home Goods", occurred_on=today))
    client = DemoBankClient(seed_transactions, new_transactions)
    service = DemoBankService(repository, client)
    token_ref = service.token_store.store(secrets.token_urlsafe(32))
    item = repository.create_plaid_item(household_id=household, plaid_item_id="demo-bank-item", access_token_ref=token_ref,
        institution_id="demo-bank", institution_name="Fictional Community Bank")
    # This value denotes the ordinary readiness schema, not a real provider. The
    # isolated repository and injected no-network service determine the context.
    with repository.connect() as connection:
        connection.execute("INSERT INTO bank_sync_state(plaid_item_id,environment) VALUES (?,'production')", (item,))
    if not service.sync_balances(item).success:
        raise RuntimeError("Demo account fixture could not be imported")
    backing = next(a.id for a in repository.list_accounts(month) if a.plaid_account_id == "demo-bills")
    funds = {}
    for name, planned, target, amount, breakdown in (
        ("Car Repairs", 10_000, 120_000, 80_000, ({"name": "Tires and maintenance", "annual_cents": 120_000},)),
        ("Annual Insurance", 15_000, 180_000, 90_000, ({"name": "Auto policy", "annual_cents": 120_000}, {"name": "Home policy", "annual_cents": 60_000})),
        ("Gifts", 10_000, 120_000, 30_000, ({"name": "Birthdays", "annual_cents": 60_000}, {"name": "Holidays", "annual_cents": 60_000})),
    ):
        funds[name] = repository.create_fund(budget_month_id=month, name=name, backing_account_id=backing,
            monthly_plan_cents=planned, annual_target_cents=target, timing_note="Save monthly for irregular expenses",
            breakdown=breakdown, actor_user_id=user_id)
    # Copy before adding relative bills so future-month bills are never duplicated.
    previous = repository.create_budget_month(household_id=household, month=previous_day.strftime("%Y-%m"), copy_from_budget_month_id=month)
    following = repository.create_budget_month(household_id=household, month=next_day.strftime("%Y-%m"), copy_from_budget_month_id=month)
    month_ids = {previous_day.strftime("%Y-%m"): previous, today.strftime("%Y-%m"): month, next_day.strftime("%Y-%m"): following}
    repository.add_expected_bill(budget_month_id=previous, name="Previous rent", amount_cents=180_000, due_on=previous_day.replace(day=1), paid=True)
    for name, amount, offset, fund_id in (("Electric", 18_500, 3, None), ("Internet", 8_000, 4, None),
                                         ("Auto insurance installment", 80_000, 5, funds["Annual Insurance"]["id"]),
                                         ("Rent", 180_000, 10, None)):
        due = today + timedelta(days=offset)
        repository.add_expected_bill(budget_month_id=month_ids[due.strftime("%Y-%m")], name=name, amount_cents=amount,
            due_on=due, reserve_fund_id=fund_id)
    if not service.sync_transactions(item).success:
        raise RuntimeError("Demo transaction fixture could not be imported")
    with repository.connect() as connection:
        ids = {r["plaid_transaction_id"]: r["id"] for r in connection.execute("SELECT id,plaid_transaction_id FROM account_transactions")}
        prior_groceries = connection.execute("SELECT c.id FROM budget_categories c JOIN budget_groups g ON g.id=c.budget_group_id WHERE g.budget_month_id=? AND c.name='Groceries'", (previous,)).fetchone()[0]
    for key, category in (("groceries", categories["Groceries"]), ("dining", categories["Dining Out"]),
                          ("gas", categories["Gas"]), ("repair", funds["Car Repairs"]["category_id"]),
                          ("prior-groceries", prior_groceries)):
        repository.assign_transaction_category(transaction_id=ids["demo-" + key], category_id=category, reviewed=True)
    repository.split_transaction(transaction_id=ids["demo-split"], splits=(
        {"category_id": categories["Groceries"], "amount_cents": 4_000},
        {"category_id": categories["Household Supplies"], "amount_cents": 2_200}))
    repository.assign_transaction_refund(ids["demo-refund"], funds["Car Repairs"]["category_id"])
    repository.mark_transaction_reviewed(ids["demo-paycheck"])
    for key in ("transfer-in", "transfer-out"):
        repository.set_transaction_ignored(transaction_id=ids["demo-" + key], ignored=True, reason="Transfer between household accounts")
    for name, amount in (("Car Repairs", 80_000), ("Annual Insurance", 90_000), ("Gifts", 30_000)):
        repository.add_fund_entry(fund_id=funds[name]["id"], budget_month_id=month, kind="contribution", amount_cents=amount,
            occurred_on=today, idempotency_key="demo-start-" + name, note="Money already set aside for upcoming expenses", actor_user_id=user_id)
    repository.transfer_funds(source_fund_id=funds["Car Repairs"]["id"], target_fund_id=funds["Gifts"]["id"], budget_month_id=month,
        amount_cents=5_000, occurred_on=today, idempotency_key="demo-gift-move", note="Adjust the birthday plan", actor_user_id=user_id)
    repository.add_fund_entry(fund_id=funds["Gifts"]["id"], budget_month_id=month, kind="release", amount_cents=2_500,
        occurred_on=today, idempotency_key="demo-gift-release", note="Free up an unused earmark", actor_user_id=user_id)
    repository.create_merchant_rule(household_id=household, merchant_match_text="Maple Market", category_id=categories["Groceries"], actor_user_id=user_id)
    reconcile_bank(repository, month, bank_status(repository, month)["revision"])
    repository.safe_to_spend(budget_month_id=month, category_id=categories["Groceries"], purchase_amount_cents=2_500, today=today, actor_user_id=user_id)
    login = repository.authenticate_local_user("alex-demo", password)
    if login is None:
        raise RuntimeError("Demo session could not be created")
    # The next ordinary sync sees new spending. Readiness/review requirements stay
    # exactly the same as the real household, including user reconciliation.
    client.new_activity_available = True
    return DemoContext(repository, service, login, household, month, user_id)
