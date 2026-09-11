"""Upgrade a stopped legacy database into a NEW file, preserving an encrypted recovery copy."""
from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .backup import create_backup, restore_backup, check_database
from .db import BudgetRepository
from .migrations import migrate
from .security import RuntimeSettings, SecretBox


def upgrade_copy(source: Path, destination: Path, backup: Path, key: str):
    if destination.exists():
        raise FileExistsError("Upgrade destination must be a new database path")
    box = SecretBox(key, "plaid-tokens")
    create_backup(source, backup, key)
    restore_backup(backup, destination, key)
    with closing(sqlite3.connect(destination)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        migrate(connection)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for reference, value in connection.execute("SELECT token_ref,access_token FROM plaid_access_tokens").fetchall():
                if value.startswith(box.PREFIX):
                    box.open(value)
                else:
                    connection.execute("UPDATE plaid_access_tokens SET access_token=? WHERE token_ref=?", (box.seal(value), reference))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        connection.execute("VACUUM")
        check_database(connection)
    BudgetRepository(destination, RuntimeSettings(encryption_key=key)).initialize()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    try:
        upgrade_copy(args.source, args.destination, args.backup, os.environ.get("FF_ENCRYPTION_KEY", ""))
    except Exception:
        parser.exit(1, "Upgrade failed. Original database preserved. Do not serve the destination; inspect configuration and use the recovery backup.\n")
    print("Upgrade completed in the new database. Original preserved; old sessions revoked and stored tokens encrypted.")


if __name__ == "__main__":
    main()
