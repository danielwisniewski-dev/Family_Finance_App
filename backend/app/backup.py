"""Encrypted consistent SQLite snapshots; restoration only to a NEW database path."""
from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing

from .migrations import LATEST_VERSION
from .security import SecretBox

MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_BACKUP_STORAGE_BYTES = 224 * 1024 * 1024
HEADER = b"FAMILY-FINANCE-BACKUP-1\n"


def check_database(connection):
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("Database integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RuntimeError("Database contains invalid references")
    if connection.execute("PRAGMA user_version").fetchone()[0] > LATEST_VERSION:
        raise RuntimeError("Database requires a newer app version")
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"households", "users", "budget_months", "auth_sessions"}.issubset(tables):
        raise RuntimeError("File is not a supported household database")


def write_new_file(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects against replacing a symlink or existing database.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def create_backup(db_path: Path, destination: Path, key: str) -> Path:
    cipher = SecretBox(key, "database-backups")
    # mode=ro never creates a missing source. The backup API captures concurrent writes/WAL consistently.
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        size = source.execute("PRAGMA page_count").fetchone()[0] * source.execute("PRAGMA page_size").fetchone()[0]
        if size > MAX_DATABASE_BYTES:
            raise RuntimeError("Database exceeds the 64 MiB stage 1 backup limit")
        target = sqlite3.connect(":memory:")
        try:
            source.backup(target)
            check_database(target)
            serialized = bytearray(target.serialize())
            # The backup API already folded committed WAL pages into this snapshot.
            # SQLite deserialize requires rollback-mode header bytes even for an in-memory snapshot:
            # https://sqlite.org/c3ref/deserialize.html
            serialized[18:20] = b"\x01\x01"
            encrypted = HEADER + cipher.encrypt(bytes(serialized))
        finally:
            target.close()
    write_new_file(destination, encrypted)
    return destination


def restore_backup(source: Path, destination: Path, key: str) -> Path:
    if source.stat().st_size > MAX_DATABASE_BYTES * 2:
        raise RuntimeError("Backup exceeds the supported size")
    encrypted = source.read_bytes()
    if not encrypted.startswith(HEADER):
        raise ValueError("Unrecognized encrypted backup format")
    plaintext = SecretBox(key, "database-backups").decrypt(encrypted[len(HEADER):])
    if len(plaintext) > MAX_DATABASE_BYTES:
        raise RuntimeError("Restored database exceeds the supported size")
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(plaintext)
        check_database(connection)
        # Old sessions must never be resurrected by recovery.
        connection.execute("DELETE FROM auth_sessions")
        connection.commit()
        write_new_file(destination, connection.serialize())
    finally:
        connection.close()
    return destination


class BackupScheduler:
    def __init__(self, db_path: Path, directory: Path, key: str, interval: int = 3600):
        self.db_path, self.directory, self.key, self.interval = db_path, directory, key, interval
        self.stop_event = threading.Event()
        self.last_success = 0.0
        self.failed = False

    def snapshot(self):
        name = "backup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex + ".ffbackup"
        path = create_backup(self.db_path, self.directory / name, self.key)
        # Authenticate and validate a restore before considering a backup successful.
        with tempfile.TemporaryDirectory() as temporary:
            restore_backup(path, Path(temporary) / "verify.sqlite", self.key)
        self.last_success, self.failed = time.time(), False
        stored_bytes = 0
        snapshots = sorted((p for p in self.directory.glob("backup-*.ffbackup") if p.is_file() and not p.is_symlink()),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        for index, old in enumerate(snapshots):
            size = old.stat().st_size
            if index >= 2 and (old.stat().st_mtime < time.time() - 7 * 86400 or stored_bytes + size > MAX_BACKUP_STORAGE_BYTES):
                old.unlink()
            else:
                stored_bytes += size
        return path

    def healthy(self):
        return not self.failed and time.time() - self.last_success < self.interval * 2

    def start(self):
        self.snapshot()  # Refuse to serve if the initial restore check fails.
        def run():
            while not self.stop_event.wait(self.interval):
                try:
                    self.snapshot()
                except Exception:
                    self.failed = True
                    # Never log the exception: filenames/provider responses may contain private data.
                    print("Encrypted database backup failed; operator attention required", flush=True)
        thread = threading.Thread(target=run, name="database-backups", daemon=True)
        thread.start()
        return thread


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "restore"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        key = os.environ.get("FF_ENCRYPTION_KEY", "")
        operation = create_backup if args.action == "create" else restore_backup
        operation(args.source, args.destination, key)
    except Exception:
        parser.exit(1, "Backup operation failed. Check the key, file paths, database version, and integrity. Existing files were not overwritten.\n")
    print("Backup operation completed; existing files were not overwritten.")


if __name__ == "__main__":
    main()
