"""Budget month choices and deposit receipts use real domain paths and synthetic money."""
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import patch

from backend.app.db import BudgetRepository
from backend.app import migrations
from backend.app.demo_data import create_demo_context
from backend.app.hosted import Application


class TransactionPlanningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = BudgetRepository(Path(temporary.name) / 'synthetic.sqlite')
        self.repo.initialize()
        self.household = self.repo.create_household('Synthetic household')
        self.month = self.repo.create_budget_month(household_id=self.household, month='2026-12')
        self.group = self.repo.add_budget_group(budget_month_id=self.month, name='Living')
        self.food = self.repo.add_category(budget_group_id=self.group, name='Food', planned_cents=10000)
        self.home = self.repo.add_category(budget_group_id=self.group, name='Home', planned_cents=10000)
        self.income = self.repo.add_income(budget_month_id=self.month, name='Pay', kind='main', planned_cents=100000, received_cents=1000)
        item = self.repo.create_plaid_item(household_id=self.household, plaid_item_id='synthetic-item', access_token_ref='synthetic-ref')
        self.account = self.repo.upsert_connected_account(budget_month_id=self.month, plaid_item_id=item,
            plaid_account_id='synthetic-account', name='Checking', account_type='checking', balance_cents=100000, available_balance_cents=100000)
        self.next = self.repo.create_budget_month(household_id=self.household, month='2027-01', copy_from_budget_month_id=self.month)
        self.number = 0

    def transaction(self, amount=-5000, pending=False, key=None, occurred=date(2026,12,30)):
        self.number += 1
        return self.repo.upsert_plaid_transaction(cash_account_id=self.account,
            plaid_transaction_id=key or 'synthetic-' + str(self.number), amount_cents=amount,
            occurred_on=occurred, name='Synthetic transaction', pending=pending).transaction_id

    def received(self, month=None, income=None):
        rows = self.repo.get_budget_detail(month or self.month, date(2026,12,30))['income']
        return next(r['received_cents'] for r in rows if income is None or r['id'] == income)

    def move(self, transaction, target=None):
        target = target or self.next
        preview = self.repo.move_transaction_month(transaction, target, preview=True)
        self.assertTrue(preview['can_move'], preview)
        return self.repo.move_transaction_month(transaction, target, revision=preview['revision'])

    def test_categorized_move_is_atomic_keeps_bank_date_cash_and_sync_override(self):
        txn = self.transaction(key='expense')
        self.repo.assign_transaction_category(transaction_id=txn, category_id=self.food)
        before = self.repo.get_transaction_detail(txn)
        preview = self.repo.move_transaction_month(txn, self.next, preview=True)
        self.assertEqual(before, self.repo.get_transaction_detail(txn))
        self.move(txn)
        self.assertFalse(self.repo.list_budget_transactions(self.month))
        detail = self.repo.get_transaction_detail(txn)
        self.assertEqual(detail.transaction.occurred_on, date(2026,12,30))
        self.assertEqual(detail.budget_month, '2027-01')
        self.assertEqual(self.repo.get_budget_detail(self.month, date(2026,12,30))["total_spent_cents"], 0)
        self.assertEqual(self.repo.get_budget_detail(self.next, date(2026,12,30))["total_spent_cents"], 5000)
        self.repo.move_transaction_month(txn, self.next, revision=preview['revision'])
        self.transaction(key='expense', occurred=date(2027,1,1))
        self.assertEqual(self.repo.get_transaction_detail(txn).final_category_id, detail.final_category_id)
        self.assertEqual(self.repo.get_summary(self.next, date(2026,12,30)).included_account_balance_cents, 100000)
        self.move(txn, self.month)
        self.transaction(key='expense', occurred=date(2027,1,2))
        self.assertEqual(self.repo.get_transaction_detail(txn).budget_month_id, self.month)

    def test_split_moves_once_and_preserves_all_allocations(self):
        txn = self.transaction()
        self.repo.split_transaction(transaction_id=txn, splits=[{'category_id':self.food,'amount_cents':2000}, {'category_id':self.home,'amount_cents':3000}])
        self.move(txn)
        detail = self.repo.get_transaction_detail(txn)
        self.assertEqual(detail.categorization_status, 'split')
        self.assertEqual([a.amount_cents for a in detail.assignments], [2000,3000])
        self.assertEqual(self.repo.get_budget_detail(self.next, date(2026,12,30))["total_spent_cents"], 5000)

    def test_unmatched_category_returns_to_review_and_preview_is_stale_after_edit(self):
        txn = self.transaction()
        self.repo.assign_transaction_category(transaction_id=txn, category_id=self.food)
        empty = self.repo.create_budget_month(household_id=self.household, month='2027-02')
        preview = self.repo.move_transaction_month(txn, empty, preview=True)
        self.assertIn('again', preview['message'])
        self.repo.assign_transaction_category(transaction_id=txn, category_id=self.home)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.repo.move_transaction_month(txn, empty, revision=preview['revision'])
        self.move(txn, empty)
        self.assertTrue(self.repo.get_transaction_detail(txn).needs_review)
        self.assertFalse(self.repo.get_transaction_detail(txn).assignments)

    def test_income_adds_to_manual_receipts_once_relinks_and_unlinks(self):
        txn = self.transaction(25000)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.repo.apply_transaction_income(txn, self.income), range(2)))
        self.assertEqual(self.received(),26000)
        self.assertEqual(self.repo.get_transaction_detail(txn).categorization_status, 'income')
        other = self.repo.add_income(budget_month_id=self.month,name='Other',kind='sporadic',planned_cents=0)
        self.repo.apply_transaction_income(txn, other)
        self.assertEqual(self.received(income=self.income),1000)
        self.assertEqual(self.received(income=other),25000)
        self.repo.remove_transaction_income(txn)
        self.assertEqual(self.received(income=other),0)
        self.assertTrue(self.repo.get_transaction_detail(txn).needs_review)

    def test_create_income_and_apply_is_atomic_and_retry_safe(self):
        txn = self.transaction(7000)
        fields = {'name':'New pay','kind':'sporadic','planned_cents':7000}
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: self.repo.apply_transaction_income(txn,new_income=fields), range(2)))
        self.assertEqual(ids[0],ids[1])
        self.assertEqual(self.received(income=ids[0]),7000)
        self.assertEqual(len(self.repo.get_budget_detail(self.month,date(2026,12,30))['income']),2)
        with self.assertRaises(ValueError):
            self.repo.apply_transaction_income(txn,new_income={'name':'Invalid','kind':'bad'})
        self.assertEqual(self.received(income=ids[0]),7000)

    def test_income_moves_between_months_and_missing_match_removes_old_receipt(self):
        txn = self.transaction(25000)
        self.repo.apply_transaction_income(txn,self.income)
        self.move(txn)
        self.assertEqual(self.received(),1000)
        self.assertEqual(self.received(self.next),25000)
        empty = self.repo.create_budget_month(household_id=self.household, month='2027-02')
        self.move(txn,empty)
        self.assertEqual(self.received(self.next),0)
        self.assertIsNone(self.repo.get_transaction_detail(txn).income_id)
        self.assertTrue(self.repo.get_transaction_detail(txn).needs_review)

    def test_changed_deposit_rejects_stale_income_screen_without_writes(self):
        txn = self.transaction(25000, key='changed')
        self.transaction(24000, key='changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.repo.apply_transaction_income(txn, self.income, expected_amount_cents=25000, expected_month_id=self.month)
        self.assertEqual(self.received(),1000)
        self.move(txn)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.repo.apply_transaction_income(txn, new_income={'name':'Stale','kind':'main','planned_cents':24000}, expected_month_id=self.month)
        self.assertEqual(len(self.repo.get_budget_detail(self.next,date(2026,12,30))['income']),1)

    def test_unchanged_pending_spending_keeps_its_review_state(self):
        txn = self.transaction(-5000, pending=True, key='pending-spending')
        self.repo.assign_transaction_category(transaction_id=txn, category_id=self.food)
        self.transaction(-5000, pending=True, key='pending-spending')
        self.assertFalse(self.repo.get_transaction_detail(txn).needs_review)

    def test_income_refund_ignore_and_bank_correction_are_exclusive(self):
        txn = self.transaction(25000,key='deposit')
        self.repo.apply_transaction_income(txn,self.income)
        self.repo.assign_transaction_refund(txn,self.food)
        self.assertEqual(self.received(),1000)
        self.repo.apply_transaction_income(txn,self.income)
        self.assertIsNone(self.repo.get_transaction_detail(txn).refund_category_id)
        self.repo.set_transaction_ignored(transaction_id=txn,ignored=True)
        self.assertEqual(self.received(),1000)
        self.repo.set_transaction_ignored(transaction_id=txn,ignored=False)
        self.repo.apply_transaction_income(txn,self.income)
        self.transaction(24000,key='deposit')
        self.assertEqual(self.received(),1000)
        self.assertTrue(self.repo.get_transaction_detail(txn).needs_review)
        self.repo.apply_transaction_income(txn,self.income)
        self.repo.mark_plaid_transaction_removed('deposit')
        self.assertEqual(self.received(),1000)

    def test_receipt_editor_preserves_links_and_income_deletion_returns_deposit_to_review(self):
        txn = self.transaction(25000)
        self.repo.apply_transaction_income(txn,self.income)
        self.repo.update_income(income_id=self.income,received_cents=27000)
        self.assertEqual(self.received(),27000)
        with self.assertRaisesRegex(ValueError,'linked deposits'):
            self.repo.update_income(income_id=self.income,received_cents=24000)
        self.repo.remove_transaction_income(txn)
        self.assertEqual(self.received(),2000)
        self.repo.apply_transaction_income(txn,self.income)
        self.repo.remove_income(income_id=self.income)
        self.assertTrue(self.repo.get_transaction_detail(txn).needs_review)
        self.assertIsNone(self.repo.get_transaction_detail(txn).income_id)

    def test_invalid_pending_negative_ignored_cross_month_and_cross_household_rejected(self):
        for txn in [self.transaction(-100),self.transaction(0),self.transaction(100,pending=True)]:
            with self.assertRaises(ValueError): self.repo.apply_transaction_income(txn,self.income)
        txn=self.transaction(100)
        self.repo.set_transaction_ignored(transaction_id=txn)
        with self.assertRaises(ValueError): self.repo.apply_transaction_income(txn,self.income)
        self.repo.set_transaction_ignored(transaction_id=txn,ignored=False)
        next_income=self.repo.get_budget_detail(self.next,date(2026,12,30))['income'][0]['id']
        with self.assertRaises(ValueError): self.repo.apply_transaction_income(txn,next_income)
        household=self.repo.create_household('Other synthetic')
        month=self.repo.create_budget_month(household_id=household,month='2027-01')
        with self.assertRaises(ValueError): self.repo.move_transaction_month(txn,month,preview=True)
        with self.assertRaises(ValueError): self.repo.split_transaction(transaction_id=txn,splits=[{'category_id':self.food,'amount_cents':100}])

    def test_fund_move_preserves_saved_cash_and_uses_budget_month_for_spent(self):
        with patch('backend.app.funds.household_today',return_value=date(2026,12,30)):
            self.repo.add_payday(household_id=self.household,payday_date=date(2027,1,5))
            fund=self.repo.create_fund(budget_month_id=self.month,name='Repairs',backing_account_id=self.account,monthly_plan_cents=10000)
            self.repo.add_fund_entry(fund_id=fund['id'],budget_month_id=self.month,kind='contribution',amount_cents=10000,occurred_on=date(2026,12,30),idempotency_key='synthetic-funding')
            # Create a later copy that contains the newly-added fund.
            target=self.repo.create_budget_month(household_id=self.household,month='2027-02',copy_from_budget_month_id=self.month)
            txn=self.transaction()
            self.repo.assign_transaction_category(transaction_id=txn,category_id=fund['category_id'])
            self.assertFalse(self.repo.move_transaction_month(txn,self.next,preview=True)['can_move'])
            self.move(txn,target)
            from backend.app.funds import fund_rows
            with self.repo.connect() as connection:
                old=fund_rows(connection,self.household,self.month)[0]
                new=fund_rows(connection,self.household,target)[0]
            self.assertEqual(old['balance_cents'],5000)
            self.assertEqual(new['balance_cents'],5000)
            self.assertEqual(old['spent_this_month_cents'],0)
            self.assertEqual(new['spent_this_month_cents'],5000)

    def test_upgrade_preserves_version_five_money_and_defaults(self):
        old=BudgetRepository(self.repo.db_path.parent/'old.sqlite')
        with patch.object(migrations,'MIGRATIONS',migrations.MIGRATIONS[:5]): old.initialize()
        household=old.create_household('Upgrade synthetic')
        month=old.create_budget_month(household_id=household,month='2026-12')
        income=old.add_income(budget_month_id=month,name='Pay',kind='main',planned_cents=5000,received_cents=1234)
        old.initialize()
        self.assertEqual(old.get_budget_detail(month,date(2026,12,30))['income'][0]['received_cents'],1234)
        with old.connect() as connection:
            from backend.app.migrations import LATEST_VERSION
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], LATEST_VERSION)
            self.assertFalse(connection.execute('PRAGMA foreign_key_check').fetchall())


