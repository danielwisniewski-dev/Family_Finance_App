from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator

from .auth import hash_password, hash_session_token, new_session_token, verify_password
from .domain import (
    AccountLine,
    BudgetSummary,
    CategoryLine,
    ExpectedBill,
    IncomeLine,
    NotificationEvent,
    PlaidItemLine,
    SafeToSpendResult,
    TransactionCategoryAssignment,
    TransactionDetail,
    TransactionLine,
    TransactionUpsertResult,
    Urgency,
    WarningLevel,
    calculate_safe_to_spend,
    summarize_budget,
)


FORBIDDEN_METADATA_TERMS = (
    "access_token",
    "access_token_ref",
    "token_ref",
    "api_key",
    "api key",
    "openai_api_key",
    "openai api key",
    "secret",
    "raw_provider",
    "provider_error",
    "plaid_token",
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
            ensure_column(connection, "users", "username", "TEXT")
            ensure_column(connection, "users", "password_hash", "TEXT")
            ensure_column(connection, "account_transactions", "reviewed", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(connection, "account_transactions", "ignored", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(connection, "account_transactions", "ignored_reason", "TEXT")

    def create_household(self, name: str, spouses: Iterable[dict[str, str]] = ()) -> int:
        with self.connect() as connection:
            household_id = insert_and_return_id(connection, "INSERT INTO households(name) VALUES (?)", (name,))
            for spouse in spouses:
                password_hash = spouse.get("password_hash")
                if password_hash is None and spouse.get("password"):
                    password_hash = hash_password(spouse["password"])
                connection.execute(
                    """
                    INSERT INTO users(household_id, name, username, email, password_hash, role)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        household_id,
                        spouse["name"],
                        normalize_login(spouse.get("username")),
                        normalize_login(spouse.get("email")),
                        password_hash,
                        spouse.get("role", "spouse"),
                    ),
                )
            return household_id

    def create_local_user(
        self,
        *,
        household_id: int,
        name: str,
        username: str,
        email: str | None,
        password: str,
        role: str = "spouse",
    ) -> int:
        with self.connect() as connection:
            self._require_household(connection, household_id)
            return insert_and_return_id(
                connection,
                """
                INSERT INTO users(household_id, name, username, email, password_hash, role)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    household_id,
                    name,
                    require_login_value(username, "username"),
                    normalize_login(email),
                    hash_password(password),
                    role,
                ),
            )

    def authenticate_local_user(self, login: str, password: str) -> dict[str, Any] | None:
        cleaned = require_login_value(login, "login")
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    u.*,
                    h.name AS household_name
                FROM users u
                JOIN households h ON h.id = u.household_id
                WHERE lower(u.username) = ? OR lower(u.email) = ?
                """,
                (cleaned, cleaned),
            ).fetchone()
            if row is None or not verify_password(password, row["password_hash"]):
                return None
            token = new_session_token()
            connection.execute(
                "INSERT INTO auth_sessions(user_id, token_hash) VALUES (?, ?)",
                (row["id"], hash_session_token(token)),
            )
            return {
                "token": token,
                "user": safe_user_from_row(row),
                "household": safe_household_from_user_row(row),
            }

    def auth_context_for_token(self, token: str) -> dict[str, Any] | None:
        token = (token or "").strip()
        if not token:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    u.*,
                    h.name AS household_name
                FROM auth_sessions s
                JOIN users u ON u.id = s.user_id
                JOIN households h ON h.id = u.household_id
                WHERE s.token_hash = ?
                """,
                (hash_session_token(token),),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE auth_sessions SET last_used_at = CURRENT_TIMESTAMP WHERE token_hash = ?",
                (hash_session_token(token),),
            )
            return {
                "user_id": int(row["id"]),
                "household_id": int(row["household_id"]),
                "user": safe_user_from_row(row),
                "household": safe_household_from_user_row(row),
            }

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
        validate_account_type(account_type)
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

    def list_accounts(self, budget_month_id: int) -> list[AccountLine]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM cash_accounts WHERE budget_month_id = ? ORDER BY id",
                (budget_month_id,),
            ).fetchall()
        return [account_from_row(row) for row in rows]

    def household_id_for_budget_month(self, budget_month_id: int) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT household_id FROM budget_months WHERE id = ?",
                (budget_month_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Budget month {budget_month_id} not found")
        return int(row["household_id"])

    def require_budget_month_access(self, budget_month_id: int, household_id: int) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM budget_months WHERE id = ? AND household_id = ?",
                (budget_month_id, household_id),
            ).fetchone()
        if row is None:
            raise PermissionError("Budget month is not available to this household")

    def require_account_access(self, account_id: int, household_id: int) -> None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT a.id
                FROM cash_accounts a
                JOIN budget_months b ON b.id = a.budget_month_id
                WHERE a.id = ? AND b.household_id = ?
                """,
                (account_id, household_id),
            ).fetchone()
        if row is None:
            raise PermissionError("Account is not available to this household")

    def require_category_access(self, category_id: int, household_id: int) -> None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT c.id
                FROM budget_categories c
                JOIN budget_groups g ON g.id = c.budget_group_id
                JOIN budget_months b ON b.id = g.budget_month_id
                WHERE c.id = ? AND b.household_id = ?
                """,
                (category_id, household_id),
            ).fetchone()
        if row is None:
            raise PermissionError("Category is not available to this household")

    def require_budget_group_access(self, budget_group_id: int, household_id: int) -> None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT g.id
                FROM budget_groups g
                JOIN budget_months b ON b.id = g.budget_month_id
                WHERE g.id = ? AND b.household_id = ?
                """,
                (budget_group_id, household_id),
            ).fetchone()
        if row is None:
            raise PermissionError("Budget group is not available to this household")

    def require_transaction_access(self, transaction_id: int, household_id: int) -> None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT t.id
                FROM account_transactions t
                JOIN cash_accounts a ON a.id = t.cash_account_id
                JOIN budget_months b ON b.id = a.budget_month_id
                WHERE t.id = ? AND b.household_id = ?
                """,
                (transaction_id, household_id),
            ).fetchone()
        if row is None:
            raise PermissionError("Transaction is not available to this household")

    def require_notification_access(self, notification_id: int, household_id: int) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM notification_events WHERE id = ? AND household_id = ?",
                (notification_id, household_id),
            ).fetchone()
        if row is None:
            raise PermissionError("Notification is not available to this household")

    def require_plaid_item_access(self, plaid_item_id: int, household_id: int) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM plaid_items WHERE id = ? AND household_id = ?",
                (plaid_item_id, household_id),
            ).fetchone()
        if row is None:
            raise PermissionError("Plaid item is not available to this household")

    def set_account_included(self, account_id: int, included_in_cash_reality: bool) -> None:
        self.update_cash_account(
            account_id=account_id,
            included_in_cash_reality=included_in_cash_reality,
        )

    def create_plaid_item(
        self,
        *,
        household_id: int,
        plaid_item_id: str,
        access_token_ref: str,
        institution_id: str | None = None,
        institution_name: str | None = None,
        sync_cursor: str | None = None,
    ) -> int:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM plaid_items WHERE plaid_item_id = ?",
                (plaid_item_id,),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE plaid_items
                    SET
                        household_id = ?,
                        access_token_ref = ?,
                        institution_id = ?,
                        institution_name = ?,
                        sync_cursor = ?,
                        status = 'connected',
                        last_error_code = NULL,
                        last_error_message = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        household_id,
                        access_token_ref,
                        institution_id,
                        institution_name,
                        sync_cursor,
                        existing["id"],
                    ),
                )
                return int(existing["id"])
            return insert_and_return_id(
                connection,
                """
                INSERT INTO plaid_items(
                    household_id,
                    plaid_item_id,
                    access_token_ref,
                    institution_id,
                    institution_name,
                    sync_cursor
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    household_id,
                    plaid_item_id,
                    access_token_ref,
                    institution_id,
                    institution_name,
                    sync_cursor,
                ),
            )

    def store_plaid_access_token(self, token_ref: str, access_token: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO plaid_access_tokens(token_ref, access_token)
                VALUES (?, ?)
                ON CONFLICT(token_ref) DO UPDATE SET access_token = excluded.access_token
                """,
                (token_ref, access_token),
            )

    def retrieve_plaid_access_token(self, token_ref: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT access_token FROM plaid_access_tokens WHERE token_ref = ?",
                (token_ref,),
            ).fetchone()
        return str(row["access_token"]) if row is not None else None

    def get_plaid_item(self, plaid_item_row_id: int) -> PlaidItemLine:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM plaid_items WHERE id = ?",
                (plaid_item_row_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Plaid item {plaid_item_row_id} not found")
        return plaid_item_from_row(row)

    def list_plaid_items(self, household_id: int) -> list[PlaidItemLine]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM plaid_items WHERE household_id = ? ORDER BY id",
                (household_id,),
            ).fetchall()
        return [plaid_item_from_row(row) for row in rows]

    def upsert_connected_account(
        self,
        *,
        budget_month_id: int,
        plaid_item_id: int,
        plaid_account_id: str,
        name: str,
        account_type: str,
        balance_cents: int,
        included_in_cash_reality: bool = True,
        subtype: str | None = None,
        mask: str | None = None,
        official_name: str | None = None,
        available_balance_cents: int | None = None,
        current_balance_cents: int | None = None,
    ) -> int:
        validate_account_type(account_type)
        with self.connect() as connection:
            budget_month = connection.execute(
                "SELECT household_id FROM budget_months WHERE id = ?",
                (budget_month_id,),
            ).fetchone()
            if budget_month is None:
                raise LookupError(f"Budget month {budget_month_id} not found")
            plaid_item = connection.execute(
                "SELECT household_id FROM plaid_items WHERE id = ?",
                (plaid_item_id,),
            ).fetchone()
            if plaid_item is None:
                raise LookupError(f"Plaid item {plaid_item_id} not found")
            if plaid_item["household_id"] != budget_month["household_id"]:
                raise ValueError("Plaid item does not belong to the budget month household")

            existing = connection.execute(
                """
                SELECT id
                FROM cash_accounts
                WHERE plaid_item_id = ? AND plaid_account_id = ?
                """,
                (plaid_item_id, plaid_account_id),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE cash_accounts
                    SET
                        budget_month_id = ?,
                        name = ?,
                        account_type = ?,
                        subtype = ?,
                        mask = ?,
                        official_name = ?,
                        balance_cents = ?,
                        available_balance_cents = ?,
                        current_balance_cents = ?,
                        included_in_cash_reality = ?
                    WHERE id = ?
                    """,
                    (
                        budget_month_id,
                        name,
                        account_type,
                        subtype,
                        mask,
                        official_name,
                        balance_cents,
                        available_balance_cents,
                        current_balance_cents,
                        1 if included_in_cash_reality else 0,
                        existing["id"],
                    ),
                )
                return int(existing["id"])
            return insert_and_return_id(
                connection,
                """
                INSERT INTO cash_accounts(
                    budget_month_id,
                    plaid_item_id,
                    plaid_account_id,
                    name,
                    account_type,
                    subtype,
                    mask,
                    official_name,
                    balance_cents,
                    available_balance_cents,
                    current_balance_cents,
                    included_in_cash_reality
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    budget_month_id,
                    plaid_item_id,
                    plaid_account_id,
                    name,
                    account_type,
                    subtype,
                    mask,
                    official_name,
                    balance_cents,
                    available_balance_cents,
                    current_balance_cents,
                    1 if included_in_cash_reality else 0,
                ),
            )

    def update_connected_account_balance(
        self,
        *,
        plaid_item_id: int,
        plaid_account_id: str,
        balance_cents: int,
        available_balance_cents: int | None = None,
        current_balance_cents: int | None = None,
    ) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id
                FROM cash_accounts
                WHERE plaid_item_id = ? AND plaid_account_id = ?
                """,
                (plaid_item_id, plaid_account_id),
            ).fetchone()
            if row is None:
                raise LookupError(f"Plaid account {plaid_account_id} not found")
            connection.execute(
                """
                UPDATE cash_accounts
                SET
                    balance_cents = ?,
                    available_balance_cents = ?,
                    current_balance_cents = ?,
                    last_balance_synced_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    balance_cents,
                    available_balance_cents,
                    current_balance_cents,
                    row["id"],
                ),
            )
            return int(row["id"])

    def find_account_id_by_plaid_account(self, plaid_item_id: int, plaid_account_id: str) -> int | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id
                FROM cash_accounts
                WHERE plaid_item_id = ? AND plaid_account_id = ?
                """,
                (plaid_item_id, plaid_account_id),
            ).fetchone()
        return int(row["id"]) if row is not None else None

    def upsert_plaid_transaction(
        self,
        *,
        cash_account_id: int,
        plaid_transaction_id: str,
        amount_cents: int,
        occurred_on: date,
        name: str,
        merchant_name: str | None = None,
        pending: bool = False,
        category_hint: str | None = None,
    ) -> TransactionUpsertResult:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM account_transactions WHERE plaid_transaction_id = ?",
                (plaid_transaction_id,),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE account_transactions
                    SET
                        cash_account_id = ?,
                        amount_cents = ?,
                        occurred_on = ?,
                        name = ?,
                        merchant_name = ?,
                        pending = ?,
                        category_hint = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        cash_account_id,
                        amount_cents,
                        occurred_on.isoformat(),
                        name,
                        merchant_name,
                        1 if pending else 0,
                        category_hint,
                        existing["id"],
                    ),
                )
                self._apply_best_rule_if_allowed(connection, int(existing["id"]))
                return TransactionUpsertResult(transaction_id=int(existing["id"]), created=False)
            transaction_id = insert_and_return_id(
                connection,
                """
                INSERT INTO account_transactions(
                    cash_account_id,
                    plaid_transaction_id,
                    amount_cents,
                    occurred_on,
                    name,
                    merchant_name,
                    pending,
                    category_hint
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cash_account_id,
                    plaid_transaction_id,
                    amount_cents,
                    occurred_on.isoformat(),
                    name,
                    merchant_name,
                    1 if pending else 0,
                    category_hint,
                ),
            )
            self._record_transaction_event(
                connection,
                transaction_id=transaction_id,
                event_type="imported",
                source="plaid_hint" if category_hint else None,
                metadata={"category_hint": category_hint, "plaid_transaction_id": plaid_transaction_id},
            )
            self._apply_best_rule_if_allowed(connection, transaction_id)
            return TransactionUpsertResult(transaction_id=transaction_id, created=True)

    def mark_plaid_transaction_removed(self, plaid_transaction_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM account_transactions WHERE plaid_transaction_id = ?",
                (plaid_transaction_id,),
            ).fetchone()
            if row is None:
                return False
            already_removed = bool(row["ignored"]) and row["ignored_reason"] == "Removed by Plaid sync"
            connection.execute(
                """
                UPDATE account_transactions
                SET
                    ignored = 1,
                    ignored_reason = 'Removed by Plaid sync',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"],),
            )
            if not already_removed:
                self._record_transaction_event(
                    connection,
                    transaction_id=int(row["id"]),
                    event_type="removed_by_plaid",
                    metadata={"plaid_transaction_id": plaid_transaction_id},
                )
            return True

    def list_transactions(self, cash_account_id: int) -> list[TransactionLine]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM account_transactions
                WHERE cash_account_id = ?
                ORDER BY occurred_on, id
                """,
                (cash_account_id,),
            ).fetchall()
        return [transaction_from_row(row) for row in rows]

    def list_budget_transactions(self, budget_month_id: int) -> list[TransactionDetail]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT t.*
                FROM account_transactions t
                JOIN cash_accounts a ON a.id = t.cash_account_id
                WHERE a.budget_month_id = ?
                ORDER BY t.occurred_on, t.id
                """,
                (budget_month_id,),
            ).fetchall()
            return [self._transaction_detail_from_row(connection, row) for row in rows]

    def list_uncategorized_transactions(self, budget_month_id: int) -> list[TransactionDetail]:
        return [
            detail
            for detail in self.list_budget_transactions(budget_month_id)
            if not detail.transaction.ignored and not detail.assignments
        ]

    def list_transaction_review_queue(self, budget_month_id: int) -> list[TransactionDetail]:
        return [
            detail
            for detail in self.list_budget_transactions(budget_month_id)
            if detail.needs_review
        ]

    def get_transaction_detail(self, transaction_id: int) -> TransactionDetail:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM account_transactions WHERE id = ?",
                (transaction_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"Transaction {transaction_id} not found")
            return self._transaction_detail_from_row(connection, row)

    def mark_transaction_reviewed(
        self,
        transaction_id: int,
        reviewed: bool = True,
        actor_user_id: int | None = None,
    ) -> None:
        with self.connect() as connection:
            self._require_transaction(connection, transaction_id)
            connection.execute(
                """
                UPDATE account_transactions
                SET reviewed = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (1 if reviewed else 0, transaction_id),
            )
            self._record_transaction_event(
                connection,
                transaction_id=transaction_id,
                event_type="marked_reviewed" if reviewed else "marked_unreviewed",
            )
            context = self._notification_context_for_transaction(connection, transaction_id)
            self._insert_notification_event(
                connection,
                household_id=context["household_id"],
                budget_month_id=context["budget_month_id"],
                event_type="transaction_marked_reviewed" if reviewed else "transaction_marked_unreviewed",
                actor_user_id=actor_user_id,
                affected_entity_type="transaction",
                affected_entity_id=transaction_id,
                title="Transaction marked reviewed" if reviewed else "Transaction marked unreviewed",
                message=f"{context['transaction_name']} was marked {'reviewed' if reviewed else 'unreviewed'}.",
                severity="info",
                metadata={"transaction_id": transaction_id, "reviewed": reviewed},
            )

    def assign_transaction_category(
        self,
        *,
        transaction_id: int,
        category_id: int,
        source: str = "manual",
        reviewed: bool = True,
        actor_user_id: int | None = None,
    ) -> None:
        if source not in {"manual", "rule", "plaid_hint"}:
            raise ValueError("source must be manual, rule, or plaid_hint")
        with self.connect() as connection:
            transaction = self._require_transaction(connection, transaction_id)
            self._validate_category_for_transaction(connection, transaction_id, category_id)
            amount_cents = budget_amount_cents(transaction["amount_cents"])
            previous_assignments = self._active_assignments(connection, transaction_id)
            self._supersede_active_assignments(connection, transaction_id)
            self._insert_assignment(
                connection,
                transaction_id=transaction_id,
                category_id=category_id,
                amount_cents=amount_cents,
                source=source,
            )
            connection.execute(
                """
                UPDATE account_transactions
                SET reviewed = ?, ignored = 0, ignored_reason = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (1 if reviewed else int(transaction["reviewed"]), transaction_id),
            )
            self._record_transaction_event(
                connection,
                transaction_id=transaction_id,
                event_type="category_assigned",
                source=source,
                category_id=category_id,
                amount_cents=amount_cents,
            )
            previous_category_ids = [int(row["budget_category_id"]) for row in previous_assignments]
            context = self._notification_context_for_transaction(connection, transaction_id)
            category_name = self._category_name(connection, category_id)
            recategorized = bool(previous_category_ids) and previous_category_ids != [category_id]
            old_category_name = (
                self._category_name(connection, previous_category_ids[0])
                if len(previous_category_ids) == 1
                else None
            )
            if recategorized:
                title = "Transaction recategorized"
                message = (
                    f"{context['transaction_name']} moved from {old_category_name or 'multiple categories'} "
                    f"to {category_name}."
                )
                event_type = "transaction_recategorized"
            else:
                title = "Transaction category assigned"
                message = f"{context['transaction_name']} was assigned to {category_name}."
                event_type = "transaction_category_assigned"
            self._insert_notification_event(
                connection,
                household_id=context["household_id"],
                budget_month_id=context["budget_month_id"],
                event_type=event_type,
                actor_user_id=actor_user_id,
                affected_entity_type="transaction",
                affected_entity_id=transaction_id,
                title=title,
                message=message,
                severity="info",
                metadata={
                    "transaction_id": transaction_id,
                    "category_id": category_id,
                    "previous_category_ids": previous_category_ids,
                    "amount_cents": amount_cents,
                    "source": source,
                },
            )

    def remove_transaction_category(
        self,
        transaction_id: int,
        reviewed: bool = False,
        actor_user_id: int | None = None,
    ) -> None:
        with self.connect() as connection:
            self._require_transaction(connection, transaction_id)
            previous_assignments = self._active_assignments(connection, transaction_id)
            self._supersede_active_assignments(connection, transaction_id)
            connection.execute(
                """
                UPDATE account_transactions
                SET reviewed = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (1 if reviewed else 0, transaction_id),
            )
            self._record_transaction_event(
                connection,
                transaction_id=transaction_id,
                event_type="category_removed",
            )
            context = self._notification_context_for_transaction(connection, transaction_id)
            self._insert_notification_event(
                connection,
                household_id=context["household_id"],
                budget_month_id=context["budget_month_id"],
                event_type="transaction_category_removed",
                actor_user_id=actor_user_id,
                affected_entity_type="transaction",
                affected_entity_id=transaction_id,
                title="Transaction category removed",
                message=f"{context['transaction_name']} was returned to uncategorized review.",
                severity="info",
                metadata={
                    "transaction_id": transaction_id,
                    "previous_category_ids": [int(row["budget_category_id"]) for row in previous_assignments],
                    "reviewed": reviewed,
                },
            )

    def split_transaction(
        self,
        *,
        transaction_id: int,
        splits: Iterable[dict[str, int]],
        reviewed: bool = True,
    ) -> None:
        split_rows = tuple(splits)
        if not split_rows:
            raise ValueError("At least one split is required")
        with self.connect() as connection:
            transaction = self._require_transaction(connection, transaction_id)
            expected_total = budget_amount_cents(transaction["amount_cents"])
            actual_total = sum(int(row["amount_cents"]) for row in split_rows)
            if actual_total != expected_total:
                raise ValueError("Split amounts must equal the transaction amount")
            self._supersede_active_assignments(connection, transaction_id)
            for row in split_rows:
                category_id = int(row["category_id"])
                amount_cents = int(row["amount_cents"])
                if amount_cents <= 0:
                    raise ValueError("Split amounts must be positive")
                self._validate_category_for_transaction(connection, transaction_id, category_id)
                self._insert_assignment(
                    connection,
                    transaction_id=transaction_id,
                    category_id=category_id,
                    amount_cents=amount_cents,
                    source="split",
                )
                self._record_transaction_event(
                    connection,
                    transaction_id=transaction_id,
                    event_type="split_line_assigned",
                    source="split",
                    category_id=category_id,
                    amount_cents=amount_cents,
                )
            connection.execute(
                """
                UPDATE account_transactions
                SET reviewed = ?, ignored = 0, ignored_reason = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (1 if reviewed else int(transaction["reviewed"]), transaction_id),
            )
            self._record_transaction_event(
                connection,
                transaction_id=transaction_id,
                event_type="transaction_split",
                source="split",
                amount_cents=actual_total,
                metadata={"split_count": len(split_rows)},
            )

    def set_transaction_ignored(
        self,
        *,
        transaction_id: int,
        ignored: bool = True,
        reason: str | None = None,
        actor_user_id: int | None = None,
    ) -> None:
        with self.connect() as connection:
            self._require_transaction(connection, transaction_id)
            if ignored:
                self._supersede_active_assignments(connection, transaction_id)
            connection.execute(
                """
                UPDATE account_transactions
                SET
                    ignored = ?,
                    ignored_reason = ?,
                    reviewed = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (1 if ignored else 0, reason if ignored else None, transaction_id),
            )
            self._record_transaction_event(
                connection,
                transaction_id=transaction_id,
                event_type="ignored" if ignored else "unignored",
                metadata={"reason": reason} if reason else None,
            )
            context = self._notification_context_for_transaction(connection, transaction_id)
            self._insert_notification_event(
                connection,
                household_id=context["household_id"],
                budget_month_id=context["budget_month_id"],
                event_type="transaction_ignored" if ignored else "transaction_unignored",
                actor_user_id=actor_user_id,
                affected_entity_type="transaction",
                affected_entity_id=transaction_id,
                title="Transaction ignored" if ignored else "Transaction unignored",
                message=(
                    f"{context['transaction_name']} was excluded from budget spending."
                    if ignored
                    else f"{context['transaction_name']} was returned to budget review."
                ),
                severity="important" if ignored else "caution",
                metadata={"transaction_id": transaction_id, "ignored": ignored, "reason": reason} if reason else {
                    "transaction_id": transaction_id,
                    "ignored": ignored,
                },
            )

    def create_notification_event(
        self,
        *,
        household_id: int,
        budget_month_id: int | None,
        event_type: str,
        actor_user_id: int | None,
        affected_entity_type: str,
        affected_entity_id: int | None,
        title: str,
        message: str,
        severity: str = "info",
        metadata: dict[str, object] | None = None,
    ) -> int:
        with self.connect() as connection:
            return self._insert_notification_event(
                connection,
                household_id=household_id,
                budget_month_id=budget_month_id,
                event_type=event_type,
                actor_user_id=actor_user_id,
                affected_entity_type=affected_entity_type,
                affected_entity_id=affected_entity_id,
                title=title,
                message=message,
                severity=severity,
                metadata=metadata,
            )

    def list_notification_events(
        self,
        *,
        household_id: int | None = None,
        budget_month_id: int | None = None,
        user_id: int | None = None,
        event_type: str | None = None,
        severity: str | None = None,
    ) -> list[NotificationEvent]:
        if household_id is None and budget_month_id is None:
            raise ValueError("household_id or budget_month_id is required")
        clauses: list[str] = []
        values: list[Any] = []
        if household_id is not None:
            clauses.append("household_id = ?")
            values.append(household_id)
        if budget_month_id is not None:
            clauses.append("budget_month_id = ?")
            values.append(budget_month_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            values.append(event_type)
        if severity is not None:
            validate_notification_severity(severity)
            clauses.append("severity = ?")
            values.append(severity)
        where = " AND ".join(clauses)
        with self.connect() as connection:
            if user_id is not None:
                self._validate_user_for_notification_scope(
                    connection,
                    user_id=user_id,
                    household_id=household_id,
                    budget_month_id=budget_month_id,
                )
                values = [user_id] + values
                rows = connection.execute(
                    f"""
                    SELECT
                        n.*,
                        r.read_at AS viewer_read_at,
                        r.user_id AS viewer_read_by_user_id
                    FROM notification_events n
                    LEFT JOIN notification_event_reads r
                        ON r.event_id = n.id
                        AND r.user_id = ?
                    WHERE {where}
                    ORDER BY n.created_at DESC, n.id DESC
                    """,
                    values,
                ).fetchall()
                return [notification_from_row(row) for row in rows]
            rows = connection.execute(
                f"""
                SELECT
                    n.*,
                    NULL AS viewer_read_at,
                    NULL AS viewer_read_by_user_id
                FROM notification_events n
                WHERE {where}
                ORDER BY n.created_at DESC, n.id DESC
                """,
                values,
            ).fetchall()
        return [notification_from_row(row) for row in rows]

    def unread_notification_count(
        self,
        *,
        household_id: int | None = None,
        budget_month_id: int | None = None,
        user_id: int | None = None,
    ) -> int:
        if household_id is None and budget_month_id is None:
            raise ValueError("household_id or budget_month_id is required")
        if user_id is None:
            raise ValueError("user_id is required for unread notification counts")
        clauses: list[str] = ["r.event_id IS NULL"]
        values: list[Any] = []
        if household_id is not None:
            clauses.append("n.household_id = ?")
            values.append(household_id)
        if budget_month_id is not None:
            clauses.append("n.budget_month_id = ?")
            values.append(budget_month_id)
        with self.connect() as connection:
            self._validate_user_for_notification_scope(
                connection,
                user_id=user_id,
                household_id=household_id,
                budget_month_id=budget_month_id,
            )
            values = [user_id] + values
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM notification_events n
                LEFT JOIN notification_event_reads r
                    ON r.event_id = n.id
                    AND r.user_id = ?
                WHERE {' AND '.join(clauses)}
                """,
                values,
            ).fetchone()
        return int(row["count"])

    def mark_notification_read(self, event_id: int, user_id: int) -> None:
        with self.connect() as connection:
            event = self._require_notification_event(connection, event_id)
            self._validate_user_for_household(connection, int(event["household_id"]), user_id)
            connection.execute(
                """
                INSERT INTO notification_event_reads(event_id, user_id)
                VALUES (?, ?)
                ON CONFLICT(event_id, user_id) DO NOTHING
                """,
                (event_id, user_id),
            )

    def mark_all_notifications_read(
        self,
        *,
        household_id: int | None = None,
        budget_month_id: int | None = None,
        user_id: int,
    ) -> None:
        if household_id is None and budget_month_id is None:
            raise ValueError("household_id or budget_month_id is required")
        clauses: list[str] = []
        values: list[Any] = []
        if household_id is not None:
            clauses.append("household_id = ?")
            values.append(household_id)
        if budget_month_id is not None:
            clauses.append("budget_month_id = ?")
            values.append(budget_month_id)
        with self.connect() as connection:
            self._validate_user_for_notification_scope(
                connection,
                user_id=user_id,
                household_id=household_id,
                budget_month_id=budget_month_id,
            )
            connection.execute(
                f"""
                INSERT INTO notification_event_reads(event_id, user_id)
                SELECT id, ?
                FROM notification_events
                WHERE {' AND '.join(clauses)}
                ON CONFLICT(event_id, user_id) DO NOTHING
                """,
                [user_id] + values,
            )

    def create_merchant_rule(
        self,
        *,
        household_id: int,
        merchant_match_text: str,
        category_id: int,
        priority: int = 100,
    ) -> int:
        cleaned = merchant_match_text.strip().casefold()
        if not cleaned:
            raise ValueError("merchant_match_text is required")
        with self.connect() as connection:
            self._validate_category_for_household(connection, household_id, category_id)
            rule_id = insert_and_return_id(
                connection,
                """
                INSERT INTO merchant_category_rules(
                    household_id,
                    budget_category_id,
                    merchant_match_text,
                    priority
                )
                VALUES (?, ?, ?, ?)
                """,
                (household_id, category_id, cleaned, priority),
            )
            return rule_id

    def update_plaid_item_cursor(self, plaid_item_id: int, sync_cursor: str | None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE plaid_items
                SET sync_cursor = ?, status = 'connected', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (sync_cursor, plaid_item_id),
            )

    def record_plaid_sync_error(
        self,
        *,
        plaid_item_id: int,
        sync_type: str,
        error_code: str | None,
        error_message: str,
    ) -> int:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE plaid_items
                SET
                    status = 'error',
                    last_error_code = ?,
                    last_error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error_code, error_message, plaid_item_id),
            )
            return insert_and_return_id(
                connection,
                """
                INSERT INTO plaid_sync_errors(
                    plaid_item_id,
                    sync_type,
                    error_code,
                    error_message
                )
                VALUES (?, ?, ?, ?)
                """,
                (plaid_item_id, sync_type, error_code, error_message),
            )

    def list_plaid_sync_errors(self, plaid_item_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM plaid_sync_errors
                WHERE plaid_item_id = ?
                ORDER BY occurred_at, id
                """,
                (plaid_item_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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
        actor_user_id: int | None = None,
    ) -> int:
        with self.connect() as connection:
            context = self._notification_context_for_budget_group(connection, budget_group_id)
            category_id = insert_and_return_id(
                connection,
                """
                INSERT INTO budget_categories(budget_group_id, name, planned_cents, display_order)
                VALUES (?, ?, ?, ?)
                """,
                (budget_group_id, name, planned_cents, display_order),
            )
            self._insert_notification_event(
                connection,
                household_id=context["household_id"],
                budget_month_id=context["budget_month_id"],
                event_type="category_created",
                actor_user_id=actor_user_id,
                affected_entity_type="category",
                affected_entity_id=category_id,
                title="Category created",
                message=f"{name} was added to the budget.",
                severity="info",
                metadata={"category_id": category_id, "planned_cents": planned_cents},
            )
            return category_id

    def update_category(
        self,
        *,
        category_id: int,
        name: str | None = None,
        planned_cents: int | None = None,
        archived: bool | None = None,
        actor_user_id: int | None = None,
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
            before = self._notification_context_for_category(connection, category_id)
            connection.execute(
                f"UPDATE budget_categories SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            category_name = name if name is not None else str(before["category_name"])
            if planned_cents is not None and int(before["planned_cents"]) != planned_cents:
                self._insert_notification_event(
                    connection,
                    household_id=before["household_id"],
                    budget_month_id=before["budget_month_id"],
                    event_type="category_funding_changed",
                    actor_user_id=actor_user_id,
                    affected_entity_type="category",
                    affected_entity_id=category_id,
                    title="Category funding changed",
                    message=f"{category_name} funding changed from {before['planned_cents']} cents to {planned_cents} cents.",
                    severity="caution",
                    metadata={
                        "category_id": category_id,
                        "previous_planned_cents": int(before["planned_cents"]),
                        "planned_cents": planned_cents,
                    },
                )
            if archived is True and not bool(before["archived"]):
                self._insert_notification_event(
                    connection,
                    household_id=before["household_id"],
                    budget_month_id=before["budget_month_id"],
                    event_type="category_archived",
                    actor_user_id=actor_user_id,
                    affected_entity_type="category",
                    affected_entity_id=category_id,
                    title="Category archived",
                    message=f"{category_name} was archived.",
                    severity="important",
                    metadata={"category_id": category_id},
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
        actor_user_id: int | None = None,
    ) -> SafeToSpendResult:
        snapshot = self._load_snapshot(budget_month_id)
        category = next((item for item in snapshot["categories"] if item.id == category_id), None)
        if category is None:
            raise LookupError(f"Category {category_id} is not part of budget month {budget_month_id}")
        result = calculate_safe_to_spend(
            category=category,
            purchase_amount_cents=purchase_amount_cents,
            included_account_balance_cents=snapshot["included_account_balance_cents"],
            expected_bills=snapshot["expected_bills"],
            paydays=snapshot["paydays"],
            today=today,
            urgency=urgency,
            low_cushion_daily_cents=snapshot["budget_month"]["low_cushion_daily_cents"],
        )
        if result.warning_level in {
            WarningLevel.CAUTION,
            WarningLevel.NO,
            WarningLevel.DISCUSS_WITH_SPOUSE,
        }:
            warning = result.warning_level.value
            event_suffix = "discuss" if warning == "discuss_with_spouse" else warning
            self.create_notification_event(
                household_id=int(snapshot["budget_month"]["household_id"]),
                budget_month_id=budget_month_id,
                event_type=f"safe_to_spend_{event_suffix}",
                actor_user_id=actor_user_id,
                affected_entity_type="category",
                affected_entity_id=category_id,
                title="Safe-to-spend needs attention",
                message=f"{category.name}: {result.required_phrase}",
                severity="important" if result.warning_level == WarningLevel.NO else "caution",
                metadata={
                    "category_id": category_id,
                    "purchase_amount_cents": purchase_amount_cents,
                    "warning_level": warning,
                    "category_remaining_after_cents": result.category_remaining_after_cents,
                    "cash_after_purchase_and_bills_cents": result.cash_after_purchase_and_bills_cents,
                },
            )
        return result

    def _active_assignments(self, connection: sqlite3.Connection, transaction_id: int) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT *
            FROM transaction_category_assignments
            WHERE transaction_id = ? AND active = 1
            ORDER BY id
            """,
            (transaction_id,),
        ).fetchall()

    def _category_name(self, connection: sqlite3.Connection, category_id: int) -> str:
        row = connection.execute(
            "SELECT name FROM budget_categories WHERE id = ?",
            (category_id,),
        ).fetchone()
        return str(row["name"]) if row is not None else f"Category #{category_id}"

    def _notification_context_for_budget_group(
        self,
        connection: sqlite3.Connection,
        budget_group_id: int,
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT b.household_id, b.id AS budget_month_id
            FROM budget_groups g
            JOIN budget_months b ON b.id = g.budget_month_id
            WHERE g.id = ?
            """,
            (budget_group_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"Budget group {budget_group_id} not found")
        return dict(row)

    def _notification_context_for_category(
        self,
        connection: sqlite3.Connection,
        category_id: int,
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT
                b.household_id,
                b.id AS budget_month_id,
                c.name AS category_name,
                c.planned_cents,
                c.archived
            FROM budget_categories c
            JOIN budget_groups g ON g.id = c.budget_group_id
            JOIN budget_months b ON b.id = g.budget_month_id
            WHERE c.id = ?
            """,
            (category_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"Category {category_id} not found")
        return dict(row)

    def _notification_context_for_transaction(
        self,
        connection: sqlite3.Connection,
        transaction_id: int,
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT
                b.household_id,
                b.id AS budget_month_id,
                t.name AS transaction_name
            FROM account_transactions t
            JOIN cash_accounts a ON a.id = t.cash_account_id
            JOIN budget_months b ON b.id = a.budget_month_id
            WHERE t.id = ?
            """,
            (transaction_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"Transaction {transaction_id} not found")
        return dict(row)

    def _insert_notification_event(
        self,
        connection: sqlite3.Connection,
        *,
        household_id: int,
        budget_month_id: int | None,
        event_type: str,
        actor_user_id: int | None,
        affected_entity_type: str,
        affected_entity_id: int | None,
        title: str,
        message: str,
        severity: str,
        metadata: dict[str, object] | None = None,
    ) -> int:
        validate_notification_severity(severity)
        if actor_user_id is not None:
            self._validate_user_for_household(connection, household_id, actor_user_id)
        return insert_and_return_id(
            connection,
            """
            INSERT INTO notification_events(
                household_id,
                budget_month_id,
                event_type,
                actor_user_id,
                affected_entity_type,
                affected_entity_id,
                title,
                message,
                severity,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                household_id,
                budget_month_id,
                event_type,
                actor_user_id,
                affected_entity_type,
                affected_entity_id,
                title,
                message,
                severity,
                json_dumps(sanitize_notification_metadata(metadata or {})),
            ),
        )

    def _validate_user_for_household(
        self,
        connection: sqlite3.Connection,
        household_id: int,
        user_id: int,
    ) -> None:
        row = connection.execute(
            "SELECT id FROM users WHERE id = ? AND household_id = ?",
            (user_id, household_id),
        ).fetchone()
        if row is None:
            raise ValueError("actor_user_id must belong to the household")

    def _require_household(self, connection: sqlite3.Connection, household_id: int) -> None:
        row = connection.execute(
            "SELECT id FROM households WHERE id = ?",
            (household_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"Household {household_id} not found")

    def _require_notification_event(self, connection: sqlite3.Connection, event_id: int) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM notification_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"Notification event {event_id} not found")
        return row

    def _validate_user_for_notification_scope(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: int,
        household_id: int | None,
        budget_month_id: int | None,
    ) -> None:
        if household_id is not None:
            self._validate_user_for_household(connection, household_id, user_id)
            return
        if budget_month_id is not None:
            row = connection.execute(
                """
                SELECT household_id
                FROM budget_months
                WHERE id = ?
                """,
                (budget_month_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"Budget month {budget_month_id} not found")
            self._validate_user_for_household(connection, int(row["household_id"]), user_id)

    def _transaction_detail_from_row(self, connection: sqlite3.Connection, row: sqlite3.Row) -> TransactionDetail:
        transaction_id = int(row["id"])
        assignment_rows = connection.execute(
            """
            SELECT *
            FROM transaction_category_assignments
            WHERE transaction_id = ? AND active = 1
            ORDER BY id
            """,
            (transaction_id,),
        ).fetchall()
        event_rows = connection.execute(
            """
            SELECT *
            FROM transaction_categorization_events
            WHERE transaction_id = ?
            ORDER BY created_at, id
            """,
            (transaction_id,),
        ).fetchall()
        return TransactionDetail(
            transaction=transaction_from_row(row),
            assignments=tuple(assignment_from_row(item) for item in assignment_rows),
            audit_events=tuple(dict(item) for item in event_rows),
        )

    def _require_transaction(self, connection: sqlite3.Connection, transaction_id: int) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM account_transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"Transaction {transaction_id} not found")
        return row

    def _validate_category_for_transaction(
        self,
        connection: sqlite3.Connection,
        transaction_id: int,
        category_id: int,
    ) -> None:
        row = connection.execute(
            """
            SELECT c.id
            FROM budget_categories c
            JOIN budget_groups g ON g.id = c.budget_group_id
            JOIN cash_accounts a ON a.budget_month_id = g.budget_month_id
            JOIN account_transactions t ON t.cash_account_id = a.id
            WHERE t.id = ? AND c.id = ? AND c.archived = 0
            """,
            (transaction_id, category_id),
        ).fetchone()
        if row is None:
            raise ValueError("Category must belong to the transaction budget month and be active")

    def _validate_category_for_household(
        self,
        connection: sqlite3.Connection,
        household_id: int,
        category_id: int,
    ) -> None:
        row = connection.execute(
            """
            SELECT c.id
            FROM budget_categories c
            JOIN budget_groups g ON g.id = c.budget_group_id
            JOIN budget_months b ON b.id = g.budget_month_id
            WHERE b.household_id = ? AND c.id = ? AND c.archived = 0
            """,
            (household_id, category_id),
        ).fetchone()
        if row is None:
            raise ValueError("Category must belong to the household and be active")

    def _supersede_active_assignments(self, connection: sqlite3.Connection, transaction_id: int) -> None:
        connection.execute(
            """
            UPDATE transaction_category_assignments
            SET active = 0, superseded_at = CURRENT_TIMESTAMP
            WHERE transaction_id = ? AND active = 1
            """,
            (transaction_id,),
        )

    def _insert_assignment(
        self,
        connection: sqlite3.Connection,
        *,
        transaction_id: int,
        category_id: int,
        amount_cents: int,
        source: str,
    ) -> int:
        if amount_cents <= 0:
            raise ValueError("Assignment amount must be positive")
        return insert_and_return_id(
            connection,
            """
            INSERT INTO transaction_category_assignments(
                transaction_id,
                budget_category_id,
                amount_cents,
                source
            )
            VALUES (?, ?, ?, ?)
            """,
            (transaction_id, category_id, amount_cents, source),
        )

    def _apply_best_rule_if_allowed(self, connection: sqlite3.Connection, transaction_id: int) -> None:
        transaction = self._require_transaction(connection, transaction_id)
        if transaction["ignored"]:
            return
        active_assignments = connection.execute(
            """
            SELECT source
            FROM transaction_category_assignments
            WHERE transaction_id = ? AND active = 1
            """,
            (transaction_id,),
        ).fetchall()
        if any(row["source"] in {"manual", "split"} for row in active_assignments):
            return
        if active_assignments:
            self._supersede_active_assignments(connection, transaction_id)

        haystack = " ".join(
            value
            for value in (transaction["merchant_name"], transaction["name"])
            if value
        ).casefold()
        if not haystack:
            return

        rule_rows = connection.execute(
            """
            SELECT r.*
            FROM merchant_category_rules r
            JOIN budget_categories c ON c.id = r.budget_category_id
            JOIN budget_groups g ON g.id = c.budget_group_id
            JOIN budget_months b ON b.id = g.budget_month_id
            JOIN cash_accounts a ON a.budget_month_id = b.id
            WHERE a.id = ?
                AND r.household_id = b.household_id
                AND r.active = 1
                AND c.archived = 0
            ORDER BY r.priority, r.id
            """,
            (transaction["cash_account_id"],),
        ).fetchall()
        for rule in rule_rows:
            if rule["merchant_match_text"] in haystack:
                amount_cents = budget_amount_cents(transaction["amount_cents"])
                self._insert_assignment(
                    connection,
                    transaction_id=transaction_id,
                    category_id=int(rule["budget_category_id"]),
                    amount_cents=amount_cents,
                    source="rule",
                )
                self._record_transaction_event(
                    connection,
                    transaction_id=transaction_id,
                    event_type="rule_applied",
                    source="rule",
                    category_id=int(rule["budget_category_id"]),
                    amount_cents=amount_cents,
                    metadata={"rule_id": int(rule["id"])},
                )
                return

    def _record_transaction_event(
        self,
        connection: sqlite3.Connection,
        *,
        transaction_id: int,
        event_type: str,
        source: str | None = None,
        category_id: int | None = None,
        amount_cents: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> int:
        return insert_and_return_id(
            connection,
            """
            INSERT INTO transaction_categorization_events(
                transaction_id,
                event_type,
                source,
                budget_category_id,
                amount_cents,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                event_type,
                source,
                category_id,
                amount_cents,
                json_dumps(metadata) if metadata is not None else None,
            ),
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
                    COALESCE(ms.manual_spent_cents, 0) + COALESCE(ts.transaction_spent_cents, 0) AS spent_cents
                FROM budget_categories c
                JOIN budget_groups g ON g.id = c.budget_group_id
                LEFT JOIN (
                    SELECT budget_category_id, SUM(amount_cents) AS manual_spent_cents
                    FROM manual_spending
                    GROUP BY budget_category_id
                ) ms ON ms.budget_category_id = c.id
                LEFT JOIN (
                    SELECT a.budget_category_id, SUM(a.amount_cents) AS transaction_spent_cents
                    FROM transaction_category_assignments a
                    JOIN account_transactions t ON t.id = a.transaction_id
                    JOIN cash_accounts ca ON ca.id = t.cash_account_id
                    WHERE a.active = 1
                        AND t.ignored = 0
                        AND ca.budget_month_id = ?
                    GROUP BY a.budget_category_id
                ) ts ON ts.budget_category_id = c.id
                WHERE g.budget_month_id = ?
                ORDER BY g.display_order, c.display_order, c.id
                """,
                (budget_month_id, budget_month_id),
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


def ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def normalize_login(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().casefold()
    return cleaned or None


def require_login_value(value: str | None, field_name: str) -> str:
    cleaned = normalize_login(value)
    if cleaned is None:
        raise ValueError(f"{field_name} is required")
    return cleaned


def safe_user_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "household_id": int(row["household_id"]),
        "name": row["name"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
    }


def safe_household_from_user_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["household_id"]),
        "name": row["household_name"],
    }


def budget_amount_cents(transaction_amount_cents: int) -> int:
    return abs(transaction_amount_cents)


def json_dumps(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True)


def validate_account_type(account_type: str) -> None:
    if account_type not in {"checking", "savings"}:
        raise ValueError("Only checking and savings accounts are supported")


def account_from_row(row: sqlite3.Row) -> AccountLine:
    return AccountLine(
        id=row["id"],
        budget_month_id=row["budget_month_id"],
        name=row["name"],
        account_type=row["account_type"],
        balance_cents=row["balance_cents"],
        included_in_cash_reality=bool(row["included_in_cash_reality"]),
        plaid_item_id=row["plaid_item_id"],
        plaid_account_id=row["plaid_account_id"],
        mask=row["mask"],
        official_name=row["official_name"],
        subtype=row["subtype"],
        available_balance_cents=row["available_balance_cents"],
        current_balance_cents=row["current_balance_cents"],
    )


def plaid_item_from_row(row: sqlite3.Row) -> PlaidItemLine:
    return PlaidItemLine(
        id=row["id"],
        household_id=row["household_id"],
        plaid_item_id=row["plaid_item_id"],
        access_token_ref=row["access_token_ref"],
        institution_id=row["institution_id"],
        institution_name=row["institution_name"],
        sync_cursor=row["sync_cursor"],
        status=row["status"],
        last_error_code=row["last_error_code"],
        last_error_message=row["last_error_message"],
    )


def transaction_from_row(row: sqlite3.Row) -> TransactionLine:
    return TransactionLine(
        id=row["id"],
        cash_account_id=row["cash_account_id"],
        plaid_transaction_id=row["plaid_transaction_id"],
        amount_cents=row["amount_cents"],
        occurred_on=date.fromisoformat(row["occurred_on"]),
        name=row["name"],
        merchant_name=row["merchant_name"],
        pending=bool(row["pending"]),
        category_hint=row["category_hint"],
        reviewed=bool(row["reviewed"]),
        ignored=bool(row["ignored"]),
        ignored_reason=row["ignored_reason"],
    )


def assignment_from_row(row: sqlite3.Row) -> TransactionCategoryAssignment:
    return TransactionCategoryAssignment(
        id=row["id"],
        transaction_id=row["transaction_id"],
        category_id=row["budget_category_id"],
        amount_cents=row["amount_cents"],
        source=row["source"],
        active=bool(row["active"]),
    )


def notification_from_row(row: sqlite3.Row) -> NotificationEvent:
    return NotificationEvent(
        id=row["id"],
        household_id=row["household_id"],
        budget_month_id=row["budget_month_id"],
        event_type=row["event_type"],
        actor_user_id=row["actor_user_id"],
        affected_entity_type=row["affected_entity_type"],
        affected_entity_id=row["affected_entity_id"],
        title=row["title"],
        message=row["message"],
        severity=row["severity"],
        metadata=sanitize_notification_metadata(json.loads(row["metadata"] or "{}")),
        read_at=row["viewer_read_at"],
        read_by_user_id=row["viewer_read_by_user_id"],
        created_at=row["created_at"],
    )


def summary_to_dict(summary: BudgetSummary) -> dict[str, Any]:
    payload = asdict(summary)
    payload["next_payday"] = summary.next_payday.isoformat()
    payload["categories"] = [asdict(category) | {"remaining_cents": category.remaining_cents} for category in summary.categories]
    return payload


def account_to_dict(account: AccountLine) -> dict[str, Any]:
    return asdict(account)


def plaid_item_to_public_dict(item: PlaidItemLine) -> dict[str, Any]:
    return {
        "id": item.id,
        "household_id": item.household_id,
        "plaid_item_id": item.plaid_item_id,
        "institution_id": item.institution_id,
        "institution_name": item.institution_name,
        "status": item.status,
        "last_error_code": item.last_error_code,
        "last_error_message": item.last_error_message,
    }


def transaction_to_dict(transaction: TransactionLine) -> dict[str, Any]:
    payload = asdict(transaction)
    payload["occurred_on"] = transaction.occurred_on.isoformat()
    return payload


def assignment_to_dict(assignment: TransactionCategoryAssignment) -> dict[str, Any]:
    return asdict(assignment)


def transaction_detail_to_dict(detail: TransactionDetail) -> dict[str, Any]:
    return {
        "transaction": transaction_to_dict(detail.transaction),
        "assignments": [assignment_to_dict(assignment) for assignment in detail.assignments],
        "audit_events": [dict(event) for event in detail.audit_events],
        "final_category_id": detail.final_category_id,
        "categorization_status": detail.categorization_status,
        "needs_review": detail.needs_review,
    }


def safe_to_spend_to_dict(result: SafeToSpendResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["warning_level"] = result.warning_level.value
    payload["next_payday"] = result.next_payday.isoformat()
    return payload


def notification_event_to_dict(event: NotificationEvent) -> dict[str, Any]:
    return asdict(event) | {"metadata": sanitize_notification_metadata(event.metadata)}


def validate_notification_severity(severity: str) -> None:
    if severity not in {"info", "caution", "important"}:
        raise ValueError("severity must be info, caution, or important")


def sanitize_notification_metadata(metadata: dict[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key, value in metadata.items():
        key_text = str(key)
        if is_forbidden_metadata_text(key_text):
            continue
        sanitized[key_text] = sanitize_notification_metadata_value(value)
    return sanitized


def sanitize_notification_metadata_value(value: object) -> object:
    if isinstance(value, dict):
        return sanitize_notification_metadata(value)
    if isinstance(value, list):
        return [sanitize_notification_metadata_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_notification_metadata_value(item) for item in value]
    if isinstance(value, str) and is_forbidden_metadata_text(value):
        return "[redacted]"
    return value


def is_forbidden_metadata_text(value: str) -> bool:
    lowered = value.casefold()
    return any(term in lowered for term in FORBIDDEN_METADATA_TERMS)
