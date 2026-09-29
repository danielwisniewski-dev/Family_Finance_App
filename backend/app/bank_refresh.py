"""Explicit bank refresh requests, separate from ordinary cursor imports.

The durable claim prevents both spouses (and restarted workers) from repeating
an expensive bank extraction while its response is uncertain. No tokens or raw
provider responses are persisted here or returned to the phone.
"""
from datetime import datetime, timedelta, timezone
from math import ceil

from .plaid import PlaidIntegrationError

REFRESH_COOLDOWN_SECONDS = 60


def utc_now():
    return datetime.now(timezone.utc)


def _timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except ValueError:
        return None


def status_for_row(row, now=None):
    now = now or utc_now()
    requested = _timestamp(row["refresh_requested_at"]) if row else None
    next_allowed = _timestamp(row["refresh_next_allowed_at"]) if row else None
    if next_allowed is None and requested:
        next_allowed = requested + timedelta(seconds=REFRESH_COOLDOWN_SECONDS)
    remaining = max(0, ceil((next_allowed-now).total_seconds())) if next_allowed else 0
    state = row["refresh_state"] if row else "idle"
    messages = {
        "idle": "Request fresh bank data when transactions in USAA are missing after a normal Sync.",
        "pending": "USAA refresh requested. Waiting for updated transactions to become available in Plaid.",
        "unknown": "The request may have reached USAA. Use Sync to import available transactions before making another request.",
        "checked": "Imported the latest transactions Plaid has made available. New USAA transactions can still take time to appear.",
        "failed": "The bank refresh request was not accepted. Try again later.",
    }
    failures = {
        "authorization": "USAA authorization needs attention. Use Reconnect USAA in Settings, then try again.",
        "rate_limit": "Plaid is limiting fresh bank requests. Wait and try again later; normal Sync is still available.",
        "not_enabled": "Fresh bank requests are unavailable for this connection. Normal Sync is still available.",
        "unavailable": "USAA could not accept the fresh-data request. Try again later; normal Sync is still available.",
    }
    return {"state": state, "requested_at": row["refresh_requested_at"] if row else None,
            "checked_at": row["refresh_checked_at"] if row else None,
            "retry_after_seconds": remaining, "can_request": row is not None and remaining == 0,
            "message": failures.get(row["refresh_error_code"], messages["failed"]) if row and state == "failed" else messages.get(state, messages["unknown"])}


def refresh_status(repository, item_id):
    with repository.connect() as connection:
        row = connection.execute("SELECT * FROM bank_sync_state WHERE plaid_item_id=?", (item_id,)).fetchone()
        return status_for_row(row)


def mark_refresh_checked(connection, item_id, bank_updated_at, history_complete):
    """A timestamp is evidence of a bank update, not proof every change is ready.

    Call only AFTER a successful atomic import, using a bank timestamp observed
    BEFORE fetching the cursor stream. The UI still retries empty imports.
    """
    if not history_complete:
        return
    row = connection.execute("SELECT * FROM bank_sync_state WHERE plaid_item_id=?", (item_id,)).fetchone()
    if not row or row["refresh_state"] not in {"pending", "unknown"}:
        return
    updated = _timestamp(bank_updated_at)
    requested = _timestamp(row["refresh_requested_at"])
    baseline = _timestamp(row["refresh_baseline_updated_at"])
    if updated and requested and updated >= requested and (baseline is None or updated > baseline):
        connection.execute("UPDATE bank_sync_state SET refresh_state='checked',refresh_checked_at=?,refresh_error_code=NULL WHERE plaid_item_id=?",
                           (utc_now().isoformat(), item_id))


class BankRefreshMixin:
    def request_fresh_data(self, item_id):
        # Use the existing Item. Neither Link nor public-token exchange belongs here.
        if not self.repository.settings.plaid_enabled:
            raise PlaidIntegrationError("Fresh bank requests are not enabled on this backend.")
        with self.lock:
            now = utc_now()
            with self.repository.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT * FROM bank_sync_state WHERE plaid_item_id=? AND environment='production'", (item_id,)).fetchone()
                if row is None:
                    raise LookupError("Bank connection not found")
                status = status_for_row(row, now)
                if not status["can_request"]:
                    return {"success": status["state"] in {"pending", "checked"}, "request_sent": False, "refresh": status}
                # Commit the claim BEFORE the network request. A process crash or
                # lost response must not remove the cooldown or assert success.
                requested_at = now.isoformat()
                connection.execute("""UPDATE bank_sync_state SET refresh_requested_at=?,refresh_next_allowed_at=?,
                    refresh_baseline_updated_at=transactions_updated_at,refresh_checked_at=NULL,
                    refresh_state='unknown',refresh_error_code=NULL WHERE plaid_item_id=?""",
                    (requested_at, (now+timedelta(seconds=120)).isoformat(), item_id))
            state, error = "pending", None
            try:
                item = self.repository.get_plaid_item(item_id)
                token = self.token_store.retrieve(item.access_token_ref)
                response = self.client._request("/transactions/refresh", {"access_token": token})
                if not isinstance(response, dict) or not isinstance(response.get("request_id"), str) or not response["request_id"]:
                    state = "unknown"
            except PlaidIntegrationError as exc:
                codes = {"ITEM_LOGIN_REQUIRED": "authorization", "ITEM_LOCKED": "authorization",
                         "USER_PERMISSION_REVOKED": "authorization", "ADDITIONAL_CONSENT_REQUIRED": "authorization",
                         "TRANSACTIONS_REFRESH_LIMIT": "rate_limit", "RATE_LIMIT_EXCEEDED": "rate_limit",
                         "PRODUCT_NOT_ENABLED": "not_enabled", "INVALID_PRODUCT": "not_enabled",
                         "INSTITUTION_DOWN": "unavailable", "INSTITUTION_NOT_RESPONDING": "unavailable",
                         "PRODUCT_NOT_READY": "unavailable", "ITEM_NOT_SUPPORTED": "unavailable"}
                error = codes.get(exc.code)
                state = "failed" if error else "unknown"
            except Exception:
                state = "unknown"
            with self.repository.connect() as connection:
                connection.execute("""UPDATE bank_sync_state SET
                    refresh_state=CASE WHEN refresh_state='checked' THEN refresh_state ELSE ? END,
                    refresh_error_code=CASE WHEN refresh_state='checked' THEN NULL ELSE ? END,
                    refresh_next_allowed_at=? WHERE plaid_item_id=? AND refresh_requested_at=?""",
                    (state, error, (utc_now()+timedelta(seconds=REFRESH_COOLDOWN_SECONDS)).isoformat(), item_id, requested_at))
            status = refresh_status(self.repository, item_id)
            return {"success": status["state"] in {"pending", "checked"}, "request_sent": True, "refresh": status}
