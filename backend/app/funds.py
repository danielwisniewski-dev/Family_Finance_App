"""Persistent, cash-backed provision funds. Plans never create money.

The immutable ledger records earmarks, releases and moves. Bank spending is read
from existing active category allocations, so corrections, splits and refunds
have exactly the same effect here as in the transaction budget.
"""
from __future__ import annotations

import json
from datetime import date

from .dates import household_today


def _cents(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0):
        raise ValueError(f"{label} must be {'positive' if positive else 'nonnegative'} integer cents")
    if value > 9_000_000_000_000:
        raise ValueError(f"{label} is too large")
    return value


def _text(value, label, *, required=False, maximum=500):
    if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
        raise ValueError(f"{label} must be {'nonempty ' if required else ''}text up to {maximum} characters")
    return value.strip()


def _breakdown(value):
    if not isinstance(value, (list, tuple)) or len(value) > 100:
        raise ValueError("breakdown must contain at most 100 items")
    result = []
    for item in value:
        if not isinstance(item, dict) or not {"name", "annual_cents"} <= set(item) or set(item)-{"name", "annual_cents", "timing_note"}:
            raise ValueError("Each breakdown item needs name and annual_cents")
        result.append({"name": _text(item["name"], "breakdown name", required=True, maximum=120),
                       "annual_cents": _cents(item["annual_cents"], "annual_cents"),
                       "timing_note": _text(item.get("timing_note", ""), "breakdown timing_note")})
    return result


def fund_rows(connection, household_id, budget_month_id):
    """Return all funds, including archived money that still needs protection."""
    month = connection.execute("SELECT month FROM budget_months WHERE id=?", (budget_month_id,)).fetchone()[0]
    result = []
    for row in connection.execute("""SELECT f.*,a.name AS backing_account_name,
            a.balance_cents AS backing_balance_cents,a.included_in_cash_reality,
            a.available_balance_cents,a.last_balance_synced_at,a.plaid_item_id
            FROM reserve_funds f JOIN cash_accounts a ON a.id=f.backing_account_id
            WHERE f.household_id=? ORDER BY f.id""", (household_id,)):
        fund = dict(row)
        if fund["plaid_item_id"] is not None and fund["available_balance_cents"] is not None:
            fund["backing_balance_cents"] = fund["available_balance_cents"]
        category = connection.execute("""SELECT c.*,g.archived AS group_archived FROM budget_categories c JOIN budget_groups g ON g.id=c.budget_group_id
            WHERE c.reserve_fund_id=? AND g.budget_month_id=? ORDER BY c.id""", (row["id"], budget_month_id)).fetchone()
        entries = [dict(e) for e in connection.execute("""SELECT e.id,e.kind,e.amount_cents,e.occurred_on,e.note,
            e.budget_month_id,COALESCE(u.name,'') AS actor_name,COALESCE(other.name,'') AS counterpart_name
            FROM reserve_entries e LEFT JOIN users u ON u.id=e.actor_user_id
            LEFT JOIN reserve_funds other ON other.id=e.counterpart_fund_id WHERE e.fund_id=? ORDER BY e.id""", (row["id"],))]
        expenses = [dict(e) for e in connection.execute("""SELECT -t.id AS id,'expense' AS kind,
            -SUM(a.amount_cents) AS amount_cents,t.occurred_on,t.name AS note,'' AS actor_name,'' AS counterpart_name
            FROM transaction_category_assignments a JOIN budget_categories c ON c.id=a.budget_category_id
            JOIN account_transactions t ON t.id=a.transaction_id
            WHERE c.reserve_fund_id=? AND a.active=1 AND t.ignored=0 GROUP BY t.id
            UNION ALL SELECT -t.id AS id,'refund' AS kind,r.amount_cents,t.occurred_on,t.name,'',''
            FROM transaction_refunds r JOIN budget_categories c ON c.id=r.budget_category_id
            JOIN account_transactions t ON t.id=r.transaction_id WHERE c.reserve_fund_id=? AND t.ignored=0""",
            (row["id"], row["id"]))]
        direct = sum(e["amount_cents"] for e in entries if e["budget_month_id"] == budget_month_id and e["kind"] in {"contribution", "release"})
        balance = sum(e["amount_cents"] for e in entries) + sum(e["amount_cents"] for e in expenses)
        planned = category["planned_cents"] if category and not category["archived"] and not category["group_archived"] and not row["archived"] else 0
        fund.update(category_id=category["id"] if category else None,
                    category_archived=bool(category and category["archived"]),
                    monthly_plan_cents=planned, contributed_this_month_cents=direct,
                    spent_this_month_cents=-sum(e["amount_cents"] for e in expenses if e["occurred_on"][:7] == month),
                    balance_cents=balance, monthly_shortfall_cents=max(0, planned-direct),
                    deficit_cents=max(0, -balance),
                    breakdown=json.loads(row["breakdown_json"]),
                    entries=sorted(entries+expenses, key=lambda e: (e["occurred_on"], e["id"]), reverse=True))
        result.append(fund)
    return result


