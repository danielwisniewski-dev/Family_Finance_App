"""Synthetic live-path tests: no credentials or provider calls."""
import io
import json
import os
import tempfile
import unittest
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.bank_data import bank_status, reconcile_bank
from backend.app.db import BudgetRepository, transaction_detail_to_dict
from backend.app.hosted import Application
from backend.app.live_plaid import LivePlaidClient, LivePlaidService
from backend.app.plaid import PlaidIntegrationError, PlaidSettings
from backend.app.security import RuntimeSettings


class FakeBank(LivePlaidClient):
    def __init__(self):
        self.calls = []
        self.fail_accounts = False
        self.fail_sync = False
        self.balance = 500
        self.currency = "USD"
        self.available = 480
        self.updated = datetime.now(timezone.utc).isoformat()
        self.history = True
        self.added = []
        self.modified = []
        self.removed = []
        self.item_error = None

    def _request(self, path, payload):
        self.calls.append((path, payload))
        if path == "/link/token/create":
            return {"link_token": "synthetic-link", "expiration": "synthetic-expiry"}
        if path == "/item/public_token/exchange":
            return {"access_token": "synthetic-bank-secret", "item_id": "synthetic-item"}
        if path in {"/accounts/get", "/accounts/balance/get"}:
            if self.fail_accounts:
                raise PlaidIntegrationError("secret provider detail", "ITEM_LOGIN_REQUIRED")
            return {"item": {"institution_id": "ins_test_usaa"}, "accounts": [
                {"account_id": "synthetic-checking", "name": "Checking", "type": "depository", "subtype": "checking", "mask": "1234",
                 "balances": {"available": self.available, "current": self.balance, "iso_currency_code": self.currency}}]}
        if path == "/transactions/sync":
            if self.fail_sync:
                raise PlaidIntegrationError("raw token private", "ITEM_LOGIN_REQUIRED")
            return {"added": self.added, "modified": self.modified, "removed": [{"transaction_id": x} for x in self.removed],
                    "next_cursor": "cursor-" + str(len(self.calls)), "has_more": False,
                    "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE" if self.history else "NOT_READY"}
        if path == "/item/get":
            return {"item": {"error": self.item_error}, "status": {"transactions": {"last_successful_update": self.updated}}}
        raise AssertionError("Unexpected endpoint")


