from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from .db import BudgetRepository, account_to_dict, plaid_item_to_public_dict


class PlaidIntegrationError(Exception):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PlaidSettings:
    client_id: str | None
    secret_env_var: str
    environment: str
    products: tuple[str, ...]
    country_codes: tuple[str, ...]
    redirect_uri: str | None

    @classmethod
    def from_env(cls) -> PlaidSettings:
        products = tuple(
            item.strip()
            for item in os.environ.get("PLAID_PRODUCTS", "transactions").split(",")
            if item.strip()
        )
        country_codes = tuple(
            item.strip()
            for item in os.environ.get("PLAID_COUNTRY_CODES", "US").split(",")
            if item.strip()
        )
        return cls(
            client_id=os.environ.get("PLAID_CLIENT_ID"),
            secret_env_var="PLAID_SECRET",
            environment=os.environ.get("PLAID_ENV", "sandbox"),
            products=products,
            country_codes=country_codes,
            redirect_uri=os.environ.get("PLAID_REDIRECT_URI"),
        )


@dataclass(frozen=True)
class PlaidLinkToken:
    link_token: str
    expiration: str
    request_id: str


@dataclass(frozen=True)
class PlaidAccountSnapshot:
    plaid_account_id: str
    name: str
    account_type: str
    balance_cents: int
    subtype: str | None = None
    mask: str | None = None
    official_name: str | None = None
    available_balance_cents: int | None = None
    current_balance_cents: int | None = None
    included_in_cash_reality: bool | None = None


@dataclass(frozen=True)
class PlaidPublicTokenExchange:
    access_token: str
    plaid_item_id: str
    institution_id: str | None
    institution_name: str | None
    accounts: tuple[PlaidAccountSnapshot, ...] = ()


@dataclass(frozen=True)
class PlaidTransactionSnapshot:
    plaid_transaction_id: str
    plaid_account_id: str
    amount_cents: int
    occurred_on: date
    name: str
    merchant_name: str | None = None
    pending: bool = False
    category_hint: str | None = None


