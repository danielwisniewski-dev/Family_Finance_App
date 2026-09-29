"""User-visible bank freshness and explicit reconciliation, without provider internals."""
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from .bank_refresh import status_for_row


def recent(value, seconds):
    if not value:
        return False
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        return 0 <= age <= seconds
    except (ValueError, TypeError):
        return False


def bank_status(repository, month_id):
    household = repository.household_id_for_budget_month(month_id)
    with repository.connect() as conn:
        month = conn.execute("SELECT month FROM budget_months WHERE id=?", (month_id,)).fetchone()[0]
        rows = conn.execute("SELECT s.* FROM bank_sync_state s JOIN plaid_items i ON i.id=s.plaid_item_id WHERE i.household_id=?", (household,)).fetchall()
        txns = conn.execute("SELECT t.id,t.amount_cents,t.pending,t.ignored,t.reviewed,t.updated_at,EXISTS(SELECT 1 FROM transaction_category_assignments a WHERE a.transaction_id=t.id AND a.active=1) AS assigned FROM account_transactions t JOIN transaction_budget_months m ON m.transaction_id=t.id WHERE m.budget_month_id=? ORDER BY t.id", (month_id,)).fetchall()
        plan = [tuple(r) for r in conn.execute("SELECT c.id,c.planned_cents,c.archived,g.archived,c.reserve_fund_id FROM budget_categories c JOIN budget_groups g ON g.id=c.budget_group_id WHERE g.budget_month_id=? ORDER BY c.id", (month_id,))]
        bills = [tuple(r) for r in conn.execute("SELECT e.id,e.amount_cents,e.due_on,e.paid,e.reserve_fund_id FROM expected_bills e JOIN budget_months b ON b.id=e.budget_month_id WHERE b.household_id=? ORDER BY e.id", (household,))]
        allocations = [tuple(r) for r in conn.execute("SELECT a.id,a.budget_category_id,a.amount_cents,a.active FROM transaction_category_assignments a JOIN transaction_budget_months m ON m.transaction_id=a.transaction_id WHERE m.budget_month_id=? ORDER BY a.id", (month_id,))]
        from .funds import fund_rows
        reserves = [(f["id"], f["backing_account_id"], f["balance_cents"], f["archived"], f["contributed_this_month_cents"])
                    for f in fund_rows(conn, household, month_id)]
    accounts = repository.list_accounts(month_id)
    enabled = repository.settings.plaid_enabled
    issues = []
    if enabled and not rows:
        issues.append("Connect USAA before using safe-to-spend.")
    if enabled and not any(a.plaid_item_id and a.included_in_cash_reality for a in accounts):
        issues.append("Choose which USAA accounts fund household spending.")
    if enabled and any(not a.plaid_item_id and a.included_in_cash_reality for a in accounts):
        issues.append("Exclude manually entered accounts that duplicate your USAA cash.")
    for row in rows:
        if row["balance_error"] or not recent(row["balance_checked_at"], 900):
            issues.append("Sync bank balances; the last successful check must be within 15 minutes.")
        if (row["transaction_error"] or not recent(row["transactions_checked_at"], 900)
                or not recent(row["transactions_updated_at"], 86400) or not row["history_complete"]):
            issues.append("Sync transactions and wait for complete history. Bank transaction data must be less than 24 hours old.")
    for a in accounts:
        if a.plaid_item_id and a.included_in_cash_reality:
            if a.available_balance_cents is None or not recent(a.last_balance_synced_at, 900):
                issues.append("An included account lacks a recent available balance. Check USAA and retry.")
    unreviewed = sum(not t["ignored"] and t["amount_cents"] < 0 and (not t["reviewed"] or not t["assigned"]) for t in txns)
    if enabled and unreviewed:
        issues.append("Review imported spending, transfers, and possible manual duplicates before using safe-to-spend.")
    # A revision binds the user's confirmation to the values visible when they opened
    # the reconciliation screen. It is not a token and conveys no account access.
    revision = hashlib.sha256(json.dumps({"month": month,
        "accounts": [(a.id, a.balance_cents, a.available_balance_cents, a.current_balance_cents, a.included_in_cash_reality) for a in accounts],
        "transactions": [tuple(t) for t in txns], "plan": plan, "bills": bills, "allocations": allocations,
        "reserves": reserves}, sort_keys=True).encode()).hexdigest()
    reconciled = bool(rows) and all(r["reconciled_month"] == month and r["reconciled_at"] for r in rows)
    return {"enabled": enabled, "mode": "production" if enabled else "disabled" if repository.settings.hosted else "sandbox",
            "accounts": [asdict(account) for account in accounts],
            "connected": bool(rows), "can_reconcile": enabled and not issues,
            "connection_id": rows[0]["plaid_item_id"] if rows else None,
            "ready": enabled and not issues and reconciled, "reconciled": reconciled,
            "revision": revision, "issues": list(dict.fromkeys(issues)), "unreviewed_spending": unreviewed,
            "balance_checked_at": rows[0]["balance_checked_at"] if rows else None,
            "transactions_checked_at": rows[0]["transactions_checked_at"] if rows else None,
            "transactions_updated_at": rows[0]["transactions_updated_at"] if rows else None,
            "history_complete": bool(rows and rows[0]["history_complete"]),
            "refresh": status_for_row(rows[0] if rows else None),
            "reconciled_at": rows[0]["reconciled_at"] if rows else None}


def reconcile_bank(repository, month_id, revision):
    # The HTTP user has explicitly compared USAA with the displayed account balances,
    # transaction dates/amounts, transfers/refunds and upcoming bills.
    with repository.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        status = bank_status(repository, month_id)
        if not status["can_reconcile"] or status["revision"] != revision:
            raise ValueError("Bank data changed or needs attention. Refresh and compare USAA again.")
        conn.execute("UPDATE bank_sync_state SET reconciled_at=CURRENT_TIMESTAMP, reconciled_month=(SELECT month FROM budget_months WHERE id=?) WHERE plaid_item_id IN (SELECT id FROM plaid_items WHERE household_id=?)",
                     (month_id, repository.household_id_for_budget_month(month_id)))
    return bank_status(repository, month_id)


def require_bank_ready(repository, month_id, today):
    if not repository.settings.plaid_enabled:
        return
    status = bank_status(repository, month_id)
    with repository.connect() as conn:
        month = conn.execute("SELECT month FROM budget_months WHERE id=?", (month_id,)).fetchone()[0]
        household = repository.household_id_for_budget_month(month_id)
        payday = conn.execute("SELECT MIN(payday_date) FROM paydays WHERE household_id=? AND payday_date>=?", (household, today.isoformat())).fetchone()[0]
        if payday and not conn.execute("SELECT 1 FROM budget_months WHERE household_id=? AND month=?", (household,payday[:7])).fetchone():
            raise ValueError("Plan the next budget month and its upcoming bills before checking spending across payday.")
    from .dates import household_today
    if today != household_today():
        raise ValueError("Live safe-to-spend must use today's date.")
    if month != today.strftime("%Y-%m"):
        raise ValueError("Use the current budget month for safe-to-spend with live balances.")
    if not status["ready"]:
        raise ValueError(status["issues"][0] if status["issues"] else "Compare USAA balances and transactions, then confirm reconciliation in Settings.")
