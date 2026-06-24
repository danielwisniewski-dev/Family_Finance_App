from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

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

    def test_credit_card_accounts_are_ignored_during_import(self) -> None:
        service = PlaidConnectionService(
            self.repository,
            client=CreditCardPlaidClient(),
            token_store=InMemoryPlaidTokenStore(),
        )

        result = service.exchange_public_token(
            household_id=self.household_id,
            budget_month_id=self.budget_month_id,
            public_token="public-sandbox-token",
        )
        accounts = self.repository.list_accounts(self.budget_month_id)

        self.assertEqual(len(result.accounts), 1)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].account_type, "checking")
        self.assertEqual(accounts[0].name, "Main Checking")

    def test_transaction_sync_inserts_added_transactions_and_persists_cursor(self) -> None:
        token_store = InMemoryPlaidTokenStore()
        token_ref = token_store.store("raw-access-token")
        plaid_item_id = self.create_connected_checking_item(token_ref)
        client = CursorPlaidClient()
        service = PlaidConnectionService(self.repository, client=client, token_store=token_store)

        outcome = service.sync_transactions(plaid_item_id)
        item = self.repository.get_plaid_item(plaid_item_id)
        account_id = self.repository.find_account_id_by_plaid_account(plaid_item_id, "checking-one")
        transactions = self.repository.list_transactions(account_id or 0)

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.inserted_transactions, 1)
        self.assertEqual(item.sync_cursor, "cursor-1")
        self.assertEqual(client.cursors, [None])
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].plaid_transaction_id, "txn-sync-one")

    def test_repeated_transaction_sync_does_not_duplicate_transactions_and_reuses_cursor(self) -> None:
        token_store = InMemoryPlaidTokenStore()
        token_ref = token_store.store("raw-access-token")
        plaid_item_id = self.create_connected_checking_item(token_ref)
        client = DuplicatePlaidClient()
        service = PlaidConnectionService(self.repository, client=client, token_store=token_store)

        first = service.sync_transactions(plaid_item_id)
        second = service.sync_transactions(plaid_item_id)
        account_id = self.repository.find_account_id_by_plaid_account(plaid_item_id, "checking-one")
        transactions = self.repository.list_transactions(account_id or 0)

        self.assertEqual(first.inserted_transactions, 1)
        self.assertEqual(second.updated_transactions, 1)
        self.assertEqual(client.cursors, [None, "cursor-dup-1"])
        self.assertEqual(len(transactions), 1)

    def test_modified_transactions_update_existing_records(self) -> None:
        token_store = InMemoryPlaidTokenStore()
        token_ref = token_store.store("raw-access-token")
        plaid_item_id = self.create_connected_checking_item(token_ref)
        client = ModifiedPlaidClient()
        service = PlaidConnectionService(self.repository, client=client, token_store=token_store)

        service.sync_transactions(plaid_item_id)
        outcome = service.sync_transactions(plaid_item_id)
        account_id = self.repository.find_account_id_by_plaid_account(plaid_item_id, "checking-one")
        transactions = self.repository.list_transactions(account_id or 0)

        self.assertEqual(outcome.updated_transactions, 1)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].amount_cents, -1_500)
        self.assertEqual(transactions[0].name, "Coffee Final")

    def test_removed_transactions_are_ignored_and_auditable(self) -> None:
        token_store = InMemoryPlaidTokenStore()
        token_ref = token_store.store("raw-access-token")
        plaid_item_id = self.create_connected_checking_item(token_ref)
        client = RemovedPlaidClient()
        service = PlaidConnectionService(self.repository, client=client, token_store=token_store)

        service.sync_transactions(plaid_item_id)
        outcome = service.sync_transactions(plaid_item_id)
        account_id = self.repository.find_account_id_by_plaid_account(plaid_item_id, "checking-one")
        transactions = self.repository.list_transactions(account_id or 0)
        detail = self.repository.get_transaction_detail(transactions[0].id)

        self.assertEqual(outcome.removed_transactions, 1)
        self.assertTrue(detail.transaction.ignored)
        self.assertEqual(detail.transaction.ignored_reason, "Removed by Plaid sync")
        self.assertTrue(any(event["event_type"] == "removed_by_plaid" for event in detail.audit_events))

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

    def test_sync_errors_are_sanitized_before_response_and_storage(self) -> None:
        token_store = InMemoryPlaidTokenStore()
        token_ref = token_store.store("raw-access-token")
        plaid_item_id = self.repository.create_plaid_item(
            household_id=self.household_id,
            plaid_item_id="item-secret-failing",
            access_token_ref=token_ref,
        )
        service = PlaidConnectionService(
            self.repository,
            client=SecretFailingPlaidClient(),
            token_store=token_store,
        )

        with patch.dict("os.environ", {"PLAID_SECRET": "super-secret", "OPENAI_API_KEY": "sk-secret"}):
            outcome = service.sync_balances(plaid_item_id)
        errors = self.repository.list_plaid_sync_errors(plaid_item_id)
        serialized = f"{outcome.error_message} {errors[0]['error_message']}"

        self.assertNotIn("super-secret", serialized)
        self.assertNotIn("sk-secret", serialized)
        self.assertNotIn("token-ref", serialized)
        self.assertIn("redacted", serialized)

    def create_connected_checking_item(self, token_ref: str) -> int:
        plaid_item_id = self.repository.create_plaid_item(
            household_id=self.household_id,
            plaid_item_id=f"item-{token_ref}",
            access_token_ref=token_ref,
        )
        self.repository.upsert_connected_account(
            budget_month_id=self.budget_month_id,
            plaid_item_id=plaid_item_id,
            plaid_account_id="checking-one",
            name="Main Checking",
            account_type="checking",
            balance_cents=75_000,
            included_in_cash_reality=True,
        )
        return plaid_item_id


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