@dataclass(frozen=True)
class PlaidTransactionSync:
    transactions: tuple[PlaidTransactionSnapshot, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class PlaidSyncOutcome:
    success: bool
    sync_type: str
    synced_accounts: int = 0
    inserted_transactions: int = 0
    updated_transactions: int = 0
    skipped_transactions: int = 0
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class PlaidConnectionResult:
    plaid_item: dict[str, object]
    accounts: tuple[dict[str, object], ...]


class PlaidClient(Protocol):
    def create_link_token(self, household_id: int) -> PlaidLinkToken:
        raise NotImplementedError

    def exchange_public_token(self, public_token: str) -> PlaidPublicTokenExchange:
        raise NotImplementedError

    def get_balances(self, access_token: str) -> tuple[PlaidAccountSnapshot, ...]:
        raise NotImplementedError

    def sync_transactions(self, access_token: str, cursor: str | None) -> PlaidTransactionSync:
        raise NotImplementedError


class PlaidTokenStore(Protocol):
    def store(self, access_token: str) -> str:
        raise NotImplementedError

    def retrieve(self, access_token_ref: str) -> str:
        raise NotImplementedError


class InMemoryPlaidTokenStore:
    def __init__(self) -> None:
        self._tokens_by_ref: dict[str, str] = {}

    def store(self, access_token: str) -> str:
        token_ref = f"plaid-token-ref-{uuid.uuid4()}"
        self._tokens_by_ref[token_ref] = access_token
        return token_ref

    def retrieve(self, access_token_ref: str) -> str:
        try:
            return self._tokens_by_ref[access_token_ref]
        except KeyError as exc:
            raise PlaidIntegrationError("Plaid access token reference is unavailable", "TOKEN_REF_MISSING") from exc


class PlaceholderPlaidClient:
    def __init__(self, settings: PlaidSettings | None = None):
        self.settings = settings or PlaidSettings.from_env()

    def create_link_token(self, household_id: int) -> PlaidLinkToken:
        expiration = datetime.now(timezone.utc) + timedelta(minutes=30)
        return PlaidLinkToken(
            link_token=f"link-token-placeholder-{uuid.uuid4()}",
            expiration=expiration.isoformat().replace("+00:00", "Z"),
            request_id=str(uuid.uuid4()),
        )

    def exchange_public_token(self, public_token: str) -> PlaidPublicTokenExchange:
        if not public_token:
            raise PlaidIntegrationError("public_token is required", "PUBLIC_TOKEN_REQUIRED")
        return PlaidPublicTokenExchange(
            access_token=f"access-token-placeholder-{uuid.uuid4()}",
            plaid_item_id=f"item-placeholder-{uuid.uuid4()}",
            institution_id=None,
            institution_name=None,
            accounts=(),
        )

    def get_balances(self, access_token: str) -> tuple[PlaidAccountSnapshot, ...]:
        raise PlaidIntegrationError("Plaid balance sync client is not configured", "PLAID_CLIENT_PLACEHOLDER")

    def sync_transactions(self, access_token: str, cursor: str | None) -> PlaidTransactionSync:
        raise PlaidIntegrationError("Plaid transaction sync client is not configured", "PLAID_CLIENT_PLACEHOLDER")


class PlaidConnectionService:
    def __init__(
        self,
        repository: BudgetRepository,
        client: PlaidClient | None = None,
        token_store: PlaidTokenStore | None = None,
    ):
        self.repository = repository
        self.client = client or PlaceholderPlaidClient()
        self.token_store = token_store or InMemoryPlaidTokenStore()

    def create_link_token(self, household_id: int) -> PlaidLinkToken:
        return self.client.create_link_token(household_id)

    def exchange_public_token(
        self,
        *,
        household_id: int,
        budget_month_id: int,
        public_token: str,
    ) -> PlaidConnectionResult:
        exchange = self.client.exchange_public_token(public_token)
        token_ref = self.token_store.store(exchange.access_token)
        plaid_item_row_id = self.repository.create_plaid_item(
            household_id=household_id,
            plaid_item_id=exchange.plaid_item_id,
            access_token_ref=token_ref,
            institution_id=exchange.institution_id,
            institution_name=exchange.institution_name,
        )
        account_ids: list[int] = []
        for account in exchange.accounts:
            account_ids.append(
                self.repository.upsert_connected_account(
                    budget_month_id=budget_month_id,
                    plaid_item_id=plaid_item_row_id,
                    plaid_account_id=account.plaid_account_id,
                    name=account.name,
                    account_type=account.account_type,
                    subtype=account.subtype,
                    mask=account.mask,
                    official_name=account.official_name,
                    balance_cents=account.balance_cents,
                    available_balance_cents=account.available_balance_cents,
                    current_balance_cents=account.current_balance_cents,
                    included_in_cash_reality=default_account_inclusion(account),
                )
            )
        accounts = tuple(
            account_to_dict(account)
            for account in self.repository.list_accounts(budget_month_id)
            if account.id in account_ids
        )
        return PlaidConnectionResult(
            plaid_item=plaid_item_to_public_dict(self.repository.get_plaid_item(plaid_item_row_id)),
            accounts=accounts,
        )

    def sync_balances(self, plaid_item_id: int) -> PlaidSyncOutcome:
        try:
            item = self.repository.get_plaid_item(plaid_item_id)
            access_token = self.token_store.retrieve(item.access_token_ref)
            accounts = self.client.get_balances(access_token)
            for account in accounts:
                self.repository.update_connected_account_balance(
                    plaid_item_id=plaid_item_id,
                    plaid_account_id=account.plaid_account_id,
                    balance_cents=account.balance_cents,
                    available_balance_cents=account.available_balance_cents,
                    current_balance_cents=account.current_balance_cents,
                )
            return PlaidSyncOutcome(success=True, sync_type="balance", synced_accounts=len(accounts))
        except PlaidIntegrationError as exc:
            return self._record_sync_error(plaid_item_id, "balance", exc)

    def sync_transactions(self, plaid_item_id: int) -> PlaidSyncOutcome:
        try:
            item = self.repository.get_plaid_item(plaid_item_id)
            access_token = self.token_store.retrieve(item.access_token_ref)
            result = self.client.sync_transactions(access_token, item.sync_cursor)
            inserted = 0
            updated = 0
            skipped = 0
            for transaction in result.transactions:
                account_id = self.repository.find_account_id_by_plaid_account(
                    plaid_item_id,
                    transaction.plaid_account_id,
                )
                if account_id is None:
                    skipped += 1
                    continue
                upsert = self.repository.upsert_plaid_transaction(
                    cash_account_id=account_id,
                    plaid_transaction_id=transaction.plaid_transaction_id,
                    amount_cents=transaction.amount_cents,
                    occurred_on=transaction.occurred_on,
                    name=transaction.name,
                    merchant_name=transaction.merchant_name,
                    pending=transaction.pending,
                    category_hint=transaction.category_hint,
                )
                if upsert.created:
                    inserted += 1
                else:
                    updated += 1
            self.repository.update_plaid_item_cursor(plaid_item_id, result.next_cursor)
            return PlaidSyncOutcome(
                success=True,
                sync_type="transaction",
                inserted_transactions=inserted,
                updated_transactions=updated,
                skipped_transactions=skipped,
            )
        except PlaidIntegrationError as exc:
            return self._record_sync_error(plaid_item_id, "transaction", exc)

    def _record_sync_error(
        self,
        plaid_item_id: int,
        sync_type: str,
        exc: PlaidIntegrationError,
    ) -> PlaidSyncOutcome:
        self.repository.record_plaid_sync_error(
            plaid_item_id=plaid_item_id,
            sync_type=sync_type,
            error_code=exc.code,
            error_message=str(exc),
        )
        return PlaidSyncOutcome(
            success=False,
            sync_type=sync_type,
            error_code=exc.code,
            error_message=str(exc),
        )


def default_account_inclusion(account: PlaidAccountSnapshot) -> bool:
    if account.included_in_cash_reality is not None:
        return account.included_in_cash_reality
    return account.account_type == "checking"


def link_token_to_dict(link_token: PlaidLinkToken) -> dict[str, object]:
    return asdict(link_token)


def plaid_connection_result_to_dict(result: PlaidConnectionResult) -> dict[str, object]:
    return {
        "plaid_item": result.plaid_item,
        "accounts": [dict(account) for account in result.accounts],
    }


def plaid_sync_outcome_to_dict(outcome: PlaidSyncOutcome) -> dict[str, object]:
    return asdict(outcome)
