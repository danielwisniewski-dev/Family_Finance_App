import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend.app.db import BudgetRepository


class BillBudgetMatchTests(unittest.TestCase):
    def test_only_confirmed_single_bill_payments_change_both_amounts(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = BudgetRepository(Path(directory) / "bill.sqlite")
            repo.initialize()
            household = repo.create_household("Synthetic")
            today = date(2026, 11, 24)
            month = repo.create_budget_month(household_id=household, month="2026-11")
            group = repo.add_budget_group(budget_month_id=month, name="Home")
            category = repo.add_category(budget_group_id=group, name="Electric", planned_cents=10000)
            ordinary = repo.add_category(budget_group_id=group, name="Groceries", planned_cents=10000)
            bill = repo.add_expected_bill(budget_month_id=month, name="Electricity", amount_cents=10000,
                                          due_on=today, budget_category_id=category)
            account = repo.add_cash_account(budget_month_id=month, name="Checking", account_type="checking", balance_cents=50000)

            def assign(key, amount, category_id, pending=False):
                payment = repo.upsert_plaid_transaction(cash_account_id=account, plaid_transaction_id=key,
                                                      amount_cents=-amount, occurred_on=today, name=key, pending=pending)
                repo.assign_transaction_category(transaction_id=payment.transaction_id, category_id=category_id)
                return payment.transaction_id

            self.assertIsNone(repo.match_bill_budget(assign("ordinary", 8000, ordinary), household, None))
            pending = assign("electric", 8600, category, pending=True)
            self.assertIsNone(repo.match_bill_budget(pending, household, None))
            payment = assign("electric", 8600, category)
            offer = repo.match_bill_budget(payment, household, None)
            self.assertEqual((offer["bill_amount_cents"], offer["planned_cents"], offer["expense_cents"]), (10000, 10000, 8600))
            self.assertEqual(repo.get_budget_detail(month, today)["expected_bills"][0]["amount_cents"], 10000)
            other = repo.create_household("Other")
            with self.assertRaises(PermissionError):
                repo.match_bill_budget(payment, other, None, offer)
            repo.update_expected_bill(bill_id=bill, amount_cents=9900)
            with self.assertRaisesRegex(ValueError, "changed"):
                repo.match_bill_budget(payment, household, None, offer)
            repo.match_bill_budget(payment, household, None, repo.match_bill_budget(payment, household, None))
            self.assertIsNone(repo.match_bill_budget(payment, household, None))
            assign("electric", 11700, category)
            higher = repo.match_bill_budget(payment, household, None)
            self.assertEqual((higher["bill_amount_cents"], higher["planned_cents"], higher["expense_cents"]), (8600, 8600, 11700))
            repo.match_bill_budget(payment, household, None, higher)
            detail = repo.get_budget_detail(month, today)
            self.assertEqual(detail["expected_bills"][0]["amount_cents"], 11700)
            self.assertEqual(next(c["planned_cents"] for g in detail["groups"] for c in g["categories"] if c["id"] == category), 11700)
            self.assertFalse(detail["expected_bills"][0]["paid"])
            copy = repo.create_budget_month(household_id=household, month="2026-12", copy_from_budget_month_id=month)
            self.assertNotEqual(repo.get_budget_detail(copy, today)["expected_bills"][0]["budget_category_id"], category)
