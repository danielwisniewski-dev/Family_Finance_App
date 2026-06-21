from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend.app.db import BudgetRepository
from backend.app.plaid import (
    InMemoryPlaidTokenStore,
    PlaidAccountSnapshot,
    PlaidConnectionService,
    PlaidIntegrationError,
    PlaidLinkToken,
    PlaidPublicTokenExchange,
    PlaidTransactionSnapshot,
    PlaidTransactionSync,
)
from backend.app.domain import WarningLevel


class PlaidAccountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = BudgetRepository(Path(self.temp_dir.name) / "test.sqlite")
        self.repository.initialize()
        self.household_id = self.repository.create_household("Plaid Test Household")
        self.budget_month_id = self.repository.create_budget_month(
            household_id=self.household_id,
            month="2026-06",
        )
        self.repository.add_payday(
            household_id=self.household_id,
            payday_date=date(2026, 6, 28),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def create_plaid_item(self) -> int:
        return self.repository.create_plaid_item(
            household_id=self.household_id,
            plaid_item_id="item-test",
            access_token_ref="token-ref-test",
            institution_name="Test Bank",
        )

    def test_two_checking_and_one_savings_can_drive_cash_reality_selection(self) -> None:
        plaid_item_id = self.create_plaid_item()
        self.repository.upsert_connected_account(
            budget_month_id=self.budget_month_id,
            plaid_item_id=plaid_item_id,
            plaid_account_id="checking-one",
            name="Main Checking",
            account_type="checking",
            balance_cents=75_000,
            included_in_cash_reality=True,
        )
        second_checking_id = self.repository.upsert_connected_account(
            budget_month_id=self.budget_month_id,
            plaid_item_id=plaid_item_id,
            plaid_account_id="checking-two",
            name="Bills Checking",
            account_type="checking",
            balance_cents=55_000,
            included_in_cash_reality=True,
        )
        savings_id = self.repository.upsert_connected_account(
            budget_month_id=self.budget_month_id,
            plaid_item_id=plaid_item_id,
            plaid_account_id="savings-one",
            name="Emergency Savings",
            account_type="savings",
            balance_cents=200_000,
            included_in_cash_reality=False,
        )

        checking_only = self.repository.get_summary(self.budget_month_id, today=date(2026, 6, 21))

        self.repository.set_account_included(savings_id, True)
        with_savings = self.repository.get_summary(self.budget_month_id, today=date(2026, 6, 21))

        self.repository.set_account_included(second_checking_id, False)
        after_excluding_second_checking = self.repository.get_summary(
            self.budget_month_id,
            today=date(2026, 6, 21),
        )

        self.assertEqual(checking_only.included_account_balance_cents, 130_000)
        self.assertEqual(with_savings.included_account_balance_cents, 330_000)
        self.assertEqual(after_excluding_second_checking.included_account_balance_cents, 275_000)

    def test_connected_account_inclusion_changes_safe_to_spend_cash_reality(self) -> None:
        plaid_item_id = self.create_plaid_item()
        savings_id = self.repository.upsert_connected_account(
            budget_month_id=self.budget_month_id,
            plaid_item_id=plaid_item_id,
            plaid_account_id="savings-one",
            name="Emergency Savings",
            account_type="savings",
            balance_cents=50_000,
            included_in_cash_reality=False,
        )
        self.repository.upsert_connected_account(
            budget_month_id=self.budget_month_id,
            plaid_item_id=plaid_item_id,
            plaid_account_id="checking-one",
            name="Main Checking",
            account_type="checking",
            balance_cents=40_000,
            included_in_cash_reality=True,
        )
        group_id = self.repository.add_budget_group(
            budget_month_id=self.budget_month_id,
            name="Food",
        )
        category_id = self.repository.add_category(
            budget_group_id=group_id,
            name="Eating Out",
            planned_cents=20_000,
        )
        self.repository.add_expected_bill(
            budget_month_id=self.budget_month_id,
            name="Insurance",
            amount_cents=30_000,
            due_on=date(2026, 6, 24),
        )

        excluded = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=category_id,
            purchase_amount_cents=5_000,
            today=date(2026, 6, 21),
            urgency="planned_want",
        )

        self.repository.set_account_included(savings_id, True)

        included = self.repository.safe_to_spend(
            budget_month_id=self.budget_month_id,
            category_id=category_id,
            purchase_amount_cents=5_000,
            today=date(2026, 6, 21),
            urgency="planned_want",
        )

        self.assertEqual(excluded.included_account_balance_cents, 40_000)
        self.assertEqual(excluded.cash_after_purchase_and_bills_cents, 5_000)
        self.assertEqual(excluded.warning_level, WarningLevel.CAUTION)
        self.assertEqual(included.included_account_balance_cents, 90_000)
        self.assertEqual(included.cash_after_purchase_and_bills_cents, 55_000)
        self.assertEqual(included.warning_level, WarningLevel.SAFE)

    def test_transaction_upsert_prevents_duplicate_plaid_transactions(self) -> None:
        plaid_item_id = self.create_plaid_item()
        account_id = self.repository.upsert_connected_account(
            budget_month_id=self.budget_month_id,
            plaid_item_id=plaid_item_id,
            plaid_account_id="checking-one",
            name="Main Checking",
            account_type="checking",
            balance_cents=75_000,
        )

        first = self.repository.upsert_plaid_transaction(
            cash_account_id=account_id,
            plaid_transaction_id="txn-duplicate",
            amount_cents=-2_450,
            occurred_on=date(2026, 6, 20),
            name="Grocery Store",
        )
        second = self.repository.upsert_plaid_transaction(
            cash_account_id=account_id,
            plaid_transaction_id="txn-duplicate",
            amount_cents=-2_500,
            occurred_on=date(2026, 6, 20),
            name="Grocery Store Final",
            merchant_name="Grocery Store",
        )

        transactions = self.repository.list_transactions(account_id)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.transaction_id, second.transaction_id)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].amount_cents, -2_500)
        self.assertEqual(transactions[0].name, "Grocery Store Final")

    def test_public_token_exchange_returns_sanitized_item_and_accounts(self) -> None:
        token_store = InMemoryPlaidTokenStore()
        service = PlaidConnectionService(
            self.repository,
            client=FakePlaidClient(),
            token_store=token_store,
        )

        result = service.exchange_public_token(
            household_id=self.household_id,
            budget_month_id=self.budget_month_id,
            public_token="public-sandbox-token",
        )

        self.assertNotIn("access_token", result.plaid_item)
        self.assertNotIn("access_token_ref", result.plaid_item)
        self.assertEqual(len(result.accounts), 3)
        self.assertEqual(result.accounts[0]["account_type"], "checking")
        self.assertFalse(result.accounts[2]["included_in_cash_reality"])

    def test_sync_errors_are_recorded_without_raising(self) -> None:
        token_store = InMemoryPlaidTokenStore()
        token_ref = token_store.store("raw-access-token")
        plaid_item_id = self.repository.create_plaid_item(
            household_id=self.household_id,
            plaid_item_id="item-failing",
            access_token_ref=token_ref,
        )
        service = PlaidConnectionService(
            self.repository,
            client=FailingPlaidClient(),
            token_store=token_store,
        )

        outcome = service.sync_balances(plaid_item_id)
        item = self.repository.get_plaid_item(plaid_item_id)
        errors = self.repository.list_plaid_sync_errors(plaid_item_id)

        self.assertFalse(outcome.success)
        self.assertEqual(outcome.error_code, "ITEM_LOGIN_REQUIRED")
        self.assertEqual(item.status, "error")
        self.assertEqual(item.last_error_code, "ITEM_LOGIN_REQUIRED")
        self.assertEqual(len(errors), 1)


