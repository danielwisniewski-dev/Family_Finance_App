"""Explicit household choices of budget month and deposit destination."""
import hashlib
import json


def apply_income(repository, transaction_id, income_id=None, new_income=None, actor_user_id=None,
                 *, expected_month_id=None, expected_amount_cents=None):
    from .db import clean_required_text, validate_income_kind, validate_nonnegative_cents
    with repository.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        transaction = repository._require_transaction(connection, transaction_id)
        context = repository._notification_context_for_transaction(connection, transaction_id)
        if actor_user_id is not None:
            repository._validate_user_for_household(connection, context['household_id'], actor_user_id)
        if transaction['amount_cents'] <= 0 or transaction['pending'] or transaction['ignored']:
            raise ValueError("Choose a posted deposit that is not ignored to apply income")
        if context['budget_month_id'] is None:
            raise ValueError("Choose a budget month for this deposit first")
        if ((expected_month_id is not None and context['budget_month_id'] != expected_month_id)
                or (expected_amount_cents is not None and transaction['amount_cents'] != expected_amount_cents)):
            raise ValueError("This deposit changed. Reopen Transaction Detail before applying income.")
        if (income_id is None) == (new_income is None):
            raise ValueError("Choose existing income or create new income")
        request_json = '{}'
        previous = connection.execute('SELECT * FROM transaction_income WHERE transaction_id=?', (transaction_id,)).fetchone()
        if new_income is not None:
            if not isinstance(new_income, dict):
                raise ValueError("New income must include a name, kind and planned amount")
            if not isinstance(new_income.get('name'), str):
                raise ValueError("Enter an income name")
            name = clean_required_text(new_income.get('name'), 'Income name')
            kind = new_income.get('kind', 'main')
            if not isinstance(kind, str):
                raise ValueError("Choose regular or other income")
            planned = new_income.get('planned_cents', transaction['amount_cents'])
            validate_income_kind(kind)
            validate_nonnegative_cents(planned, 'planned_cents')
            request_json = json.dumps({'name': name, 'kind': kind, 'planned_cents': planned}, sort_keys=True)
            if previous and previous['request_json'] == request_json:
                return previous['income_id']
            income_id = connection.execute('INSERT INTO income_plan(budget_month_id,name,kind,planned_cents,received_cents) VALUES (?,?,?,?,0)',
                (context['budget_month_id'], name, kind, planned)).lastrowid
        income = connection.execute('SELECT * FROM income_plan WHERE id=? AND budget_month_id=?',
            (income_id, context['budget_month_id'])).fetchone()
        if income is None:
            raise ValueError("Income must belong to this transaction's budget month")
        if previous and previous['income_id'] == income_id:
            connection.execute('UPDATE account_transactions SET reviewed=1 WHERE id=?', (transaction_id,))
            return income_id
        connection.execute('DELETE FROM transaction_refunds WHERE transaction_id=?', (transaction_id,))
        repository._supersede_active_assignments(connection, transaction_id)
        connection.execute('INSERT INTO transaction_income(transaction_id,income_id,request_json) VALUES (?,?,?) ON CONFLICT(transaction_id) DO UPDATE SET income_id=excluded.income_id,request_json=excluded.request_json',
            (transaction_id, income_id, request_json))
        connection.execute('UPDATE account_transactions SET reviewed=1,updated_at=CURRENT_TIMESTAMP WHERE id=?', (transaction_id,))
        repository._record_transaction_event(connection, transaction_id=transaction_id, event_type='income_applied',
            amount_cents=transaction['amount_cents'], metadata={'income_id': income_id, 'previous_income_id': previous['income_id'] if previous else None})
        return income_id


def remove_income(repository, transaction_id, actor_user_id=None):
    with repository.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        context = repository._notification_context_for_transaction(connection, transaction_id)
        if actor_user_id is not None:
            repository._validate_user_for_household(connection, context['household_id'], actor_user_id)
        if connection.execute('DELETE FROM transaction_income WHERE transaction_id=?', (transaction_id,)).rowcount:
            connection.execute('UPDATE account_transactions SET reviewed=0,updated_at=CURRENT_TIMESTAMP WHERE id=?', (transaction_id,))
            repository._record_transaction_event(connection, transaction_id=transaction_id, event_type='income_unlinked')


def _matching_category(connection, category_id, month_id):
    source = connection.execute('SELECT c.*,g.name AS group_name FROM budget_categories c JOIN budget_groups g ON g.id=c.budget_group_id WHERE c.id=?', (category_id,)).fetchone()
    rows = connection.execute('''SELECT c.id FROM budget_categories c JOIN budget_groups g ON g.id=c.budget_group_id
        WHERE g.budget_month_id=? AND c.archived=0 AND g.archived=0
          AND NOT EXISTS(SELECT 1 FROM reserve_funds f WHERE f.id=c.reserve_fund_id AND f.archived=1)
          AND ((? IS NOT NULL AND c.reserve_fund_id=?) OR
               (? IS NULL AND c.reserve_fund_id IS NULL AND c.name=? AND g.name=?))''',
        (month_id, source['reserve_fund_id'], source['reserve_fund_id'], source['reserve_fund_id'], source['name'], source['group_name'])).fetchall()
    return (rows[0]['id'] if len(rows) == 1 else None), source['reserve_fund_id'] is not None