class TransactionPlanningApiTests(unittest.TestCase):
    def test_real_demo_routes_and_cross_environment_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            context=create_demo_context(Path(temporary)/'synthetic-real.sqlite')
            app=Application(context.repository)
            self.addCleanup(app.demo_manager.close)
            def request(path,token,payload=None,method='PATCH',expected=200):
                data=json.dumps(payload or {}).encode(); statuses=[]
                env={'REQUEST_METHOD':method,'PATH_INFO':path,'CONTENT_LENGTH':str(len(data)),
                    'wsgi.input':io.BytesIO(data),'HTTP_AUTHORIZATION':'Bearer '+token,'CONTENT_TYPE':'application/json'}
                result=json.loads(b''.join(app(env,lambda status,headers:statuses.append(int(status.split()[0])))))
                self.assertEqual(statuses,[expected],result)
                return result
            real=context.login['token']
            with patch('socket.socket.connect',side_effect=AssertionError('No live providers')):
                for demo in (False,True):
                    session=request('/demo/start',real,method='POST') if demo else context.login
                    token=session['token']; prefix='/demo' if demo else ''
                    months=request(prefix+'/budget-months',token,method='GET')['budget_months']
                    month=next(m['id'] for m in months if m['is_active'])
                    rows=request(prefix+f'/budget-months/{month}/transactions',token,method='GET')['transactions']
                    deposit=next(r for r in rows if r['transaction']['amount_cents']>0 and not r['transaction']['pending'] and not r['transaction']['ignored'] and r['categorization_status'] != 'refund')
                    txn=deposit['transaction']['id']
                    income=request(prefix+f'/budget-months/{month}/budget-detail',token,method='GET')['income'][0]
                    request(prefix+f'/transactions/{txn}/income',token,{'income_id':income['id'],'budget_month_id':month,'amount_cents':deposit['transaction']['amount_cents']})
                    request(prefix+f'/transactions/{txn}/income',token,{'income_id':income['id'],'budget_month_id':month,'amount_cents':deposit['transaction']['amount_cents']})
                    target=next(m['id'] for m in months if m['id']!=month)
                    preview=request(prefix+f'/transactions/{txn}/budget-month',token,{'budget_month_id':target,'preview':True})
                    request(prefix+f'/transactions/{txn}/budget-month',token,{'budget_month_id':target,'revision':preview['revision']})
                    if demo:
                        request(prefix+f'/transactions/{txn}/income',real,{'remove':True},expected=401)
                        request(f'/transactions/{txn}/income',token,{'remove':True},expected=401)
                        request(prefix+'/exit',token,method='POST')


if __name__ == '__main__':
    unittest.main()
