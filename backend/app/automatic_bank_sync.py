"""Household-shared foreground sync policy; never request a provider refresh."""
from datetime import datetime, timezone
from .dates import household_date_at

SYNC_INTERVAL_SECONDS = 3 * 60 * 60
RETRY_INTERVAL_SECONDS = 60


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (AttributeError, ValueError, TypeError, OverflowError):
        return None


def sync_due(row, now):
    if row["balance_error"] or row["transaction_error"] or not row["history_complete"]:
        return True
    for field in ("balance_checked_at", "transactions_checked_at"):
        checked = timestamp(row[field])
        if (checked is None or checked > now or (now - checked).total_seconds() >= SYNC_INTERVAL_SECONDS
                or household_date_at(checked) != household_date_at(now)):
            return True
    return False


def record_successful_sync(connection, item_id):
    cursor = connection.execute("SELECT * FROM bank_sync_state WHERE plaid_item_id=?", (item_id,))
    values = cursor.fetchone()
    row = dict(zip((column[0] for column in cursor.description), values)) if values else None
    if not row or row["balance_error"] or row["transaction_error"]:
        return
    stamps = [timestamp(row[field]) for field in ("balance_checked_at", "transactions_checked_at")]
    if all(stamps):
        connection.execute("UPDATE bank_sync_state SET last_successful_sync_at=? WHERE plaid_item_id=?",
                           (min(stamps).isoformat(), item_id))


def sync_if_due(repository, service, month_id, *, force=False, now=None):
    from .bank_data import bank_status
    household = repository.household_id_for_budget_month(month_id)
    if not repository.settings.plaid_enabled:
        return {"success": True, "synced": False, "bank_status": bank_status(repository, month_id)}
    # Live and demo services share this reentrant lock with their normal sync paths.
    # Recheck saved timestamps AFTER acquiring it: two spouses opening together sync once.
    with service.lock:
        now = now or datetime.now(timezone.utc)
        with repository.connect() as connection:
            rows = connection.execute("SELECT s.* FROM bank_sync_state s JOIN plaid_items i ON i.id=s.plaid_item_id WHERE i.household_id=?", (household,)).fetchall()
        due = [row for row in rows if force or sync_due(row, now)]
        synced = False
        for row in due:
            attempted = timestamp(row["auto_sync_attempted_at"])
            age = (now - attempted).total_seconds() if attempted else RETRY_INTERVAL_SECONDS
            if not force and 0 <= age < RETRY_INTERVAL_SECONDS:
                return {"success": False, "synced": synced, "retry_after_seconds": max(1, int(RETRY_INTERVAL_SECONDS - age)),
                        "message": "Bank sync could not finish. Your saved data is still available. Retry shortly."}
            with repository.connect() as connection:
                connection.execute("UPDATE bank_sync_state SET auto_sync_attempted_at=? WHERE plaid_item_id=?", (now.isoformat(), row["plaid_item_id"]))
            for operation in (service.sync_balances, service.sync_transactions):
                outcome = operation(row["plaid_item_id"])
                if not outcome.success:
                    return {"success": False, "synced": synced,
                            "message": outcome.error_message or "Bank sync could not finish. Your saved data is still available."}
            synced = True
        return {"success": True, "synced": synced, "bank_status": bank_status(repository, month_id)}