class SecretFailingPlaidClient(FakePlaidClient):
    def get_balances(self, access_token: str) -> tuple[PlaidAccountSnapshot, ...]:
        raise PlaidIntegrationError(
            "Failed with secret super-secret, key sk-secret, and token-ref plaid-token-ref-test",
            "PLAID_SECRET_LEAK_TEST",
        )


class CreditCardPlaidClient(FakePlaidClient):
    def exchange_public_token(self, public_token: str) -> PlaidPublicTokenExchange:
        return PlaidPublicTokenExchange(
            access_token="fake-access-token",
            plaid_item_id="item-with-credit-card",
            institution_id="ins-test",
            institution_name="Test Bank",
            accounts=(
                PlaidAccountSnapshot(
                    plaid_account_id="checking-one",
                    name="Main Checking",
                    account_type="checking",
                    balance_cents=75_000,
                ),
                PlaidAccountSnapshot(
                    plaid_account_id="credit-one",
                    name="Sandbox Credit Card",
                    account_type="credit",
                    balance_cents=-10_000,
                ),
            ),
        )


class CursorPlaidClient(FakePlaidClient):
    def __init__(self) -> None:
        self.cursors: list[str | None] = []

    def sync_transactions(self, access_token: str, cursor: str | None) -> PlaidTransactionSync:
        self.cursors.append(cursor)
        return PlaidTransactionSync(
            transactions=(sync_transaction("txn-sync-one", -1_200, "Coffee"),),
            next_cursor="cursor-1",
        )


class DuplicatePlaidClient(CursorPlaidClient):
    def sync_transactions(self, access_token: str, cursor: str | None) -> PlaidTransactionSync:
        self.cursors.append(cursor)
        return PlaidTransactionSync(
            transactions=(sync_transaction("txn-duplicate-sync", -1_200, "Coffee"),),
            next_cursor=f"cursor-dup-{len(self.cursors)}",
        )


class ModifiedPlaidClient(CursorPlaidClient):
    def sync_transactions(self, access_token: str, cursor: str | None) -> PlaidTransactionSync:
        self.cursors.append(cursor)
        if cursor is None:
            return PlaidTransactionSync(
                transactions=(sync_transaction("txn-modified", -1_200, "Coffee Pending"),),
                next_cursor="cursor-mod-1",
            )
        return PlaidTransactionSync(
            modified_transactions=(sync_transaction("txn-modified", -1_500, "Coffee Final"),),
            next_cursor="cursor-mod-2",
        )


class RemovedPlaidClient(CursorPlaidClient):
    def sync_transactions(self, access_token: str, cursor: str | None) -> PlaidTransactionSync:
        self.cursors.append(cursor)
        if cursor is None:
            return PlaidTransactionSync(
                transactions=(sync_transaction("txn-removed", -1_200, "Coffee"),),
                next_cursor="cursor-rem-1",
            )
        return PlaidTransactionSync(
            removed_transaction_ids=("txn-removed",),
            next_cursor="cursor-rem-2",
        )


def sync_transaction(plaid_transaction_id: str, amount_cents: int, name: str) -> PlaidTransactionSnapshot:
    return PlaidTransactionSnapshot(
        plaid_transaction_id=plaid_transaction_id,
        plaid_account_id="checking-one",
        amount_cents=amount_cents,
        occurred_on=date(2026, 6, 21),
        name=name,
    )


if __name__ == "__main__":
    unittest.main()
