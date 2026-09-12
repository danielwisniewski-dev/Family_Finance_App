"""Ordered, atomic SQLite upgrades for the known local MVP schema and later releases."""
from __future__ import annotations

import sqlite3
from pathlib import Path

LATEST_VERSION = 3


def add_column(connection, table, column, definition):
    if column not in {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def baseline(connection):
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
        add_column(connection, "users", "username", "TEXT")
    # executescript implicitly commits, so execute complete statements individually.
    statement = ""
    for line in Path(__file__).with_name("schema.sql").read_text(encoding="utf-8").splitlines(True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    for table, column, definition in [
        ("users", "password_hash", "TEXT"), ("households", "active_budget_month_id", "INTEGER"),
        ("budget_groups", "archived", "INTEGER NOT NULL DEFAULT 0"),
        ("account_transactions", "reviewed", "INTEGER NOT NULL DEFAULT 0"),
        ("account_transactions", "ignored", "INTEGER NOT NULL DEFAULT 0"),
        ("account_transactions", "ignored_reason", "TEXT"), ("merchant_category_rules", "updated_at", "TEXT"),
    ]:
        add_column(connection, table, column, definition)


def private_sessions(connection):
    add_column(connection, "auth_sessions", "expires_at", "INTEGER")
    # Legacy tokens had no expiry. Require a fresh login instead of extending them.
    connection.execute("DELETE FROM auth_sessions WHERE expires_at IS NULL")
    connection.execute("CREATE INDEX IF NOT EXISTS auth_session_expiry ON auth_sessions(expires_at)")
    connection.execute("""CREATE TABLE IF NOT EXISTS auth_attempts (
        bucket TEXT PRIMARY KEY, attempts INTEGER NOT NULL, resets_at INTEGER NOT NULL)""")
    connection.execute("CREATE TABLE IF NOT EXISTS app_secret_checks (name TEXT PRIMARY KEY, sealed_value TEXT NOT NULL)")


def live_bank_data(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS bank_sync_state (
        plaid_item_id INTEGER PRIMARY KEY REFERENCES plaid_items(id),
        environment TEXT NOT NULL CHECK(environment = 'production'),
        balance_checked_at TEXT, transactions_checked_at TEXT,
        transactions_updated_at TEXT, history_complete INTEGER NOT NULL DEFAULT 0,
        reconciled_at TEXT, reconciled_month TEXT,
        balance_error INTEGER NOT NULL DEFAULT 1, transaction_error INTEGER NOT NULL DEFAULT 1)""")
    # Keep the original account and transaction IDs. Account ownership is household-wide;
    # a bank transaction's date determines its budget month, even across a posting change.
    connection.execute("""CREATE VIEW IF NOT EXISTS transaction_budget_months AS
        SELECT t.id AS transaction_id, b.id AS budget_month_id
        FROM account_transactions t JOIN cash_accounts a ON a.id = t.cash_account_id
        JOIN budget_months anchor ON anchor.id = a.budget_month_id
        JOIN budget_months b ON b.household_id = anchor.household_id
            AND ((a.plaid_item_id IS NOT NULL AND b.month = substr(t.occurred_on, 1, 7))
                 OR (a.plaid_item_id IS NULL AND b.id = anchor.id))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS transaction_refunds (
        transaction_id INTEGER PRIMARY KEY REFERENCES account_transactions(id),
        budget_category_id INTEGER NOT NULL REFERENCES budget_categories(id),
        amount_cents INTEGER NOT NULL CHECK(amount_cents > 0))""")


MIGRATIONS = [(1, "local_mvp_baseline", baseline), (2, "expiring_sessions_and_throttling", private_sessions),
              (3, "live_bank_sync_and_months", live_bank_data)]


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > LATEST_VERSION:
            raise RuntimeError("Database was created by a newer app version; refusing downgrade")
        connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        applied = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
        if applied != list(range(1, version + 1)):
            raise RuntimeError("Database migration history is inconsistent")
        for number, name, apply in MIGRATIONS:
            if number > version:
                apply(connection)
                connection.execute("INSERT INTO schema_migrations(version,name) VALUES (?,?)", (number, name))
                connection.execute(f"PRAGMA user_version = {number}")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("Database has invalid references; migration rolled back")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
