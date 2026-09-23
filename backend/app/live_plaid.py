"""Opt-in private USAA connection. Secrets and provider payloads stay on the server."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .db import account_to_dict
from .bank_refresh import BankRefreshMixin, mark_refresh_checked
from .plaid import (DatabasePlaidTokenStore, PlaidConnectionService, PlaidConnectionResult,
                    PlaidIntegrationError, PlaidLinkToken, PlaidSandboxClient, PlaidSyncOutcome,
                    PlaidTransactionSync, account_from_plaid_json, transaction_from_plaid_json)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LivePlaidClient(PlaidSandboxClient):
    def _request(self, path, payload):
        # Only the factory behind RuntimeSettings may construct the live client.
        if self.settings.environment != "production" or not self.settings.secret or not self.settings.client_id:
            raise PlaidIntegrationError("Bank connection is not configured", "PLAID_CONFIG_MISSING")
        request = Request("https://production.plaid.com" + path,
                          data=json.dumps({"client_id": self.settings.client_id,
                                           "secret": self.settings.secret, **payload}).encode(),
                          headers={"Content-Type": "application/json", "Plaid-Version": "2020-09-14"}, method="POST")
        try:
            with build_opener(NoRedirects()).open(request, timeout=90 if path == "/transactions/refresh" else 35) as response:
                return json.loads(response.read().decode())
        except HTTPError as exc:
            code = "PLAID_REQUEST_FAILED"
            try:
                candidate = json.loads(exc.read()).get("error_code")
                if candidate in {"ITEM_LOGIN_REQUIRED", "ITEM_LOCKED", "ITEM_NOT_SUPPORTED",
                                 "INSTITUTION_DOWN", "INSTITUTION_NOT_RESPONDING", "PRODUCT_NOT_READY",
                                 "SYNC_UPDATES_DURING_PAGINATION", "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION",
                                 "RATE_LIMIT_EXCEEDED", "TRANSACTIONS_REFRESH_LIMIT", "PRODUCT_NOT_ENABLED",
                                 "INVALID_PRODUCT", "USER_PERMISSION_REVOKED", "ADDITIONAL_CONSENT_REQUIRED"}:
                    code = candidate
            except (ValueError, TypeError, AttributeError):
                pass
            message = ("USAA authorization needs attention. Reconnect USAA in Settings."
                       if code in {"ITEM_LOGIN_REQUIRED", "ITEM_LOCKED", "USER_PERMISSION_REVOKED", "ADDITIONAL_CONSENT_REQUIRED"}
                       else "Bank request failed. Try again later.")
            raise PlaidIntegrationError(message, code) from None
        except (URLError, TimeoutError, OSError):
            raise PlaidIntegrationError("Bank connection could not be reached. Retry later.", "PLAID_NETWORK_ERROR") from None
        except (ValueError, TypeError, KeyError):
            raise PlaidIntegrationError("Bank response could not be read. Retry later.", "PLAID_RESPONSE_ERROR") from None

    def link_token(self, household_id, access_token=None):
        payload = {"client_name": "Family Finance", "country_codes": ["US"], "language": "en",
                   "user": {"client_user_id": f"household-{household_id}"},
                   "android_package_name": self.ANDROID_PACKAGE_NAME}
        if access_token:
            payload["access_token"] = access_token
        else:
            payload["products"] = ["transactions"]
            payload["account_filters"] = {"depository": {"account_subtypes": ["checking", "savings"]}}
        result = self._request("/link/token/create", payload)
        return PlaidLinkToken(result["link_token"], result["expiration"], "")

    def accounts(self, token, *, fresh):
        payload = self._request("/accounts/balance/get" if fresh else "/accounts/get", {"access_token": token})
        item = payload.get("item") or {}
        if item.get("institution_id") != os.environ["PLAID_USAA_INSTITUTION_ID"]:
            raise PlaidIntegrationError("This private beta supports the configured USAA institution only.", "INSTITUTION_MISMATCH")
        accounts = []
        for raw in payload.get("accounts", []):
            if raw.get("type") != "depository" or raw.get("subtype") not in {"checking", "savings"}:
                continue
            balance = raw.get("balances") or {}
            if (balance.get("iso_currency_code") != "USD" or balance.get("unofficial_currency_code")
                    or (balance.get("available") is None and balance.get("current") is None)):
                raise PlaidIntegrationError("An account has an unavailable USD balance. Retry later.", "BALANCE_UNAVAILABLE")
            accounts.append(account_from_plaid_json(raw))
        if not accounts:
            raise PlaidIntegrationError("No supported USAA checking or savings accounts were returned.", "ACCOUNTS_UNAVAILABLE")
        return tuple(accounts)

    def sync_transactions(self, access_token, cursor):
        # Pagination restarts from the ORIGINAL cursor on bank-side mutation.
        for attempt in range(3):
            added, modified, removed = [], [], []
            next_cursor = cursor
            try:
                for page in range(1000):
                    payload = {"access_token": access_token, "count": 500}
                    if next_cursor:
                        payload["cursor"] = next_cursor
                    result = self._request("/transactions/sync", payload)
                    for raw in result.get("added", []) + result.get("modified", []):
                        if raw.get("iso_currency_code") != "USD" or raw.get("unofficial_currency_code"):
                            raise PlaidIntegrationError("A transaction currency needs review.", "PLAID_RESPONSE_ERROR")
                    added.extend(transaction_from_plaid_json(x) for x in result.get("added", []))
                    modified.extend(transaction_from_plaid_json(x) for x in result.get("modified", []))
                    removed.extend(x["transaction_id"] for x in result.get("removed", []))
                    previous, next_cursor = next_cursor, result["next_cursor"]
                    if not result["has_more"]:
                        return (PlaidTransactionSync(tuple(added), next_cursor, tuple(modified), tuple(removed)),
                                result.get("transactions_update_status") == "HISTORICAL_UPDATE_COMPLETE")
                    if previous == next_cursor:
                        raise PlaidIntegrationError("Bank sync could not finish. Retry later.", "PLAID_RESPONSE_ERROR")
                raise PlaidIntegrationError("Bank sync could not finish. Retry later.", "PLAID_RESPONSE_ERROR")
            except PlaidIntegrationError as exc:
                if exc.code not in {"SYNC_UPDATES_DURING_PAGINATION", "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"} or attempt == 2:
                    raise


class LivePlaidService(BankRefreshMixin, PlaidConnectionService):
    def __init__(self, repository, client=None):
        super().__init__(repository, client or LivePlaidClient(), DatabasePlaidTokenStore(repository))
        if not repository.settings.hosted or not repository.settings.plaid_enabled or not repository.settings.token_box():
            raise ValueError("Live bank access requires the enabled encrypted hosted runtime")
        self.lock = threading.RLock()
        with repository.connect() as conn:
            if conn.execute("SELECT 1 FROM plaid_items i LEFT JOIN bank_sync_state s ON s.plaid_item_id=i.id WHERE s.environment IS NULL").fetchone():
                raise ValueError("Existing Sandbox connections must not be used with production credentials")

    def create_link_token(self, household_id):
        with self.lock:
            items = self.repository.list_plaid_items(household_id)
            token = self.token_store.retrieve(items[0].access_token_ref) if items else None
            return self.client.link_token(household_id, token)

    def exchange_public_token(self, *, household_id, budget_month_id, public_token):
        self.repository.require_budget_month_access(budget_month_id, household_id)
        with self.lock:
            if self.repository.list_plaid_items(household_id):
                raise PlaidIntegrationError("A bank is already connected. Use Reconnect and then sync.", "ITEM_ALREADY_CONNECTED")
            if not isinstance(public_token, str) or not public_token.startswith("public-production-"):
                raise PlaidIntegrationError("A production Link result is required.", "PUBLIC_TOKEN_REQUIRED")
            result = self.client._request("/item/public_token/exchange", {"public_token": public_token})
            # Persist immediately, BEFORE any subsequent network operation. A failed balance
            # or institution request must not strand a Trial Item or lose its access token.
            with self.repository.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                import uuid
                ref = "plaid-token-ref-" + uuid.uuid4().hex
                sealed = self.repository.settings.token_box().seal(result["access_token"])
                conn.execute("INSERT INTO plaid_access_tokens(token_ref, access_token) VALUES (?,?)", (ref, sealed))
                item_id = conn.execute("INSERT INTO plaid_items(household_id,plaid_item_id,access_token_ref,institution_name) VALUES (?,?,?,'USAA (verification pending)')",
                                       (household_id, result["item_id"], ref)).lastrowid
                conn.execute("INSERT INTO bank_sync_state(plaid_item_id,environment) VALUES (?,'production')", (item_id,))
            self.sync_balances(item_id)
            self.sync_transactions(item_id)
            return PlaidConnectionResult({"id": item_id}, tuple(account_to_dict(a) for a in self.repository.list_accounts(budget_month_id)))

    def sync_balances(self, plaid_item_id):
        with self.lock:
            try:
                with self.repository.connect() as conn:
                    conn.execute("UPDATE bank_sync_state SET balance_error=1 WHERE plaid_item_id=?", (plaid_item_id,))
                item = self.repository.get_plaid_item(plaid_item_id)
                token = self.token_store.retrieve(item.access_token_ref)
                accounts = self.client.accounts(token, fresh=True)
                with self.repository.connect() as conn:
                    month = conn.execute("SELECT active_budget_month_id FROM households WHERE id=?", (item.household_id,)).fetchone()[0]
                    if month is None:
                        raise ValueError("Choose a budget month before syncing")
                    conn.execute("BEGIN IMMEDIATE")
                    existing = {r["plaid_account_id"]: r for r in conn.execute("SELECT * FROM cash_accounts WHERE plaid_item_id=?", (plaid_item_id,))}
                    for account in accounts:
                        # New accounts require explicit inclusion, preventing double cash counting
                        # against existing manually entered accounts.
                        self.repository.upsert_connected_account(
                            budget_month_id=existing[account.plaid_account_id]["budget_month_id"] if account.plaid_account_id in existing else month,
                            plaid_item_id=plaid_item_id, **asdict(account),
                            _connection=conn)
                    returned = {a.plaid_account_id for a in accounts}
                    if returned != set(existing):
                        conn.execute("UPDATE bank_sync_state SET reconciled_at=NULL WHERE plaid_item_id=?", (plaid_item_id,))
                    for key, row in existing.items():
                        if key not in returned:
                            conn.execute("UPDATE cash_accounts SET last_balance_synced_at=NULL WHERE id=?", (row["id"],))
                    conn.execute("UPDATE cash_accounts SET last_balance_synced_at=CURRENT_TIMESTAMP WHERE plaid_item_id=? AND plaid_account_id IN (" + ",".join("?" for _ in returned) + ")", (plaid_item_id, *returned))
                    conn.execute("UPDATE bank_sync_state SET balance_checked_at=CURRENT_TIMESTAMP, balance_error=0 WHERE plaid_item_id=?", (plaid_item_id,))
                    conn.execute("UPDATE plaid_items SET institution_name='USAA', institution_id=? WHERE id=?", (os.environ["PLAID_USAA_INSTITUTION_ID"], plaid_item_id))
                return PlaidSyncOutcome(True, "balance", synced_accounts=len(accounts))
            except Exception as exc:
                return self._failure(plaid_item_id, "balance", exc)

    def sync_transactions(self, plaid_item_id):
        with self.lock:
            try:
                with self.repository.connect() as conn:
                    conn.execute("UPDATE bank_sync_state SET transaction_error=1 WHERE plaid_item_id=?", (plaid_item_id,))
                item = self.repository.get_plaid_item(plaid_item_id)
                token = self.token_store.retrieve(item.access_token_ref)
                # Discover accounts before advancing the cursor; never silently skip an
                # unknown supported account's history. Balance sync populates the account set.
                snapshots = self.client.accounts(token, fresh=False)
                known = {a.plaid_account_id for a in self.repository.list_accounts_for_item(plaid_item_id)}
                if any(a.plaid_account_id not in known for a in snapshots):
                    raise PlaidIntegrationError("Sync balances first to discover new accounts.", "ACCOUNTS_UNAVAILABLE")
                # Observe the bank update BEFORE downloading changes; a timestamp
                # that advances during the download cannot prove we imported it.
                status = self.client._request("/item/get", {"access_token": token})
                if (status.get("item") or {}).get("error"):
                    raise PlaidIntegrationError("Reconnect USAA in Settings.", "ITEM_LOGIN_REQUIRED")
                updated = ((status.get("status") or {}).get("transactions") or {}).get("last_successful_update")
                if updated:
                    datetime.fromisoformat(updated.replace("Z", "+00:00"))
                result, complete = self.client.sync_transactions(token, item.sync_cursor)
                counts = self.repository.apply_plaid_transaction_sync(
                    plaid_item_id=plaid_item_id, expected_cursor=item.sync_cursor, next_cursor=result.next_cursor,
                    transactions=(asdict(t) for t in result.transactions + result.modified_transactions),
                    removed_transaction_ids=result.removed_transaction_ids)
                with self.repository.connect() as conn:
                    conn.execute("UPDATE bank_sync_state SET transactions_checked_at=CURRENT_TIMESTAMP, transactions_updated_at=?, history_complete=?, transaction_error=0 WHERE plaid_item_id=?", (updated, int(complete), plaid_item_id))
                    mark_refresh_checked(conn, plaid_item_id, updated, complete)
                return PlaidSyncOutcome(True, "transaction", **counts)
            except Exception as exc:
                return self._failure(plaid_item_id, "transaction", exc)

    def _failure(self, item_id, kind, exc):
        code = exc.code if isinstance(exc, PlaidIntegrationError) else "PLAID_SYNC_INVALID"
        message = ("Reconnect USAA in Settings, then sync again."
                   if code in {"ITEM_LOGIN_REQUIRED", "ITEM_LOCKED", "USER_PERMISSION_REVOKED", "ADDITIONAL_CONSENT_REQUIRED"}
                   else "Bank sync did not finish. Try Sync again later; saved data was retained.")
        with self.repository.connect() as conn:
            column = "balance_error" if kind == "balance" else "transaction_error"
            conn.execute(f"UPDATE bank_sync_state SET {column}=1 WHERE plaid_item_id=?", (item_id,))
        self.repository.record_plaid_sync_error(plaid_item_id=item_id, sync_type=kind, error_code="BANK_SYNC_FAILED", error_message=message)
        return PlaidSyncOutcome(False, kind, error_code="BANK_SYNC_FAILED", error_message=message)
