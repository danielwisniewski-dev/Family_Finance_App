"""Private-beta smoke against the actual production HTTP stack, using synthetic data only."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import date
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from waitress import create_server
from backend.app.backup import BackupScheduler, restore_backup
from backend.app.db import BudgetRepository
from backend.app.hosted import Application
from backend.app.security import RuntimeSettings


@contextmanager
def server_for(path, settings):
    repo = BudgetRepository(path, settings)
    repo.initialize()
    backups = BackupScheduler(path, path.parent / "backups", settings.encryption_key)
    backups.snapshot()
    server = create_server(Application(repo, backups), host="127.0.0.1", port=0, threads=4,
                           max_request_body_size=262144, expose_tracebacks=False)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        yield int(server.effective_port), repo, backups
    finally:
        server.task_dispatcher.shutdown()
        server.close()
        thread.join(timeout=5)


def run():
    settings = RuntimeSettings(hosted=True, setup_code="synthetic-setup-smoke-" * 3,
                               encryption_key="synthetic-backup-smoke-" * 3)
    def call(method, path, data=None, token=None, expected=200):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        connection = HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=headers)
            response = connection.getresponse()
            body = response.read()
            assert response.status == expected, (method, path, response.status, expected)
            assert response.getheader("Cache-Control") == "no-store"
            for secret in [settings.setup_code, settings.encryption_key, "password_hash", "token_hash", "access_token_ref"]:
                assert secret.encode() not in body
            return json.loads(body)
        finally:
            connection.close()

    with tempfile.TemporaryDirectory(prefix="family-finance-stage1-") as temporary:
        path = Path(temporary) / "synthetic.sqlite"
        with server_for(path, settings) as (port, repo, backups):
            assert call("GET", "/ready")["ok"]
            call("GET", "/budget-months", expected=401)
            users = [{"name": "Daniel", "username": "daniel", "password": "synthetic-daniel-password"},
                     {"name": "Kara", "username": "kara", "password": "synthetic-kara-password"}]
            setup = {"household_name": "Synthetic beta", "users": users}
            call("POST", "/setup/initialize", setup, expected=403)
            call("POST", "/setup/initialize", {**setup, "setup_code": settings.setup_code}, expected=201)
            first = call("POST", "/auth/login", {"username": "daniel", "password": users[0]["password"]})
            second = call("POST", "/auth/login", {"username": "kara", "password": users[1]["password"]})
            daniel, kara = first["token"], second["token"]
            assert first["household"] == second["household"]
            household = first["household"]["id"]
            month = call("POST", "/budget-months", {"household_id": household, "month": "2026-09",
                "included_account_balance_cents": 100000}, daniel, 201)["id"]
            group = call("POST", "/budget-groups", {"budget_month_id": month, "name": "Food"}, daniel, 201)["id"]
            category = call("POST", "/categories", {"budget_group_id": group, "name": "Groceries", "planned_cents": 20000}, daniel, 201)["id"]
            call("POST", "/paydays", {"household_id": household, "payday_date": "2026-09-16"}, daniel, 201)
            call("POST", "/expected-bills", {"budget_month_id": month, "name": "Electric", "amount_cents": 10000, "due_on": "2026-09-14"}, daniel, 201)
            call("POST", "/spending", {"category_id": category, "amount_cents": 1234, "occurred_on": "2026-09-11"}, kara, 201)
            summary_path = f"/budget-months/{month}/summary?today=2026-09-11"
            shared = call("GET", summary_path, token=daniel)
            assert shared["total_spent_cents"] == 1234
            assert shared == call("GET", summary_path, token=kara)
            result = call("POST", "/safe-to-spend", {"budget_month_id": month, "category_id": category,
                "purchase_amount_cents": 2000, "today": "2026-09-11"}, kara)
            assert result["cash_after_purchase_and_bills_cents"] == 88000
            assert "$880.00 left for 5 days until payday." in result["required_phrase"]
            call("POST", "/plaid/link-token", {}, daniel, 403)
            call("POST", "/auth/logout", {}, daniel)
            call("GET", summary_path, token=daniel, expected=401)
            snapshot = backups.snapshot()
        with server_for(path, settings) as (port, repo, backups):
            assert shared == call("GET", summary_path, token=kara)
        restored = restore_backup(snapshot, Path(temporary) / "recovered.sqlite", settings.encryption_key)
        with server_for(restored, settings) as (port, repo, backups):
            call("GET", summary_path, token=kara, expected=401)
            fresh = call("POST", "/auth/login", {"username": "kara", "password": users[1]["password"]})["token"]
            assert shared == call("GET", summary_path, token=fresh)
    print("Stage 1 smoke passed: protected setup, two-user shared totals, safe-to-spend, logout, restart, encrypted restore, and fresh login after recovery.")


def main():
    with patch.dict(os.environ, {"FF_MODE": "local", "COACH_PROVIDER": "mock", "PLAID_ENV": "sandbox",
                                 "PLAID_CLIENT_ID": "", "PLAID_SECRET": "", "OPENAI_API_KEY": ""}):
        run()


if __name__ == "__main__":
    main()