class FakePlaidClient:
    def create_link_token(self, household_id: int) -> PlaidLinkToken:
        return PlaidLinkToken(
            link_token="link-token-test",
            expiration="2026-06-21T12:00:00Z",
            request_id="request-test",
        )

    def exchange_public_token(self, public_token: str) -> PlaidPublicTokenExchange:
        return PlaidPublicTokenExchange(
            access_token="fake-access-token",
            plaid_item_id="item-from-public-token",
            institution_id="ins-test",
            institution_name="Test Bank",
            accounts=(
                PlaidAccountSnapshot(
                    plaid_account_id="checking-one",
                    name="Main Checking",
                    account_type="checking",
                    balance_cents=75_000,
                    included_in_cash_reality=True,
                ),
                PlaidAccountSnapshot(
                    plaid_account_id="checking-two",
                    name="Bills Checking",
                    account_type="checking",
                    balance_cents=55_000,
                    included_in_cash_reality=True,
                ),
                PlaidAccountSnapshot(
                    plaid_account_id="savings-one",
                    name="Emergency Savings",
                    account_type="savings",
                    balance_cents=200_000,
                    included_in_cash_reality=False,
                ),
            ),
        )

    def get_balances(self, access_token: str) -> tuple[PlaidAccountSnapshot, ...]:
        return ()

    def sync_transactions(self, access_token: str, cursor: str | None) -> PlaidTransactionSync:
        return PlaidTransactionSync(
            transactions=(
                PlaidTransactionSnapshot(
                    plaid_transaction_id="txn-one",
                    plaid_account_id="checking-one",
                    amount_cents=-1_200,
                    occurred_on=date(2026, 6, 21),
                    name="Coffee",
                ),
            ),
            next_cursor="cursor-next",
        )


class FailingPlaidClient(FakePlaidClient):
    def get_balances(self, access_token: str) -> tuple[PlaidAccountSnapshot, ...]:
        raise PlaidIntegrationError("Plaid item needs user repair", "ITEM_LOGIN_REQUIRED")


if __name__ == "__main__":
    unittest.main()