def cash_context(connection, household_id, budget_month_id, today, *, fund_id=None, purchase_amount_cents=0, balance_adjustments=None):
    rows = fund_rows(connection, household_id, budget_month_id)
    for row in rows:
        row["balance_cents"] += (balance_adjustments or {}).get(row["id"], 0)
    month_accounts = {r["id"] for r in connection.execute("""SELECT a.id FROM cash_accounts a
        JOIN budget_months b ON b.id=a.budget_month_id WHERE b.household_id=?
        AND (a.plaid_item_id IS NOT NULL OR a.budget_month_id=?)""", (household_id, budget_month_id))}
    balances = {r["id"]: max(0, r["balance_cents"]) for r in rows}
    included = {r["id"] for r in rows if r["included_in_cash_reality"] and r["backing_account_id"] in month_accounts}
    reserved = sum(balances[f] for f in included)
    release = min(balances.get(fund_id, 0), purchase_amount_cents) if fund_id in included else 0
    after = dict(balances)
    if fund_id in after:
        after[fund_id] = max(0, after[fund_id]-purchase_amount_cents)
    payday = connection.execute("SELECT MIN(payday_date) FROM paydays WHERE household_id=? AND payday_date>=?", (household_id, today.isoformat())).fetchone()[0]
    bills = connection.execute("""SELECT e.* FROM expected_bills e JOIN budget_months b ON b.id=e.budget_month_id
        WHERE b.household_id=? AND e.paid=0 AND e.due_on>=? AND e.due_on<? ORDER BY e.due_on,e.id""",
        (household_id, today.isoformat(), payday or today.isoformat())).fetchall()

    def covered(available):
        available = dict(available)
        total = 0
        for bill in bills:
            linked = bill["reserve_fund_id"]
            if linked in included:
                amount = min(bill["amount_cents"], available[linked])
                total += amount
                available[linked] -= amount
        return total

    issues = []
    by_account = {}
    for fund in rows:
        by_account[fund["backing_account_id"]] = by_account.get(fund["backing_account_id"], 0) + max(0, fund["balance_cents"])
        if fund["balance_cents"] < 0:
            issues.append(f"{fund['name']} has spent more than was set aside. Add money or correct its transactions.")
        if fund["balance_cents"] > 0 and fund["backing_account_id"] not in month_accounts:
            issues.append(f"The account backing {fund['name']} is unavailable in this budget month.")
    for account_id, protected in by_account.items():
        fund = next(f for f in rows if f["backing_account_id"] == account_id)
        if protected > max(0, fund["backing_balance_cents"]):
            issues.append(f"{fund['backing_account_name']} has less cash than its provision funds. Reconcile the reserve balances.")
    return {"rows": rows, "reserved_cash_cents": reserved, "funded_purchase_cents": release,
            "reserve_covered_bills_cents": covered(balances), "reserve_covered_bills_after_cents": covered(after),
            "bills_cents": sum(b["amount_cents"] for b in bills), "next_payday": payday,
            "issues": list(dict.fromkeys(issues)), "reserved_by_account": by_account,
            "available_account_ids": month_accounts}