class Stage2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"PLAID_USAA_INSTITUTION_ID": "ins_test_usaa"})
        self.env.start(); self.addCleanup(self.env.stop)
        self.repo = BudgetRepository(Path(self.temp.name) / "synthetic.sqlite",
            RuntimeSettings(hosted=True, setup_code="s" * 40, encryption_key="k" * 40, plaid_enabled=True))
        self.repo.initialize()
        self.household = self.repo.create_household("Synthetic only")
        self.today = date(2026, 9, 12)
        clock = patch('backend.app.dates.household_today', return_value=self.today)
        clock.start(); self.addCleanup(clock.stop)
        self.month = self.repo.create_budget_month(household_id=self.household, month=self.today.strftime("%Y-%m"))
        self.repo.set_active_budget_month(household_id=self.household, budget_month_id=self.month)
        self.group = self.repo.add_budget_group(budget_month_id=self.month, name="Spending")
        self.food = self.repo.add_category(budget_group_id=self.group, name="Food", planned_cents=10000)
        self.repo.add_payday(household_id=self.household, payday_date=self.today + timedelta(days=5))
        self.bank = FakeBank()
        self.service = LivePlaidService(self.repo, self.bank)

    def connect(self):
        self.service.exchange_public_token(household_id=self.household, budget_month_id=self.month, public_token="public-production-synthetic")
        return self.repo.list_plaid_items(self.household)[0].id

    def transaction(self, key="purchase", amount=12, **extra):
        return {"transaction_id": key, "account_id": "synthetic-checking", "amount": amount,
                "date": self.today.isoformat(), "name": "Store", "pending": False, "iso_currency_code": "USD", **extra}

    def ready(self):
        item = self.connect()
        account = self.repo.list_accounts(self.month)[0]
        self.repo.set_account_included(account.id, True)
        state = bank_status(self.repo, self.month)
        self.assertTrue(state["can_reconcile"], state)
        reconcile_bank(self.repo, self.month, state["revision"])
        return item, account.id

    def test_connection_persists_encrypted_token_before_failed_account_fetch(self):
        self.bank.fail_accounts = True
        item = self.connect()
        with self.repo.connect() as conn:
            raw = conn.execute("SELECT access_token FROM plaid_access_tokens").fetchone()[0]
        self.assertTrue(raw.startswith("sealed:v1:"))
        self.assertNotIn("synthetic-bank-secret", raw)
        self.assertEqual(self.repo.list_accounts(self.month), [])
        self.service.create_link_token(self.household)
        self.assertEqual(self.bank.calls[-1][1]["access_token"], "synthetic-bank-secret")
        self.bank.fail_accounts = False
        self.assertTrue(self.service.sync_balances(item).success)
        self.assertEqual(len(self.repo.list_accounts(self.month)), 1)

    def test_initial_link_transactions_only_android_and_update_reuses_item(self):
        self.service.create_link_token(self.household)
        payload = self.bank.calls[-1][1]
        self.assertEqual(payload["products"], ["transactions"])
        self.assertEqual(payload["android_package_name"], "com.familyfinance.app")
        self.assertNotIn("redirect_uri", payload)
        self.connect()
        self.service.create_link_token(self.household)
        self.assertNotIn("products", self.bank.calls[-1][1])
        with self.assertRaises(PlaidIntegrationError):
            self.connect()
        self.assertEqual(sum(p == "/item/public_token/exchange" for p, _ in self.bank.calls), 1)

    def test_new_accounts_excluded_until_user_checks_for_manual_duplicates(self):
        self.connect()
        self.assertFalse(self.repo.list_accounts(self.month)[0].included_in_cash_reality)
        self.assertFalse(bank_status(self.repo, self.month)["ready"])

    def test_diagnostics_do_not_claim_live_spending_ready_before_reconciliation(self):
        with patch('backend.app.db.household_today', return_value=self.today):
            self.assertFalse(self.repo._safe_to_spend_diagnostic(self.month)["ok"])
            self.ready()
            self.assertTrue(self.repo._safe_to_spend_diagnostic(self.month)["ok"])

    def test_current_cash_and_category_limits_required_after_reconciliation(self):
        self.ready()
        result = self.repo.safe_to_spend(budget_month_id=self.month, category_id=self.food, purchase_amount_cents=15000, today=self.today)
        self.assertNotEqual(result.warning_level.value, "safe")
        self.assertEqual(result.included_account_balance_cents, 48000)
        self.assertIn("After upcoming bills", result.required_phrase)

    def test_stale_sync_failure_and_missing_available_balance_block_safe_to_spend(self):
        item, _ = self.ready()
        for change in ["UPDATE bank_sync_state SET balance_checked_at='2000-01-01'", "UPDATE bank_sync_state SET transaction_error=1", "UPDATE cash_accounts SET available_balance_cents=NULL"]:
            with self.repo.connect() as conn: conn.execute(change)
            with self.assertRaises(ValueError):
                self.repo.safe_to_spend(budget_month_id=self.month, category_id=self.food, purchase_amount_cents=1, today=self.today)
            self.service.sync_balances(item); self.service.sync_transactions(item)

    def test_provider_freshness_and_history_not_successful_download_time(self):
        self.bank.updated = "2000-01-01T00:00:00Z"
        item = self.connect()
        self.repo.set_account_included(self.repo.list_accounts(self.month)[0].id, True)
        self.assertFalse(bank_status(self.repo, self.month)["can_reconcile"])
        self.bank.updated = datetime.now(timezone.utc).isoformat(); self.bank.history = False
        self.service.sync_transactions(item)
        self.assertFalse(bank_status(self.repo, self.month)["history_complete"])

    def test_sync_error_is_redacted_and_preserves_data_and_cursor(self):
        self.bank.added = [self.transaction()]
        item = self.connect()
        before = self.repo.get_plaid_item(item).sync_cursor
        self.bank.fail_sync = True
        outcome = self.service.sync_transactions(item)
        self.assertFalse(outcome.success)
        self.assertNotIn("raw token", json.dumps(asdict(outcome)))
        self.assertEqual(self.repo.get_plaid_item(item).sync_cursor, before)
        self.assertEqual(len(self.repo.list_budget_transactions(self.month)), 1)

    def test_item_error_with_successful_http_response_blocks_stale_cached_sync(self):
        item,_=self.ready()
        cursor=self.repo.get_plaid_item(item).sync_cursor
        self.bank.item_error={"error_code":"ITEM_LOGIN_REQUIRED","error_message":"private provider text"}
        outcome=self.service.sync_transactions(item)
        self.assertFalse(outcome.success)
        self.assertNotIn("private provider text",outcome.error_message)
        self.assertEqual(self.repo.get_plaid_item(item).sync_cursor,cursor)
        self.assertFalse(bank_status(self.repo,self.month)["ready"])

    def test_pending_posted_modified_and_removed_never_double_count(self):
        self.bank.added = [self.transaction("pending", pending=True)]
        item = self.connect()
        tid = self.repo.list_budget_transactions(self.month)[0].transaction.id
        self.repo.assign_transaction_category(transaction_id=tid, category_id=self.food, reviewed=True)
        self.bank.added = [self.transaction("posted", 13, pending_transaction_id="pending")]
        self.bank.removed = ["pending"]
        self.service.sync_transactions(item); self.service.sync_transactions(item)
        self.assertEqual(len(self.repo.list_budget_transactions(self.month)), 1)
        self.assertEqual(self.repo.get_summary(self.month, self.today).categories[0].spent_cents, 1300)
        self.bank.added = []; self.bank.removed = ["posted"]
        self.service.sync_transactions(item)
        self.assertEqual(self.repo.get_summary(self.month, self.today).categories[0].spent_cents, 0)

    def test_month_rollover_keeps_account_id_and_filters_transaction_dates(self):
        self.bank.added = [self.transaction()]
        item = self.connect()
        account_id = self.repo.list_accounts(self.month)[0].id
        next_date = (self.today.replace(day=28) + timedelta(days=4)).replace(day=1)
        next_month = self.repo.create_budget_month(household_id=self.household, month=next_date.strftime("%Y-%m"))
        self.assertEqual(self.repo.list_accounts(next_month)[0].id, account_id)
        self.bank.added = [self.transaction("next-month", date=next_date.isoformat())]
        self.service.sync_transactions(item)
        self.assertEqual(len(self.repo.list_budget_transactions(self.month)), 1)
        self.assertEqual(len(self.repo.list_budget_transactions(next_month)), 1)
        with self.assertRaises(ValueError):
            self.repo.assign_transaction_category(transaction_id=self.repo.list_budget_transactions(next_month)[0].transaction.id, category_id=self.food)

    def test_posting_across_month_preserves_audit_and_requires_recategorization(self):
        self.bank.added = [self.transaction("pending", pending=True)]
        item = self.connect()
        tid = self.repo.list_budget_transactions(self.month)[0].transaction.id
        self.repo.assign_transaction_category(transaction_id=tid, category_id=self.food, reviewed=True)
        other = (self.today.replace(day=28) + timedelta(days=4)).replace(day=1)
        self.repo.create_budget_month(household_id=self.household, month=other.strftime("%Y-%m"))
        self.bank.added = [self.transaction("posted", pending_transaction_id="pending", date=other.isoformat())]
        self.service.sync_transactions(item)
        detail = self.repo.get_transaction_detail(tid)
        self.assertEqual(detail.assignments, ())
        self.assertTrue(detail.needs_review)
        self.assertEqual(self.repo.get_summary(self.month, self.today).categories[0].spent_cents, 0)

    def test_explicit_refund_credits_once_transfer_exclusion_and_amount_changes(self):
        self.bank.added = [self.transaction("purchase", 20), self.transaction("refund", -5)]
        item = self.connect()
        tx = {d.transaction.plaid_transaction_id:d.transaction.id for d in self.repo.list_budget_transactions(self.month)}
        self.repo.assign_transaction_category(transaction_id=tx["purchase"], category_id=self.food)
        self.repo.assign_transaction_refund(tx["refund"], self.food)
        self.repo.assign_transaction_refund(tx["refund"], self.food)
        self.assertEqual(self.repo.get_summary(self.month, self.today).categories[0].spent_cents, 1500)
        self.repo.set_transaction_ignored(transaction_id=tx["purchase"], ignored=True, reason="Transfer confirmed")
        self.assertEqual(self.repo.get_summary(self.month, self.today).categories[0].spent_cents, -500)
        self.bank.added=[]; self.bank.modified=[self.transaction("refund", -6)]
        self.service.sync_transactions(item)
        self.assertEqual(self.repo.get_summary(self.month, self.today).categories[0].spent_cents, 0)

    def test_unreviewed_and_reviewed_uncategorized_spending_blocks_readiness(self):
        self.bank.added=[self.transaction()]
        item=self.connect()
        self.repo.set_account_included(self.repo.list_accounts(self.month)[0].id, True)
        tid=self.repo.list_budget_transactions(self.month)[0].transaction.id
        self.repo.mark_transaction_reviewed(tid)
        self.assertEqual(bank_status(self.repo, self.month)["unreviewed_spending"], 1)
        self.repo.assign_transaction_category(transaction_id=tid, category_id=self.food, reviewed=True)
        self.assertTrue(bank_status(self.repo, self.month)["can_reconcile"])

    def test_reconciliation_rejects_changed_values(self):
        item,_=self.ready()
        revision=bank_status(self.repo,self.month)["revision"]
        self.bank.balance=600; self.bank.available=580
        self.service.sync_balances(item)
        with self.assertRaises(ValueError): reconcile_bank(self.repo,self.month,revision)

    def test_other_households_cannot_see_shared_accounts(self):
        self.connect()
        other=self.repo.create_household("Other synthetic")
        month=self.repo.create_budget_month(household_id=other,month=self.today.strftime("%Y-%m"))
        self.assertEqual(self.repo.list_accounts(month), [])
        self.assertEqual(self.repo.list_budget_transactions(month), [])
        self.assertFalse(bank_status(self.repo,month)["connected"])

    def test_inclusion_change_requires_reconciliation_and_manual_balance_cannot_override_bank(self):
        _,account=self.ready()
        with self.assertRaises(ValueError): self.repo.update_cash_account(account_id=account,balance_cents=999999)
        self.repo.set_account_included(account,False)
        self.repo.set_account_included(account,True)
        self.assertFalse(bank_status(self.repo,self.month)["reconciled"])

    def test_refund_undo_ignore_and_archived_category_preserve_correct_totals(self):
        self.bank.added=[self.transaction("refund",-5)]
        self.connect()
        tid=self.repo.list_budget_transactions(self.month)[0].transaction.id
        self.repo.assign_transaction_refund(tid,self.food)
        detail=self.repo.get_transaction_detail(tid)
        self.assertEqual(detail.categorization_status,"refund")
        self.assertEqual(detail.final_category_id,self.food)
        self.assertFalse(detail.needs_review)
        self.repo.remove_transaction_category(tid)
        self.assertEqual(self.repo.get_summary(self.month,self.today).categories[0].spent_cents,0)
        self.repo.assign_transaction_refund(tid,self.food)
        self.repo.set_transaction_ignored(transaction_id=tid,ignored=True)
        self.repo.set_transaction_ignored(transaction_id=tid,ignored=False)
        self.assertEqual(self.repo.get_summary(self.month,self.today).categories[0].spent_cents,0)
        self.repo.update_category(category_id=self.food, archived=True)
        with self.assertRaises(ValueError): self.repo.assign_transaction_refund(tid,self.food)

    def test_next_month_bill_is_reserved_before_payday(self):
        from backend.app.domain import ExpectedBill
        item,account=self.ready()
        october=self.repo.create_budget_month(household_id=self.household,month="2026-10")
        self.repo.add_expected_bill(budget_month_id=october,name="Rent",amount_cents=10000,due_on=date(2026,10,1))
        self.repo.add_payday(household_id=self.household,payday_date=date(2026,10,5))
        with patch('backend.app.dates.household_today',return_value=date(2026,9,30)):
            result=self.repo.safe_to_spend(budget_month_id=self.month,category_id=self.food,purchase_amount_cents=1,today=date(2026,9,30))
        self.assertEqual(result.bills_before_payday_cents,10000)

    def test_removed_transaction_reappears_for_review_without_old_assignment(self):
        self.bank.added=[self.transaction()]
        item=self.connect()
        tid=self.repo.list_budget_transactions(self.month)[0].transaction.id
        self.repo.assign_transaction_category(transaction_id=tid,category_id=self.food,reviewed=True)
        self.bank.added=[]; self.bank.removed=["purchase"]
        self.service.sync_transactions(item)
        self.bank.added=[self.transaction()]; self.bank.removed=[]
        self.service.sync_transactions(item)
        detail=self.repo.get_transaction_detail(tid)
        self.assertFalse(detail.transaction.ignored)
        self.assertTrue(detail.needs_review)
        self.assertEqual(detail.assignments,())

    def test_unknown_or_non_usd_balances_never_overwrite_last_good_data(self):
        item=self.connect()
        before=self.repo.list_accounts(self.month)[0].balance_cents
        for available,current,currency in [(None,None,"USD"),(500,500,"EUR")]:
            self.bank.available=available; self.bank.balance=current; self.bank.currency=currency
            self.assertFalse(self.service.sync_balances(item).success)
            self.assertEqual(self.repo.list_accounts(self.month)[0].balance_cents,before)

    def test_hosted_http_bank_smoke_shared_household_and_auth_boundaries(self):
        from http.client import HTTPConnection
        import threading
        from waitress import create_server
        for username in ["one", "two"]:
            self.repo.create_local_user(household_id=self.household,name=username,username=username,email=None,password="synthetic-password-"+username)
        self.bank.added=[self.transaction()]
        app=Application(self.repo); app.plaid=self.service
        server=create_server(app,host="127.0.0.1",port=0,threads=2)
        thread=threading.Thread(target=server.run,daemon=True); thread.start()
        def request(method,path,payload=None,token=None):
            connection=HTTPConnection("127.0.0.1",int(server.effective_port),timeout=10)
            headers={"Content-Type":"application/json"}
            if token: headers["Authorization"]="Bearer "+token
            connection.request(method,path,json.dumps(payload) if payload is not None else None,headers)
            response=connection.getresponse(); raw=response.read(); status=response.status
            connection.close()
            self.assertNotIn(b"synthetic-bank-secret",raw)
            self.assertNotIn(b"sealed:v1",raw)
            self.assertNotIn(b"plaid-token-ref",raw)
            return status,json.loads(raw)
        try:
            self.assertEqual(request("POST","/plaid/link-token",{})[0],401)
            tokens=[request("POST","/auth/login",{"username":u,"password":"synthetic-password-"+u})[1]["token"] for u in ["one","two"]]
            self.assertEqual(request("POST","/plaid/link-token",{},tokens[0])[0],201)
            status,linked=request("POST","/plaid/exchange-public-token",{"budget_month_id":self.month,"public_token":"public-production-synthetic"},tokens[0])
            self.assertEqual(status,201,linked)
            self.assertTrue(request("GET",f"/budget-months/{self.month}/bank-status",token=tokens[1])[1]["connected"])
            tx=self.repo.list_budget_transactions(self.month)[0].transaction.id
            self.assertEqual(request("PATCH",f"/transactions/{tx}/category",{"category_id":self.food,"reviewed":True},tokens[1])[0],200)
            account=self.repo.list_accounts(self.month)[0].id
            self.assertEqual(request("PATCH",f"/accounts/{account}",{"included_in_cash_reality":True},tokens[0])[0],200)
            _,state=request("GET",f"/budget-months/{self.month}/bank-status",token=tokens[1])
            self.assertTrue(state["can_reconcile"],state)
            self.assertEqual(state["accounts"][0]["balance_cents"],48000)
            self.assertTrue(state["accounts"][0]["included_in_cash_reality"])
            self.assertEqual(request("POST",f"/budget-months/{self.month}/bank-reconciliation",{"revision":state["revision"]},tokens[1])[0],200)
            result=request("POST","/safe-to-spend",{"budget_month_id":self.month,"category_id":self.food,"purchase_amount_cents":100,"today":self.today.isoformat()},tokens[0])
            self.assertEqual(result[0],200,result)
            self.assertIn("After upcoming bills",result[1]["required_phrase"])
            other=self.repo.create_household("Other")
            other_month=self.repo.create_budget_month(household_id=other,month="2026-09")
            self.assertEqual(request("GET",f"/budget-months/{other_month}/bank-status",token=tokens[0])[0],403)
            self.assertEqual(request("POST",f"/budget-months/{other_month}/bank-reconciliation",{"revision":state["revision"]},tokens[0])[0],403)
            self.bank.fail_sync=True
            failure=request("POST","/plaid/sync",{"plaid_item_id":linked["plaid_item"]["id"],"sync_type":"transaction"},tokens[0])
            self.assertFalse(failure[1]["success"])
            self.assertEqual(request("POST","/safe-to-spend",{"budget_month_id":self.month,"category_id":self.food,"purchase_amount_cents":100,"today":self.today.isoformat()},tokens[0])[0],400)
        finally:
            server.task_dispatcher.shutdown(); server.close(); thread.join(timeout=5)