def move_month(repository, transaction_id, month_id, *, preview=False, revision=None, actor_user_id=None):
    with repository.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        transaction = repository._require_transaction(connection, transaction_id)
        context = repository._notification_context_for_transaction(connection, transaction_id)
        target = repository._require_budget_month(connection, month_id)
        if target['household_id'] != context['household_id']:
            raise ValueError("Choose a budget month in this household")
        if actor_user_id is not None:
            repository._validate_user_for_household(connection, context['household_id'], actor_user_id)
        assignments = repository._active_assignments(connection, transaction_id)
        refund = connection.execute('SELECT * FROM transaction_refunds WHERE transaction_id=?', (transaction_id,)).fetchone()
        income = connection.execute('SELECT i.* FROM income_plan i JOIN transaction_income r ON r.income_id=i.id WHERE r.transaction_id=?', (transaction_id,)).fetchone()
        mappings = [_matching_category(connection, row['budget_category_id'], month_id) for row in assignments]
        refund_mapping = _matching_category(connection, refund['budget_category_id'], month_id) if refund else (None, False)
        matched_income = [] if income is None else connection.execute('SELECT id FROM income_plan WHERE budget_month_id=? AND name=? AND kind=?',
            (month_id, income['name'], income['kind'])).fetchall()
        income_id = matched_income[0]['id'] if len(matched_income) == 1 else None
        missing_categories = any(item[0] is None for item in mappings)
        blocked = (missing_categories and any(item[1] for item in mappings)) or (refund and refund_mapping[1] and refund_mapping[0] is None)
        messages = []
        if blocked:
            messages.append("Add the matching categories and Provision Fund to that month's budget before moving this transaction.")
        elif missing_categories:
            messages.append("The category or split doesn't match this month. Choose its categories again after moving.")
        elif assignments:
            messages.append("The category" + (" split" if len(assignments) > 1 else "") + " will move to the matching budget categories.")
        if refund:
            messages.append("The refund will move to the matching category." if refund_mapping[0] else "Choose a refund category again after moving.")
        if income:
            messages.append("The received deposit will move to matching income: " + income['name'] + "." if income_id else "The deposit will be removed from this month's received income. Apply it to income again in the new month.")
        source_month = connection.execute('SELECT month FROM budget_months WHERE id=?', (context['budget_month_id'],)).fetchone()
        state = [dict(transaction), [dict(r) for r in assignments], dict(refund) if refund else None,
                 dict(income) if income else None, month_id, mappings, refund_mapping, income_id]
        digest = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
        result = {'source_month': source_month[0] if source_month else None, 'target_month': target['month'],
                  'can_move': not bool(blocked), 'message': ' '.join(messages) or 'This transaction will belong to the selected budget month.', 'revision': digest}
        if preview:
            return result
        if context['budget_month_id'] == month_id:
            return result  # A lost response/retry must not perform the move twice.
        if blocked:
            raise ValueError(result['message'])
        if revision != digest:
            raise ValueError("This transaction or its destination changed. Review the move again.")
        connection.execute('UPDATE account_transactions SET budget_month_override_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (month_id, transaction_id))
        repository._supersede_active_assignments(connection, transaction_id)
        if not missing_categories:
            for row, mapped in zip(assignments, mappings):
                repository._insert_assignment(connection, transaction_id=transaction_id, category_id=mapped[0], amount_cents=row['amount_cents'], source=row['source'])
        connection.execute('DELETE FROM transaction_refunds WHERE transaction_id=?', (transaction_id,))
        if refund and refund_mapping[0]:
            connection.execute('INSERT INTO transaction_refunds VALUES (?,?,?)', (transaction_id, refund_mapping[0], refund['amount_cents']))
        connection.execute('DELETE FROM transaction_income WHERE transaction_id=?', (transaction_id,))
        if income_id:
            connection.execute('INSERT INTO transaction_income(transaction_id,income_id) VALUES (?,?)', (transaction_id, income_id))
        if missing_categories or (refund and not refund_mapping[0]) or (income and not income_id):
            connection.execute('UPDATE account_transactions SET reviewed=0 WHERE id=?', (transaction_id,))
        repository._record_transaction_event(connection, transaction_id=transaction_id, event_type='budget_month_moved',
            metadata={'from_budget_month_id': context['budget_month_id'], 'to_budget_month_id': month_id})
        return result
