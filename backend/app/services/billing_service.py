from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import ConfigurationError, Settings
from app.models import BillingCheckoutCreate, PlatformUser
from app.utils.files import ensure_dir, read_json, write_json

try:
    import stripe
except ImportError:  # pragma: no cover - local/free billing mode does not need stripe
    stripe = None

ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


class BillingNotConfiguredError(RuntimeError):
    pass


class BillingAccountNotFoundError(KeyError):
    pass


@dataclass(frozen=True)
class BillingEntitlements:
    plan: str
    status: str
    max_projects: int
    max_active_jobs: int


@dataclass(frozen=True)
class BillingAccount:
    actor_id: str
    plan: str
    status: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    stripe_price_id: str | None
    current_period_end: datetime | None
    updated_at: datetime


class BillingService:
    """Stripe Billing foundation with file-backed local subscription state."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.accounts_dir = ensure_dir(settings.data_dir / "_billing")
        if stripe is not None:
            stripe.api_key = settings.stripe_api_key
            stripe.api_version = settings.stripe_api_version

    def configured(self) -> bool:
        return bool(self.settings.stripe_api_key and self.settings.stripe_pro_price_id)

    def metadata(self) -> dict[str, object]:
        return {
            "provider": "stripe",
            "configured": self.configured(),
            "api_version": self.settings.stripe_api_version,
            "pro_price_configured": bool(self.settings.stripe_pro_price_id),
            "webhook_configured": bool(self.settings.stripe_webhook_secret),
            "state_backend": "local",
        }

    def entitlements_for_user(self, user: PlatformUser | None) -> BillingEntitlements:
        account = self.get_account(user.id) if user else None
        if account and account.plan == "pro" and account.status in ACTIVE_SUBSCRIPTION_STATUSES:
            return BillingEntitlements(
                plan="pro",
                status=account.status,
                max_projects=self.settings.billing_pro_max_projects,
                max_active_jobs=self.settings.billing_pro_max_active_jobs,
            )
        return BillingEntitlements(
            plan="free",
            status=account.status if account else "free",
            max_projects=self.settings.usage_max_projects_per_user,
            max_active_jobs=self.settings.usage_max_active_jobs_per_user,
        )

    def create_checkout_session(self, user: PlatformUser, payload: BillingCheckoutCreate) -> dict[str, Any]:
        self._require_configured()
        price_id = payload.price_id or self.settings.stripe_pro_price_id
        if not price_id:
            raise BillingNotConfiguredError("Stripe price is not configured")
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=user.email,
            client_reference_id=user.id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=self.settings.stripe_success_url,
            cancel_url=self.settings.stripe_cancel_url,
            metadata={"user_id": user.id, "plan": payload.plan, "price_id": price_id},
            subscription_data={"metadata": {"user_id": user.id, "plan": payload.plan, "price_id": price_id}},
        )
        return {"id": session["id"], "url": session["url"]}

    def create_portal_session(self, user: PlatformUser) -> dict[str, Any]:
        self._require_configured()
        account = self.get_account(user.id)
        if not account or not account.stripe_customer_id:
            raise BillingAccountNotFoundError(user.id)
        session = stripe.billing_portal.Session.create(
            customer=account.stripe_customer_id,
            return_url=self.settings.stripe_portal_return_url,
        )
        return {"id": session["id"], "url": session["url"]}

    def construct_webhook_event(self, payload: bytes, signature: str | None) -> dict[str, Any]:
        if stripe is None:
            raise ConfigurationError("stripe is required for billing webhooks")
        if self.settings.stripe_webhook_secret:
            return stripe.Webhook.construct_event(payload, signature or "", self.settings.stripe_webhook_secret)
        if self.settings.app_env not in {"local", "test", "dev", "development"}:
            raise ConfigurationError("STRIPE_WEBHOOK_SECRET is required for non-local billing webhooks")
        return json.loads(payload.decode("utf-8"))

    def handle_webhook_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event_type = str(event.get("type") or "")
        obj = dict(event.get("data", {}).get("object", {}) or {})
        if event_type == "checkout.session.completed":
            return self._handle_checkout_completed(obj)
        if event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
            return self._handle_subscription_event(obj)
        return {"handled": False, "event_type": event_type}

    def get_account(self, actor_id: str) -> BillingAccount | None:
        path = self._account_file(actor_id)
        if not path.exists():
            return None
        return self._account_from_json(read_json(path))

    def list_accounts(self) -> list[BillingAccount]:
        accounts: list[BillingAccount] = []
        for path in sorted(self.accounts_dir.glob("billing_user_*.json")):
            try:
                accounts.append(self._account_from_json(read_json(path)))
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return sorted(accounts, key=lambda item: item.updated_at, reverse=True)

    def _handle_checkout_completed(self, obj: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(obj.get("metadata") or {})
        actor_id = str(metadata.get("user_id") or obj.get("client_reference_id") or "")
        if not actor_id:
            return {"handled": False, "event_type": "checkout.session.completed", "reason": "missing_user_id"}
        account = BillingAccount(
            actor_id=actor_id,
            plan=str(metadata.get("plan") or self._plan_for_price(metadata.get("price_id"))),
            status="checkout_completed",
            stripe_customer_id=_optional_str(obj.get("customer")),
            stripe_subscription_id=_optional_str(obj.get("subscription")),
            stripe_price_id=_optional_str(metadata.get("price_id")),
            current_period_end=None,
            updated_at=datetime.now(timezone.utc),
        )
        self.save_account(account)
        return {"handled": True, "event_type": "checkout.session.completed", "actor_id": actor_id}

    def _handle_subscription_event(self, obj: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(obj.get("metadata") or {})
        price_id = self._price_id_from_subscription(obj)
        actor_id = str(metadata.get("user_id") or "")
        if not actor_id:
            existing = self._find_by_customer_id(_optional_str(obj.get("customer")))
            actor_id = existing.actor_id if existing else ""
        if not actor_id:
            return {"handled": False, "event_type": "customer.subscription", "reason": "missing_user_id"}
        account = BillingAccount(
            actor_id=actor_id,
            plan=str(metadata.get("plan") or self._plan_for_price(price_id)),
            status=str(obj.get("status") or "unknown"),
            stripe_customer_id=_optional_str(obj.get("customer")),
            stripe_subscription_id=_optional_str(obj.get("id")),
            stripe_price_id=price_id,
            current_period_end=_datetime_from_timestamp(obj.get("current_period_end")),
            updated_at=datetime.now(timezone.utc),
        )
        self.save_account(account)
        return {"handled": True, "event_type": "customer.subscription", "actor_id": actor_id}

    def save_account(self, account: BillingAccount) -> None:
        write_json(self._account_file(account.actor_id), self._account_to_json(account))

    def account_payload(self, user: PlatformUser | None) -> dict[str, Any]:
        account = self.get_account(user.id) if user else None
        entitlements = self.entitlements_for_user(user)
        return {
            "account": self._account_to_json(account) if account else None,
            "entitlements": {
                "plan": entitlements.plan,
                "status": entitlements.status,
                "max_projects": entitlements.max_projects,
                "max_active_jobs": entitlements.max_active_jobs,
            },
            "provider": self.metadata(),
        }

    def _require_configured(self) -> None:
        if stripe is None:
            raise BillingNotConfiguredError("stripe package is not installed")
        if not self.configured():
            raise BillingNotConfiguredError("Stripe billing is not configured")

    def _find_by_customer_id(self, customer_id: str | None) -> BillingAccount | None:
        if not customer_id:
            return None
        for account in self.list_accounts():
            if account.stripe_customer_id == customer_id:
                return account
        return None

    def _plan_for_price(self, price_id: str | None) -> str:
        if price_id and price_id == self.settings.stripe_pro_price_id:
            return "pro"
        return "custom" if price_id else "free"

    def _price_id_from_subscription(self, obj: dict[str, Any]) -> str | None:
        items = obj.get("items")
        data = items.get("data") if isinstance(items, dict) else None
        if not data:
            return None
        first = data[0]
        if not isinstance(first, dict):
            return None
        price = first.get("price")
        if not isinstance(price, dict):
            return None
        return _optional_str(price.get("id"))

    def _account_file(self, actor_id: str) -> Path:
        return self.accounts_dir / f"billing_{actor_id}.json"

    def _account_to_json(self, account: BillingAccount) -> dict[str, Any]:
        return {
            "actor_id": account.actor_id,
            "plan": account.plan,
            "status": account.status,
            "stripe_customer_id": account.stripe_customer_id,
            "stripe_subscription_id": account.stripe_subscription_id,
            "stripe_price_id": account.stripe_price_id,
            "current_period_end": account.current_period_end.isoformat() if account.current_period_end else None,
            "updated_at": account.updated_at.isoformat(),
        }

    def _account_from_json(self, payload: dict[str, Any]) -> BillingAccount:
        return BillingAccount(
            actor_id=str(payload["actor_id"]),
            plan=str(payload["plan"]),
            status=str(payload["status"]),
            stripe_customer_id=_optional_str(payload.get("stripe_customer_id")),
            stripe_subscription_id=_optional_str(payload.get("stripe_subscription_id")),
            stripe_price_id=_optional_str(payload.get("stripe_price_id")),
            current_period_end=_datetime_from_iso(payload.get("current_period_end")),
            updated_at=_datetime_from_iso(payload.get("updated_at")) or datetime.now(timezone.utc),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _datetime_from_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _datetime_from_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result