def _public_fund(fund):
    keys = ("id", "name", "category_id", "backing_account_id", "backing_account_name", "monthly_plan_cents",
            "annual_target_cents", "timing_note", "breakdown", "contributed_this_month_cents",
            "spent_this_month_cents", "balance_cents", "monthly_shortfall_cents", "deficit_cents", "entries")
    return {key: fund[key] for key in keys} | {"archived": bool(fund["archived"]),
                                              "backing_included": bool(fund["included_in_cash_reality"])}


class FundRepositoryMixin:
    def _notify_fund(self, connection, *, household_id, budget_month_id, actor_user_id, fund_id, action, message, metadata=None):
        self._insert_notification_event(connection, household_id=household_id, budget_month_id=budget_month_id,
            event_type="provision_"+action, actor_user_id=actor_user_id, affected_entity_type="provision_fund",
            affected_entity_id=fund_id, title="Provision funds updated", message=message, severity="info", metadata=metadata)

    def require_fund_access(self, fund_id, household_id):
        with self.connect() as connection:
            self._require_fund(connection, fund_id, household_id)

    def _require_fund(self, connection, fund_id, household_id):
        row = connection.execute("SELECT * FROM reserve_funds WHERE id=? AND household_id=?", (fund_id, household_id)).fetchone()
        if row is None:
            raise LookupError("Provision fund not found")
        return row

    def get_funds(self, budget_month_id, today=None):
        today = today or household_today()
        with self.connect() as connection:
            connection.execute("BEGIN")
            month = self._require_budget_month(connection, budget_month_id)
            context = cash_context(connection, month["household_id"], budget_month_id, today)
        funds = [_public_fund(f) for f in context["rows"]]
        return {"budget_month_id": budget_month_id, "month": month["month"], "funds": funds,
                "total_planned_cents": sum(f["monthly_plan_cents"] for f in funds),
                "total_contributed_cents": sum(f["contributed_this_month_cents"] for f in funds),
                "total_spent_cents": sum(f["spent_this_month_cents"] for f in funds),
                "total_balance_cents": sum(f["balance_cents"] for f in funds),
                "total_shortfall_cents": sum(f["monthly_shortfall_cents"] for f in funds),
                "reserved_included_cents": context["reserved_cash_cents"], "issues": context["issues"]}

    def _create_fund(self, connection, *, budget_month_id, name, backing_account_id, monthly_plan_cents,
                     annual_target_cents=0, timing_note="", breakdown=(), actor_user_id=None):
        name = _text(name, "name", required=True, maximum=120)
        _cents(monthly_plan_cents, "monthly_plan_cents")
        _cents(annual_target_cents, "annual_target_cents")
        timing_note = _text(timing_note, "timing_note")
        breakdown = _breakdown(breakdown)
        month = self._require_budget_month(connection, budget_month_id)
        household = month["household_id"]
        account = connection.execute("""SELECT a.* FROM cash_accounts a JOIN budget_months b ON b.id=a.budget_month_id
            WHERE a.id=? AND b.household_id=? AND a.account_type IN ('checking','savings')
            AND (a.plaid_item_id IS NOT NULL OR a.budget_month_id=?)""", (backing_account_id, household, budget_month_id)).fetchone()
        if account is None:
            raise ValueError("Choose a household checking or savings account available in this month")
        if self.settings.plaid_enabled and account["plaid_item_id"] is None:
            raise ValueError("Choose a connected bank account to back live provision funds")
        if actor_user_id is not None:
            self._validate_user_for_household(connection, household, actor_user_id)
        if connection.execute("SELECT 1 FROM reserve_funds WHERE household_id=? AND lower(name)=lower(?)", (household, name)).fetchone():
            raise ValueError("A provision fund with this name already exists")
        fund_id = connection.execute("""INSERT INTO reserve_funds(household_id,name,backing_account_id,annual_target_cents,timing_note,breakdown_json)
            VALUES (?,?,?,?,?,?)""", (household, name, backing_account_id, annual_target_cents, timing_note, json.dumps(breakdown))).lastrowid
        self._attach_fund_category(connection, budget_month_id, fund_id, name, monthly_plan_cents)
        return fund_id

    def _attach_fund_category(self, connection, budget_month_id, fund_id, name, monthly_plan_cents):
        group = connection.execute("SELECT id FROM budget_groups WHERE budget_month_id=? AND name='Combined Monthly Provision' AND archived=0 ORDER BY id LIMIT 1", (budget_month_id,)).fetchone()
        group_id = group[0] if group else connection.execute("INSERT INTO budget_groups(budget_month_id,name) VALUES (?,'Combined Monthly Provision')", (budget_month_id,)).lastrowid
        return connection.execute("INSERT INTO budget_categories(budget_group_id,name,planned_cents,reserve_fund_id,display_order) VALUES (?,?,?,?,?)",
                                  (group_id, name, monthly_plan_cents, fund_id, fund_id)).lastrowid

    def create_fund(self, **kwargs):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            fund_id = self._create_fund(connection, **kwargs)
            household = self._require_budget_month(connection, kwargs["budget_month_id"])["household_id"]
            self._notify_fund(connection, household_id=household, budget_month_id=kwargs["budget_month_id"],
                actor_user_id=kwargs.get("actor_user_id"), fund_id=fund_id, action="created",
                message=f"{kwargs['name']} was added with no money set aside.")
        return next(f for f in self.get_funds(kwargs["budget_month_id"])["funds"] if f["id"] == fund_id)

    def setup_funds(self, *, budget_month_id, backing_account_id, funds, replace_category_id=None, actor_user_id=None):
        if not isinstance(funds, (list, tuple)) or not 1 <= len(funds) <= 100:
            raise ValueError("Choose between 1 and 100 provision funds")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            month = self._require_budget_month(connection, budget_month_id)
            if connection.execute("SELECT 1 FROM reserve_funds WHERE household_id=?", (month["household_id"],)).fetchone():
                raise ValueError("Provision funds are already set up; edit the existing funds")
            if replace_category_id is not None:
                old = connection.execute("""SELECT c.* FROM budget_categories c JOIN budget_groups g ON g.id=c.budget_group_id
                    WHERE c.id=? AND g.budget_month_id=? AND c.reserve_fund_id IS NULL""", (replace_category_id, budget_month_id)).fetchone()
                if old is None:
                    raise ValueError("Choose the existing provision category from this budget month")
                if connection.execute("SELECT 1 FROM merchant_category_rules WHERE budget_category_id=? AND active=1", (replace_category_id,)).fetchone():
                    raise ValueError("Review or disable merchant rules for the old provision category before replacing its plan")
                # Keep historical spending and assignments visible. Only its current
                # contribution plan is replaced, explicitly, by the new child plans.
                connection.execute("UPDATE budget_categories SET planned_cents=0 WHERE id=?", (replace_category_id,))
            for spec in funds:
                if not isinstance(spec, dict) or set(spec)-{"name", "monthly_plan_cents", "annual_target_cents", "timing_note", "breakdown"}:
                    raise ValueError("Invalid provision fund setup fields")
                if not {"name", "monthly_plan_cents"} <= set(spec):
                    raise ValueError("Each provision fund needs name and monthly_plan_cents")
                self._create_fund(connection, budget_month_id=budget_month_id, backing_account_id=backing_account_id,
                                  actor_user_id=actor_user_id, **spec)
            self._notify_fund(connection, household_id=month["household_id"], budget_month_id=budget_month_id,
                actor_user_id=actor_user_id, fund_id=None, action="setup", message="Provision funds were set up with zero starting balances.",
                metadata={"replaced_category_id": replace_category_id, "fund_count": len(funds)})
        return self.get_funds(budget_month_id)

    def update_fund(self, *, fund_id, budget_month_id, name=None, monthly_plan_cents=None,
                    annual_target_cents=None, timing_note=None, breakdown=None, archived=None, actor_user_id=None):
        fields = {}
        if name is not None:
            fields["name"] = _text(name, "name", required=True, maximum=120)
        if annual_target_cents is not None:
            fields["annual_target_cents"] = _cents(annual_target_cents, "annual_target_cents")
        if timing_note is not None:
            fields["timing_note"] = _text(timing_note, "timing_note")
        if breakdown is not None:
            fields["breakdown_json"] = json.dumps(_breakdown(breakdown))
        if archived is not None:
            if not isinstance(archived, bool):
                raise ValueError("archived must be true or false")
            fields["archived"] = int(archived)
        if monthly_plan_cents is not None:
            _cents(monthly_plan_cents, "monthly_plan_cents")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            household = self._require_budget_month(connection, budget_month_id)["household_id"]
            before = dict(self._require_fund(connection, fund_id, household))
            if actor_user_id is not None:
                self._validate_user_for_household(connection, household, actor_user_id)
            if name is not None and connection.execute("SELECT 1 FROM reserve_funds WHERE household_id=? AND lower(name)=lower(?) AND id!=?", (household, fields["name"], fund_id)).fetchone():
                raise ValueError("A provision fund with this name already exists")
            category = connection.execute("""SELECT c.id,c.planned_cents,g.archived AS group_archived FROM budget_categories c JOIN budget_groups g ON g.id=c.budget_group_id
                WHERE c.reserve_fund_id=? AND g.budget_month_id=?""", (fund_id, budget_month_id)).fetchone()
            previous_monthly_plan = category["planned_cents"] if category else None
            if category is None and (archived is False or monthly_plan_cents is not None):
                if fields.get("archived", before["archived"]):
                    raise ValueError("Restore the provision fund before adding its monthly plan")
                # A fund may have been skipped while archived, or this month may
                # have been created without copying. An explicit restore/plan edit
                # attaches it with zero planned money unless the user supplies a plan.
                category_id = self._attach_fund_category(connection, budget_month_id, fund_id,
                    fields.get("name", before["name"]), monthly_plan_cents if monthly_plan_cents is not None else 0)
                category = connection.execute("""SELECT c.id,c.planned_cents,g.archived AS group_archived FROM budget_categories c
                    JOIN budget_groups g ON g.id=c.budget_group_id WHERE c.id=?""", (category_id,)).fetchone()
            if archived is False and category and category["group_archived"]:
                raise ValueError("Restore the budget group before restoring this fund")
            if fields:
                connection.execute("UPDATE reserve_funds SET " + ",".join(k+"=?" for k in fields) + " WHERE id=?", (*fields.values(), fund_id))
            if category:
                for key, value in (("name", fields.get("name")), ("planned_cents", monthly_plan_cents), ("archived", fields.get("archived"))):
                    if value is not None:
                        connection.execute(f"UPDATE budget_categories SET {key}=? WHERE id=?", (value, category["id"]))
            if fields or monthly_plan_cents is not None:
                metadata = {"before": {k: before[k] for k in fields}, "after": fields,
                            "previous_monthly_plan_cents": previous_monthly_plan,
                            "monthly_plan_cents": monthly_plan_cents}
                self._notify_fund(connection, household_id=household, budget_month_id=budget_month_id,
                    actor_user_id=actor_user_id, fund_id=fund_id, action="plan_changed",
                    message=f"The plan for {fields.get('name', before['name'])} was updated.", metadata=metadata)
        return next(f for f in self.get_funds(budget_month_id)["funds"] if f["id"] == fund_id)

    def _fund_operation(self, connection, household, idempotency_key, payload):
        key = _text(idempotency_key, "idempotency_key", required=True, maximum=128)
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        existing = connection.execute("SELECT id,payload_json FROM reserve_operations WHERE household_id=? AND idempotency_key=?", (household, key)).fetchone()
        if existing:
            if existing["payload_json"] != serialized:
                raise ValueError("This request key was already used for a different provision change")
            return existing["id"], True
        operation = connection.execute("INSERT INTO reserve_operations(household_id,idempotency_key,payload_json) VALUES (?,?,?)", (household, key, serialized)).lastrowid
        return operation, False

    def _validate_fund_change(self, connection, budget_month_id, occurred_on, amount_cents, actor_user_id):
        _cents(amount_cents, "amount_cents", positive=True)
        if type(occurred_on) is not date or occurred_on > household_today():
            raise ValueError("Provision changes need a valid date that is not in the future")
        month = self._require_budget_month(connection, budget_month_id)
        if occurred_on.strftime("%Y-%m") != month["month"]:
            raise ValueError("Provision change date must be in the selected budget month")
        if actor_user_id is not None:
            self._validate_user_for_household(connection, month["household_id"], actor_user_id)
        return month

    def add_fund_entry(self, *, fund_id, budget_month_id, kind, amount_cents, occurred_on,
                       idempotency_key, note="", actor_user_id=None):
        if kind not in {"contribution", "release"}:
            raise ValueError("kind must be contribution or release")
        note = _text(note, "note")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            month = self._validate_fund_change(connection, budget_month_id, occurred_on, amount_cents, actor_user_id)
            household = month["household_id"]
            self._require_fund(connection, fund_id, household)
            operation, replay = self._fund_operation(connection, household, idempotency_key,
                {"fund_id": fund_id, "budget_month_id": budget_month_id, "kind": kind, "amount_cents": amount_cents,
                 "occurred_on": occurred_on.isoformat(), "note": note, "actor_user_id": actor_user_id})
            if not replay:
                if self.settings.plaid_enabled and month["month"] != household_today().strftime("%Y-%m"):
                    raise ValueError("Use the current budget month when changing live bank reserves")
                context = cash_context(connection, household, budget_month_id, household_today())
                fund = next(f for f in context["rows"] if f["id"] == fund_id)
                if kind == "contribution":
                    if self.settings.plaid_enabled and fund["plaid_item_id"] is None:
                        raise ValueError("Choose a connected bank account to back live provision funds")
                    if fund["backing_account_id"] not in context["available_account_ids"]:
                        raise ValueError("The backing account is not available in this budget month")
                    if fund["archived"] or fund["category_archived"] or fund["category_id"] is None:
                        raise ValueError("Cannot set aside money in an archived fund or a month without its budget line")
                    if connection.execute("SELECT g.archived FROM budget_groups g JOIN budget_categories c ON c.budget_group_id=g.id WHERE c.id=?", (fund["category_id"],)).fetchone()[0]:
                        raise ValueError("Cannot set aside money in an archived budget group")
                    from .bank_data import require_bank_ready, recent
                    require_bank_ready(self, budget_month_id, household_today())
                    if fund["plaid_item_id"] and self.settings.plaid_enabled and (fund["available_balance_cents"] is None or not recent(fund["last_balance_synced_at"], 900)):
                        raise ValueError("Sync the provision backing account before setting aside money")
                    if not context["next_payday"]:
                        raise ValueError("Add an upcoming payday before setting aside money")
                    prospective = cash_context(connection, household, budget_month_id, household_today(), balance_adjustments={fund_id: amount_cents})
                    if prospective["reserved_by_account"].get(fund["backing_account_id"], 0) > max(0, fund["backing_balance_cents"]):
                        raise ValueError("Not enough unreserved cash after upcoming bills to set aside this amount")
                    if fund["included_in_cash_reality"]:
                        snapshot = self._load_snapshot(budget_month_id)
                        if (snapshot["included_account_balance_cents"] - prospective["reserved_cash_cents"]
                                - prospective["bills_cents"] + prospective["reserve_covered_bills_cents"]) < 0:
                            raise ValueError("Not enough unreserved cash after upcoming bills to set aside this amount")
                elif amount_cents > max(0, fund["balance_cents"]):
                    raise ValueError("Cannot release more than this fund's available balance")
                connection.execute("""INSERT INTO reserve_entries(fund_id,operation_id,budget_month_id,kind,amount_cents,occurred_on,note,actor_user_id)
                    VALUES (?,?,?,?,?,?,?,?)""", (fund_id, operation, budget_month_id, kind,
                    amount_cents if kind == "contribution" else -amount_cents, occurred_on.isoformat(), note, actor_user_id))
                verb = "set aside in" if kind == "contribution" else "released from"
                self._notify_fund(connection, household_id=household, budget_month_id=budget_month_id,
                    actor_user_id=actor_user_id, fund_id=fund_id, action=kind,
                    message=f"${amount_cents / 100:,.2f} was {verb} {fund['name']}.",
                    metadata={"amount_cents": amount_cents, "operation_id": operation, "note": note})
        return self.get_funds(budget_month_id)

    def transfer_funds(self, *, source_fund_id, target_fund_id, budget_month_id, amount_cents,
                       occurred_on, idempotency_key, note="", actor_user_id=None):
        if source_fund_id == target_fund_id:
            raise ValueError("Choose two different provision funds")
        note = _text(note, "note")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            month = self._validate_fund_change(connection, budget_month_id, occurred_on, amount_cents, actor_user_id)
            household = month["household_id"]
            source = self._require_fund(connection, source_fund_id, household)
            target = self._require_fund(connection, target_fund_id, household)
            operation, replay = self._fund_operation(connection, household, idempotency_key,
                {"source_fund_id": source_fund_id, "target_fund_id": target_fund_id, "budget_month_id": budget_month_id,
                 "amount_cents": amount_cents, "occurred_on": occurred_on.isoformat(), "note": note, "actor_user_id": actor_user_id})
            if not replay:
                if self.settings.plaid_enabled and month["month"] != household_today().strftime("%Y-%m"):
                    raise ValueError("Use the current budget month when changing live bank reserves")
                if source["backing_account_id"] != target["backing_account_id"]:
                    raise ValueError("Funds must share the same backing account to move an earmark")
                rows = fund_rows(connection, household, budget_month_id)
                origin = next(f for f in rows if f["id"] == source_fund_id)
                destination = next(f for f in rows if f["id"] == target_fund_id)
                if target["archived"] or destination["category_archived"] or destination["category_id"] is None:
                    raise ValueError("Cannot move money into an archived fund or a month without its budget line")
                if connection.execute("SELECT g.archived FROM budget_groups g JOIN budget_categories c ON c.budget_group_id=g.id WHERE c.id=?", (destination["category_id"],)).fetchone()[0]:
                    raise ValueError("Cannot move money into an archived budget group")
                if amount_cents > max(0, origin["balance_cents"]):
                    raise ValueError("Cannot move more than the source fund's available balance")
                for fund_id, other, kind, amount in ((source_fund_id, target_fund_id, "transfer_out", -amount_cents),
                                                     (target_fund_id, source_fund_id, "transfer_in", amount_cents)):
                    connection.execute("""INSERT INTO reserve_entries(fund_id,operation_id,budget_month_id,kind,amount_cents,occurred_on,note,actor_user_id,counterpart_fund_id)
                        VALUES (?,?,?,?,?,?,?,?,?)""", (fund_id, operation, budget_month_id, kind, amount, occurred_on.isoformat(), note, actor_user_id, other))
                self._notify_fund(connection, household_id=household, budget_month_id=budget_month_id,
                    actor_user_id=actor_user_id, fund_id=source_fund_id, action="transfer",
                    message=f"${amount_cents / 100:,.2f} was moved from {source['name']} to {target['name']}.",
                    metadata={"amount_cents": amount_cents, "target_fund_id": target_fund_id, "operation_id": operation, "note": note})
        return self.get_funds(budget_month_id)