class LiveClientTests(unittest.TestCase):
    def test_stage1_migration_preserves_existing_household_rows_sessions_and_encryption(self):
        from backend.app import migrations
        from backend.app.backup import create_backup, restore_backup
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"existing.sqlite"
            settings=RuntimeSettings(hosted=True,setup_code="s"*40,encryption_key="k"*40)
            repo=BudgetRepository(path,settings)
            with patch.object(migrations,"MIGRATIONS",migrations.MIGRATIONS[:2]): repo.initialize()
            household=repo.create_household("Existing",[{"name":"one","username":"one","password":"synthetic-password-one"},{"name":"two","username":"two","password":"synthetic-password-two"}])
            month=repo.create_budget_month(household_id=household,month="2026-09",included_account_balance_cents=12345)
            auth=repo.authenticate_local_user("one","synthetic-password-one")
            with repo.connect() as conn:
                tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_migrations'")]
                columns={t:[r[1] for r in conn.execute('PRAGMA table_info("'+t+'")')] for t in tables}
                before={t:[tuple(r) for r in conn.execute('SELECT * FROM "'+t+'" ORDER BY rowid')] for t in tables}
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0],2)
            archive=create_backup(path,Path(directory)/"before.ffbackup",settings.encryption_key)
            restore_backup(archive,Path(directory)/"verified.sqlite",settings.encryption_key)
            repo.initialize()
            with repo.connect() as conn:
                after={t:[tuple(r) for r in conn.execute('SELECT '+','.join('"'+c+'"' for c in columns[t])+' FROM "'+t+'" ORDER BY rowid')] for t in tables}
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0],migrations.LATEST_VERSION)
            self.assertEqual(before,after)
            self.assertIsNotNone(repo.auth_context_for_token(auth["token"]))
            self.assertEqual(repo.get_summary(month,date(2026,9,12)).included_account_balance_cents,12345)

    def test_pagination_mutation_restarts_original_cursor_and_discards_partial_batch(self):
        client=LivePlaidClient()
        page={"added":[],"modified":[],"removed":[],"has_more":True,"next_cursor":"partial"}
        final={**page,"has_more":False,"next_cursor":"done","transactions_update_status":"HISTORICAL_UPDATE_COMPLETE"}
        with patch.object(client,"_request",side_effect=[page,PlaidIntegrationError("changed","SYNC_UPDATES_DURING_PAGINATION"),final]) as request:
            result,complete=client.sync_transactions("synthetic", "original")
        self.assertEqual([c.args[1]["cursor"] for c in request.call_args_list],["original","partial","original"])
        self.assertEqual(result.next_cursor,"done"); self.assertTrue(complete)

    def test_configuration_is_explicit_and_rejects_auth_and_redirect(self):
        env={"FF_MODE":"hosted","FF_SETUP_CODE":"s"*40,"FF_ENCRYPTION_KEY":"k"*40,
             "FF_PLAID_ENABLED":"true","PLAID_ENV":"production","FF_PLAID_TRIAL_CONFIRMED":"true",
             "PLAID_CLIENT_ID":"synthetic","PLAID_SECRET":"synthetic","PLAID_USAA_INSTITUTION_ID":"ins_test"}
        with patch.dict(os.environ,env,clear=True):
            self.assertTrue(RuntimeSettings.from_env().plaid_enabled)
            for changed in [{"PLAID_PRODUCTS":"auth,transactions"},{"PLAID_REDIRECT_URI":"https://example.test"},
                            {"FF_PLAID_TRIAL_CONFIRMED":"false"},{"FF_MODE":"local"}]:
                with patch.dict(os.environ,changed), self.assertRaises(ValueError): RuntimeSettings.from_env()


if __name__ == '__main__': unittest.main()
