"""A closed, in-process fictional bank using the ordinary import/readiness pipeline.

There is deliberately no provider factory, environment lookup or network transport
here. A demo context must explicitly inject this service; production never selects
it from an Android flag. The database remains disposable and isolated by its owner.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .db import account_to_dict, plaid_item_to_public_dict
from .live_plaid import LivePlaidService
from .plaid import (PlaidAccountSnapshot, PlaidConnectionResult, PlaidIntegrationError,
                    PlaidLinkToken, PlaidSyncOutcome, PlaidTransactionSync)


class DemoBankClient:
    """Two deterministic statements: the ready seed and one new batch on Sync."""

    def __init__(self, transactions, new_transactions):
        self.transactions = tuple(transactions)
        self.new_transactions = tuple(new_transactions)
        self.new_activity_available = False
        self.balances = {"demo-spending": 130_000, "demo-bills": 220_000, "demo-savings": 650_000}
        # Balance = opening balance plus imported activity, including transfers.
        self.opening_balances = {
            key: balance - sum(t.amount_cents for t in self.transactions if t.plaid_account_id == key)
            for key, balance in self.balances.items()
        }

    def accounts(self, token, *, fresh):
        activity = self.transactions + (self.new_transactions if self.new_activity_available else ())
        names = (("demo-spending", "Everyday Checking", "checking", "1001", True),
                 ("demo-bills", "Bills Checking", "checking", "1002", True),
                 ("demo-savings", "Emergency Savings", "savings", "1003", False))
        result = []
        for key, name, kind, mask, included in names:
            balance = self.opening_balances[key] + sum(t.amount_cents for t in activity if t.plaid_account_id == key)
            result.append(PlaidAccountSnapshot(key, name, kind, balance, subtype=kind, mask=mask,
                available_balance_cents=balance, current_balance_cents=balance,
                included_in_cash_reality=included))
        return tuple(result)

    def sync_transactions(self, token, cursor):
        if cursor not in (None, "demo-seed-v1", "demo-import-v1"):
            raise PlaidIntegrationError("Demo bank history could not be read.", "PLAID_SYNC_INVALID")
        rows = self.transactions if cursor is None else ()
        if self.new_activity_available and cursor != "demo-import-v1":
            rows += self.new_transactions
        next_cursor = "demo-import-v1" if self.new_activity_available else "demo-seed-v1"
        return PlaidTransactionSync(rows, next_cursor), True

    def _request(self, path, payload):
        if path == "/item/get":
            return {"item": {"error": None}, "status": {"transactions": {
                "last_successful_update": datetime.now(timezone.utc).isoformat()}}}
        if path == "/transactions/refresh":
            return {"request_id": "demo-refresh"}
        raise PlaidIntegrationError("This operation is unavailable in the simulated bank.")


class DemoBankService(LivePlaidService):
    """Reuse live transaction importing, refresh claims and failure protections.

Override the only balance path that otherwise identifies the real institution.
The required injected client has no network capability, including its private
request method used by the shared transaction and refresh implementations.
"""

    def __init__(self, repository, client: DemoBankClient):
        if type(client) is not DemoBankClient:
            raise TypeError("Demo bank requires its simulated client")
        super().__init__(repository, client)

    def create_link_token(self, household_id):
        if not self.repository.list_plaid_items(household_id):
            raise LookupError("Demo bank connection not found")
        return PlaidLinkToken("demo-bank-link", (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(), "demo-link")

    def exchange_public_token(self, *, household_id, budget_month_id, public_token):
        self.repository.require_budget_month_access(budget_month_id, household_id)
        if public_token != "demo-bank-confirmed":
            raise PlaidIntegrationError("Use the simulated demo bank connection.", "PUBLIC_TOKEN_REQUIRED")
        items = self.repository.list_plaid_items(household_id)
        if len(items) != 1:
            raise LookupError("Demo bank connection not found")
        item_id = items[0].id
        with self.lock, self.repository.connect() as connection:
            connection.execute("UPDATE plaid_items SET status='connected',last_error_code=NULL,last_error_message=NULL WHERE id=?", (item_id,))
        return PlaidConnectionResult(plaid_item_to_public_dict(self.repository.get_plaid_item(item_id)),
            tuple(account_to_dict(a) for a in self.repository.list_accounts(budget_month_id)))

    def sync_balances(self, plaid_item_id):
        with self.lock:
            try:
                with self.repository.connect() as connection:
                    connection.execute("UPDATE bank_sync_state SET balance_error=1 WHERE plaid_item_id=?", (plaid_item_id,))
                item = self.repository.get_plaid_item(plaid_item_id)
                token = self.token_store.retrieve(item.access_token_ref)
                snapshots = self.client.accounts(token, fresh=True)
                with self.repository.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    month = connection.execute("SELECT active_budget_month_id FROM households WHERE id=?", (item.household_id,)).fetchone()[0]
                    known = {r["plaid_account_id"]: r for r in connection.execute("SELECT * FROM cash_accounts WHERE plaid_item_id=?", (plaid_item_id,))}
                    for snapshot in snapshots:
                        self.repository.upsert_connected_account(budget_month_id=known[snapshot.plaid_account_id]["budget_month_id"] if snapshot.plaid_account_id in known else month,
                            plaid_item_id=plaid_item_id, **asdict(snapshot), _connection=connection)
                    returned = {a.plaid_account_id for a in snapshots}
                    if returned != set(known):
                        connection.execute("UPDATE bank_sync_state SET reconciled_at=NULL WHERE plaid_item_id=?", (plaid_item_id,))
                    for key, row in known.items():
                        if key not in returned:
                            connection.execute("UPDATE cash_accounts SET last_balance_synced_at=NULL WHERE id=?", (row["id"],))
                    connection.execute("UPDATE cash_accounts SET last_balance_synced_at=CURRENT_TIMESTAMP WHERE plaid_item_id=? AND plaid_account_id IN (" + ",".join("?" for _ in returned) + ")", (plaid_item_id, *returned))
                    connection.execute("UPDATE bank_sync_state SET balance_checked_at=CURRENT_TIMESTAMP,balance_error=0 WHERE plaid_item_id=?", (plaid_item_id,))
                return PlaidSyncOutcome(True, "balance", synced_accounts=len(snapshots))
            except Exception as exc:
                return self._failure(plaid_item_id, "balance", exc)
