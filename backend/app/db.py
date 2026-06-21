from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator

from .domain import (
    BudgetSummary,
    CategoryLine,
    ExpectedBill,
    IncomeLine,
    SafeToSpendResult,
    Urgency,
    calculate_safe_to_spend,
    summarize_budget,
)


class BudgetRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        with self.connect() as connection:
            connection.executescript(schema_path.read_text(encoding="utf-8"))

    def create_household(self, name: str, spouses: Iterable[dict[str, str]] = ()) -> int:
        with self.connect() as connection:
            household_id = insert_and_return_id(connection, "INSERT INTO households(name) VALUES (?)", (name,))
            for spouse in spouses:
                connection.execute(
                    "INSERT INTO users(household_id, name, email, role) VALUES (?, ?, ?, ?)",
                    (household_id, spouse["name"], spouse.get("email"), spouse.get("role", "spouse")),
                )
            return household_id

    def create_budget_month(
        self,
        *,
        household_id: int,
        month: str,
        included_account_balance_cents: int = 0,
        low_cushion_daily_cents: int = 5_000,
    ) -> int:
        with self.connect() as connection:
            return insert_and_return_id(
                connection,
                """
                INSERT INTO budget_months(
                    household_id,
                    month,
                    included_account_balance_cents,
                    low_cushion_daily_cents
                )
                VALUES (?, ?, ?, ?)
                """,
                (household_id, month, included_account_balance_cents, low_cushion_daily_cents),
            )

    def update_account_balance(self, budget_month_id: int, included_account_balance_cents: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE budget_months SET included_account_balance_cents = ? WHERE id = ?",
                (included_account_balance_cents, budget_month_id),
            )

    def add_cash_account(
        self,
        *,
        budget_month_id: int,
        name: str,
        account_type: str,
        balance_cents: int,
        included_in_cash_reality: bool = True,
    ) -> int:
        with self.connect() as connection:
            return insert_and_return_id(
                connection,
                """
                INSERT INTO cash_accounts(
                    budget_month_id,
                    name,
                    account_type,
                    balance_cents,
                    included_in_cash_reality
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    budget_month_id,
                    name,
                    account_type,
                    balance_cents,
                    1 if included_in_cash_reality else 0,
                ),
            )

    def update_cash_account(
        self,
        *,
        account_id: int,
        balance_cents: int | None = None,
        included_in_cash_reality: bool | None = None,
    ) -> None:
        assignments: list[str] = []
        values: list[Any] = []
        if balance_cents is not None:
            assignments.append("balance_cents = ?")
            values.append(balance_cents)
        if included_in_cash_reality is not None:
            assignments.append("included_in_cash_reality = ?")
            values.append(1 if included_in_cash_reality else 0)
        if not assignments:
            return
        values.append(account_id)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE cash_accounts SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

    def add_income(
        self,
        *,
        budget_month_id: int,
        name: str,
        kind: str,
        planned_cents: int,
        received_cents: int = 0,
    ) -> int:
        with self.connect() as connection:
            return insert_and_return_id(
                connection,
                """
                INSERT INTO income_plan(budget_month_id, name, kind, planned_cents, received_cents)
                VALUES (?, ?, ?, ?, ?)
                """,
                (budget_month_id, name, kind, planned_cents, received_cents),
            )

    def add_budget_group(self, *, budget_month_id: int, name: str, display_order: int = 0) -> int:
        with self.connect() as connection:
            return insert_and_return_id(
                connection,
                "INSERT INTO budget_groups(budget_month_id, name, display_order) VALUES (?, ?, ?)",
                (budget_month_id, name, display_order),
            )

    def add_category(
        self,
        *,
        budget_group_id: int,
        name: str,
        planned_cents: int,
        display_order: int = 0,
    ) -> int:
        with self.connect() as connection:
            return insert_and_return_id(
                connection,
                """
                INSERT INTO budget_categories(budget_group_id, name, planned_cents, display_order)
                VALUES (?, ?, ?, ?)
                """,
                (budget_group_id, name, planned_cents, display_order),
            )

    def update_category(
        self,
        *,
        category_id: int,
        name: str | None = None,
        planned_cents: int | None = None,
        archived: bool | None = None,
    ) -> None:
        assignments: list[str] = []
        values: list[Any] = []
        if name is not None:
            assignments.append("name = ?")
            values.append(name)
        if planned_cents is not None:
            assignments.append("planned_cents = ?")
            values.append(planned_cents)
        if archived is not None:
            assignments.append("archived = ?")
            values.append(1 if archived else 0)
        if not assignments:
            return
        values.append(category_id)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE budget_categories SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

    def record_spending(
        self,
        *,
        category_id: int,
        amount_cents: int,
        occurred_on: date,
        note: str | None = None,
    ) -> int:
        with self.connect() as connection:
            return insert_and_return_id(
                connection,
                """
                INSERT INTO manual_spending(budget_category_id, amount_cents, occurred_on, note)
                VALUES (?, ?, ?, ?)
                """,
                (category_id, amount_cents, occurred_on.isoformat(), note),
            )

    def add_expected_bill(
        self,
        *,
        budget_month_id: int,
        name: str,
        amount_cents: int,
        due_on: date,
        paid: bool = False,
    ) -> int:
        with self.connect() as connection:
            return insert_and_return_id(
                connection,
                """
                INSERT INTO expected_bills(budget_month_id, name, amount_cents, due_on, paid)
                VALUES (?, ?, ?, ?, ?)
                """,
                (budget_month_id, name, amount_cents, due_on.isoformat(), 1 if paid else 0),
            )

    def add_payday(self, *, household_id: int, payday_date: date) -> int:
        with self.connect() as connection:
            return insert_and_return_id(
                connection,
                "INSERT OR IGNORE INTO paydays(household_id, payday_date) VALUES (?, ?)",
                (household_id, payday_date.isoformat()),
            )

    def get_summary(self, budget_month_id: int, today: date) -> BudgetSummary:
        snapshot = self._load_snapshot(budget_month_id)
        return summarize_budget(
            budget_month_id=budget_month_id,
            month=snapshot["budget_month"]["month"],
            income_lines=snapshot["income_lines"],
            categories=snapshot["categories"],
            included_account_balance_cents=snapshot["included_account_balance_cents"],
            expected_bills=snapshot["expected_bills"],
            paydays=snapshot["paydays"],
            today=today,
        )

    def safe_to_spend(
        self,
        *,
        budget_month_id: int,
        category_id: int,
        purchase_amount_cents: int,
        today: date,
        urgency: Urgency = "planned_want",
    ) -> SafeToSpendResult:
        snapshot = self._load_snapshot(budget_month_id)
        category = next((item for item in snapshot["categories"] if item.id == category_id), None)
        if category is None:
            raise LookupError(f"Category {category_id} is not part of budget month {budget_month_id}")
        return calculate_safe_to_spend(
            category=category,
            purchase_amount_cents=purchase_amount_cents,
            included_account_balance_cents=snapshot["included_account_balance_cents"],
            expected_bills=snapshot["expected_bills"],
            paydays=snapshot["paydays"],
            today=today,
            urgency=urgency,
            low_cushion_daily_cents=snapshot["budget_month"]["low_cushion_daily_cents"],
        )

    def _load_snapshot(self, budget_month_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            budget_month = connection.execute(
                "SELECT * FROM budget_months WHERE id = ?",
                (budget_month_id,),
            ).fetchone()
            if budget_month is None:
                raise LookupError(f"Budget month {budget_month_id} not found")

            income_rows = connection.execute(
                "SELECT * FROM income_plan WHERE budget_month_id = ? ORDER BY id",
                (budget_month_id,),
            ).fetchall()
            category_rows = connection.execute(
                """
                SELECT
                    c.id,
                    c.name,
                    c.planned_cents,
                    c.archived,
                    COALESCE(SUM(s.amount_cents), 0) AS spent_cents
                FROM budget_categories c
                JOIN budget_groups g ON g.id = c.budget_group_id
                LEFT JOIN manual_spending s ON s.budget_category_id = c.id
                WHERE g.budget_month_id = ?
                GROUP BY c.id, c.name, c.planned_cents, c.archived, c.display_order
                ORDER BY g.display_order, c.display_order, c.id
                """,
                (budget_month_id,),
            ).fetchall()
            bill_rows = connection.execute(
                "SELECT * FROM expected_bills WHERE budget_month_id = ? ORDER BY due_on, id",
                (budget_month_id,),
            ).fetchall()
            account_rows = connection.execute(
                "SELECT * FROM cash_accounts WHERE budget_month_id = ? ORDER BY id",
                (budget_month_id,),
            ).fetchall()
            payday_rows = connection.execute(
                "SELECT payday_date FROM paydays WHERE household_id = ? ORDER BY payday_date",
                (budget_month["household_id"],),
            ).fetchall()

        if account_rows:
            included_account_balance_cents = sum(
                row["balance_cents"]
                for row in account_rows
                if row["included_in_cash_reality"]
            )
        else:
            included_account_balance_cents = budget_month["included_account_balance_cents"]

        return {
            "budget_month": dict(budget_month),
            "included_account_balance_cents": included_account_balance_cents,
            "income_lines": [
                IncomeLine(
                    name=row["name"],
                    kind=row["kind"],
                    planned_cents=row["planned_cents"],
                    received_cents=row["received_cents"],
                )
                for row in income_rows
            ],
            "categories": [
                CategoryLine(
                    id=row["id"],
                    name=row["name"],
                    planned_cents=row["planned_cents"],
                    spent_cents=row["spent_cents"],
                    archived=bool(row["archived"]),
                )
                for row in category_rows
            ],
            "expected_bills": [
                ExpectedBill(
                    name=row["name"],
                    amount_cents=row["amount_cents"],
                    due_on=date.fromisoformat(row["due_on"]),
                    paid=bool(row["paid"]),
                )
                for row in bill_rows
            ],
            "paydays": [date.fromisoformat(row["payday_date"]) for row in payday_rows],
        }


def insert_and_return_id(connection: sqlite3.Connection, sql: str, values: Iterable[Any]) -> int:
    cursor = connection.execute(sql, tuple(values))
    return int(cursor.lastrowid)


def summary_to_dict(summary: BudgetSummary) -> dict[str, Any]:
    payload = asdict(summary)
    payload["next_payday"] = summary.next_payday.isoformat()
    payload["categories"] = [asdict(category) | {"remaining_cents": category.remaining_cents} for category in summary.categories]
    return payload


def safe_to_spend_to_dict(result: SafeToSpendResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["warning_level"] = result.warning_level.value
    payload["next_payday"] = result.next_payday.isoformat()
    return payload
