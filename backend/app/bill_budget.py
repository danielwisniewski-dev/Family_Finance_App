"""Match an expected bill and its dedicated monthly budget line to a posted payment."""


def match_bill_budget(repository, transaction_id, household_id, actor_user_id, confirmed=None):
    with repository.connect() as connection:
        connection.execute("BEGIN IMMEDIATE" if confirmed is not None else "BEGIN")
        context = repository._notification_context_for_transaction(connection, transaction_id)
        if context["household_id"] != household_id:
            raise PermissionError("Transaction is unavailable for this household.")
        eligible = connection.execute(
            """SELECT b.id AS bill_id, b.name AS bill_name, b.amount_cents AS bill_amount_cents,
                      c.id AS category_id, c.name AS category_name, c.planned_cents AS planned_cents,
                      -t.amount_cents AS expense_cents
               FROM account_transactions t
               JOIN transaction_budget_months m ON m.transaction_id=t.id
               JOIN transaction_category_assignments a ON a.transaction_id=t.id AND a.active=1
               JOIN budget_categories c ON c.id=a.budget_category_id
               JOIN budget_groups g ON g.id=c.budget_group_id AND g.budget_month_id=m.budget_month_id
               JOIN expected_bills b ON b.budget_category_id=c.id AND b.budget_month_id=m.budget_month_id
               WHERE t.id=? AND t.amount_cents<0 AND t.pending=0 AND t.ignored=0 AND t.reviewed=1
                 AND g.archived=0 AND c.archived=0 AND c.reserve_fund_id IS NULL AND b.reserve_fund_id IS NULL
                 AND NOT EXISTS (SELECT 1 FROM transaction_category_assignments s
                                 WHERE s.transaction_id=t.id AND s.active=1 AND s.id!=a.id)
                 AND NOT EXISTS (SELECT 1 FROM manual_spending s WHERE s.budget_category_id=c.id)
                 AND NOT EXISTS (
                     SELECT 1 FROM transaction_category_assignments s
                     JOIN account_transactions other ON other.id=s.transaction_id
                     WHERE s.budget_category_id=c.id AND s.active=1 AND other.id!=t.id
                       AND other.ignored=0 AND other.amount_cents<0
                 )""",
            (transaction_id,),
        ).fetchone()
        offer = dict(eligible) if eligible is not None else None
        if offer and offer["expense_cents"] == offer["bill_amount_cents"] == offer["planned_cents"]:
            offer = None
        if confirmed is None:
            return offer
        if offer is None or confirmed != offer:
            raise ValueError("The expense or bill budget changed. Reopen the transaction before adjusting it.")
        expense = offer["expense_cents"]
        connection.execute("UPDATE expected_bills SET amount_cents=? WHERE id=?", (expense, offer["bill_id"]))
        connection.execute("UPDATE budget_categories SET planned_cents=? WHERE id=?", (expense, offer["category_id"]))
        repository._insert_notification_event(
            connection, household_id=household_id, budget_month_id=context["budget_month_id"],
            event_type="bill_changed", actor_user_id=actor_user_id, affected_entity_type="expected_bill",
            affected_entity_id=offer["bill_id"], title="Bill budget adjusted",
            message=f"{offer['bill_name']} and its budget line were matched to a posted expense.",
            severity="info", metadata={"transaction_id": transaction_id, **offer},
        )
        return None
