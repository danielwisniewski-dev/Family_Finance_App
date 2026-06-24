from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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

    @property
    def secret(self) -> str | None:
        return os.environ.get(self.secret_env_var)


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
    transactions: tuple[PlaidTransactionSnapshot, ...] = ()
    next_cursor: str | None = None
    modified_transactions: tuple[PlaidTransactionSnapshot, ...] = ()
    removed_transaction_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlaidSyncOutcome:
    success: bool
    sync_type: str
    synced_accounts: int = 0
    inserted_transactions: int = 0
    updated_transactions: int = 0
    removed_transactions: int = 0
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


class DatabasePlaidTokenStore:
    def __init__(self, repository: BudgetRepository):
        self.repository = repository

    def store(self, access_token: str) -> str:
        token_ref = f"plaid-token-ref-{uuid.uuid4()}"
        self.repository.store_plaid_access_token(token_ref, access_token)
        return token_ref

    def retrieve(self, access_token_ref: str) -> str:
        access_token = self.repository.retrieve_plaid_access_token(access_token_ref)
        if access_token is None:
            raise PlaidIntegrationError("Plaid access token is unavailable", "TOKEN_REF_MISSING")
        return access_token


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


class PlaidSandboxClient:
    SANDBOX_BASE_URL = "https://sandbox.plaid.com"
    ANDROID_PACKAGE_NAME = "com.familyfinance.app"

    def __init__(self, settings: PlaidSettings | None = None):
        self.settings = settings or PlaidSettings.from_env()

    def create_link_token(self, household_id: int) -> PlaidLinkToken:
        payload: dict[str, Any] = {
            "client_name": "Family Finance Sandbox",
            "country_codes": list(self.settings.country_codes),
            "language": "en",
            "products": list(self.settings.products),
            "user": {"client_user_id": f"household-{household_id}"},
            "android_package_name": self.ANDROID_PACKAGE_NAME,
        }
        if self.settings.redirect_uri:
            payload["redirect_uri"] = self.settings.redirect_uri
        result = self._request("/link/token/create", payload)
        return PlaidLinkToken(
            link_token=str(result["link_token"]),
            expiration=str(result["expiration"]),
            request_id=str(result.get("request_id", "")),
        )

    def exchange_public_token(self, public_token: str) -> PlaidPublicTokenExchange:
        if not public_token:
            raise PlaidIntegrationError("public_token is required", "PUBLIC_TOKEN_REQUIRED")
        exchange = self._request("/item/public_token/exchange", {"public_token": public_token})
        access_token = str(exchange["access_token"])
        plaid_item_id = str(exchange["item_id"])
        account_payload = self._request("/accounts/get", {"access_token": access_token})
        item = account_payload.get("item") or {}
        institution_id = optional_str(item.get("institution_id"))
        institution_name = self._institution_name(institution_id)
        return PlaidPublicTokenExchange(
            access_token=access_token,
            plaid_item_id=plaid_item_id,
            institution_id=institution_id,
            institution_name=institution_name,
            accounts=tuple(account_from_plaid_json(account) for account in account_payload.get("accounts", [])),
        )

    def get_balances(self, access_token: str) -> tuple[PlaidAccountSnapshot, ...]:
        payload = self._request("/accounts/get", {"access_token": access_token})
        return tuple(account_from_plaid_json(account) for account in payload.get("accounts", []))

    def sync_transactions(self, access_token: str, cursor: str | None) -> PlaidTransactionSync:
        added: list[PlaidTransactionSnapshot] = []
        modified: list[PlaidTransactionSnapshot] = []
        removed: list[str] = []
        next_cursor = cursor
        has_more = True
        while has_more:
            payload: dict[str, Any] = {"access_token": access_token}
            if next_cursor:
                payload["cursor"] = next_cursor
            result = self._request("/transactions/sync", payload)
            added.extend(transaction_from_plaid_json(item) for item in result.get("added", []))
            modified.extend(transaction_from_plaid_json(item) for item in result.get("modified", []))
            removed.extend(
                str(item["transaction_id"])
                for item in result.get("removed", [])
                if item.get("transaction_id")
            )
            next_cursor = optional_str(result.get("next_cursor"))
            has_more = bool(result.get("has_more", False))
        return PlaidTransactionSync(
            transactions=tuple(added),
            modified_transactions=tuple(modified),
            removed_transaction_ids=tuple(removed),
            next_cursor=next_cursor,
        )

    def _institution_name(self, institution_id: str | None) -> str | None:
        if not institution_id:
            return None
        try:
            payload = self._request(
                "/institutions/get_by_id",
                {
                    "institution_id": institution_id,
                    "country_codes": list(self.settings.country_codes),
                },
            )
        except PlaidIntegrationError:
            return None
        institution = payload.get("institution") or {}
        return optional_str(institution.get("name"))

    def _request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_sandbox_config()
        request_payload = {
            "client_id": self.settings.client_id,
            "secret": self.settings.secret,
        } | payload
        request = Request(
            self.SANDBOX_BASE_URL + path,
            data=json.dumps(request_payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = "Plaid Sandbox request failed"
            code = f"HTTP_{exc.code}"
            try:
                body = json.loads(exc.read().decode("utf-8"))
                code = optional_str(body.get("error_code")) or code
                message = optional_str(body.get("error_message")) or message
            except Exception:
                pass
            raise PlaidIntegrationError(redact_sensitive_text(message, self.settings), code) from exc
        except URLError as exc:
            raise PlaidIntegrationError("Could not reach Plaid Sandbox", "PLAID_NETWORK_ERROR") from exc
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PlaidIntegrationError("Plaid Sandbox returned an unexpected response", "PLAID_RESPONSE_ERROR") from exc

    def _require_sandbox_config(self) -> None:
        if self.settings.environment.casefold() != "sandbox":
            raise PlaidIntegrationError("Only PLAID_ENV=sandbox is supported in this app", "PLAID_ENV_NOT_SANDBOX")
        if not self.settings.client_id or not self.settings.secret:
            raise PlaidIntegrationError(
                "Plaid Sandbox is not configured: set PLAID_CLIENT_ID and PLAID_SECRET",
                "PLAID_CONFIG_MISSING",
            )
        if "transactions" not in {product.casefold() for product in self.settings.products}:
            raise PlaidIntegrationError("PLAID_PRODUCTS must include transactions", "PLAID_PRODUCTS_INVALID")
        if not self.settings.country_codes:
            raise PlaidIntegrationError("PLAID_COUNTRY_CODES must include US", "PLAID_COUNTRY_CODES_INVALID")


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
            if not is_supported_cash_account(account):
                continue
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
            synced = 0
            for account in accounts:
                if not is_supported_cash_account(account):
                    continue
                self.repository.update_connected_account_balance(
                    plaid_item_id=plaid_item_id,
                    plaid_account_id=account.plaid_account_id,
                    balance_cents=account.balance_cents,
                    available_balance_cents=account.available_balance_cents,
                    current_balance_cents=account.current_balance_cents,
                )
                synced += 1
            return PlaidSyncOutcome(success=True, sync_type="balance", synced_accounts=synced)
        except PlaidIntegrationError as exc:
            return self._record_sync_error(plaid_item_id, "balance", exc)

    def sync_transactions(self, plaid_item_id: int) -> PlaidSyncOutcome:
        try:
            item = self.repository.get_plaid_item(plaid_item_id)
            access_token = self.token_store.retrieve(item.access_token_ref)
            result = self.client.sync_transactions(access_token, item.sync_cursor)
            inserted = 0
            updated = 0
            removed = 0
            skipped = 0
            for transaction in result.transactions + result.modified_transactions:
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
            for plaid_transaction_id in result.removed_transaction_ids:
                if self.repository.mark_plaid_transaction_removed(plaid_transaction_id):
                    removed += 1
                else:
                    skipped += 1
            self.repository.update_plaid_item_cursor(plaid_item_id, result.next_cursor)
            return PlaidSyncOutcome(
                success=True,
                sync_type="transaction",
                inserted_transactions=inserted,
                updated_transactions=updated,
                removed_transactions=removed,
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
            error_message=sanitize_plaid_error(str(exc)),
        )
        return PlaidSyncOutcome(
            success=False,
            sync_type=sync_type,
            error_code=exc.code,
            error_message=sanitize_plaid_error(str(exc)),
        )


def build_plaid_service_from_env(repository: BudgetRepository) -> PlaidConnectionService:
    return PlaidConnectionService(
        repository,
        client=PlaidSandboxClient(),
        token_store=DatabasePlaidTokenStore(repository),
    )


def is_supported_cash_account(account: PlaidAccountSnapshot) -> bool:
    return account.account_type in {"checking", "savings"}


def default_account_inclusion(account: PlaidAccountSnapshot) -> bool:
    if account.included_in_cash_reality is not None:
        return account.included_in_cash_reality
    return account.account_type == "checking"


def account_from_plaid_json(account: dict[str, Any]) -> PlaidAccountSnapshot:
    subtype = optional_str(account.get("subtype"))
    plaid_type = optional_str(account.get("type"))
    account_type = subtype if plaid_type == "depository" and subtype in {"checking", "savings"} else "unsupported"
    balances = account.get("balances") or {}
    available = optional_money_cents(balances.get("available"))
    current = optional_money_cents(balances.get("current"))
    return PlaidAccountSnapshot(
        plaid_account_id=str(account["account_id"]),
        name=str(account.get("name") or account.get("official_name") or "Plaid account"),
        account_type=account_type,
        subtype=subtype,
        mask=optional_str(account.get("mask")),
        official_name=optional_str(account.get("official_name")),
        balance_cents=available if available is not None else current or 0,
        available_balance_cents=available,
        current_balance_cents=current,
    )


def transaction_from_plaid_json(transaction: dict[str, Any]) -> PlaidTransactionSnapshot:
    return PlaidTransactionSnapshot(
        plaid_transaction_id=str(transaction["transaction_id"]),
        plaid_account_id=str(transaction["account_id"]),
        amount_cents=-money_cents(transaction.get("amount", 0)),
        occurred_on=date.fromisoformat(str(transaction["date"])),
        name=str(transaction.get("name") or "Plaid transaction"),
        merchant_name=optional_str(transaction.get("merchant_name")),
        pending=bool(transaction.get("pending", False)),
        category_hint=plaid_category_hint(transaction),
    )


def plaid_category_hint(transaction: dict[str, Any]) -> str | None:
    personal = transaction.get("personal_finance_category") or {}
    for key in ("primary", "detailed"):
        value = optional_str(personal.get(key))
        if value:
            return value
    categories = transaction.get("category") or []
    if categories:
        return " / ".join(str(item) for item in categories if item)
    return None


def optional_money_cents(value: object) -> int | None:
    if value is None:
        return None
    return money_cents(value)


def money_cents(value: object) -> int:
    return int((Decimal(str(value)) * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))


def optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def sanitize_plaid_error(message: str) -> str:
    lowered = message.casefold()
    if "plaid sandbox is not configured" in lowered:
        return "Plaid Sandbox is not configured. Set Sandbox client ID and secret on the backend."
    if "only plaid_env=sandbox" in lowered:
        return "Only Plaid Sandbox is supported in this app."
    if "public_token is required" in lowered:
        return "Plaid public token is required."
    forbidden_terms = ("access_token", "access token", "token_ref", "token-ref", "api_key", "secret")
    if any(term in lowered for term in forbidden_terms):
        return "Plaid request failed; details were redacted."
    return redact_sensitive_text(message, PlaidSettings.from_env())


def redact_sensitive_text(message: str, settings: PlaidSettings) -> str:
    redacted = message
    sensitive_values = [
        settings.client_id,
        settings.secret,
        os.environ.get("OPENAI_API_KEY"),
    ]
    for value in sensitive_values:
        if value:
            redacted = redacted.replace(value, "[redacted]")
    return redacted


def link_token_to_dict(link_token: PlaidLinkToken) -> dict[str, object]:
    return asdict(link_token)


def plaid_connection_result_to_dict(result: PlaidConnectionResult) -> dict[str, object]:
    return {
        "plaid_item": result.plaid_item,
        "accounts": [dict(account) for account in result.accounts],
    }


def plaid_sync_outcome_to_dict(outcome: PlaidSyncOutcome) -> dict[str, object]:
    return asdict(outcome)
