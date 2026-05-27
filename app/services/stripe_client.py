"""Stripe SDK wrapper.

Lazy init pattern matching app/services/analytics_posthog.py.

Configuration via env vars:
  STRIPE_API_KEY:              sk_test_... or sk_live_...
  STRIPE_PRICE_ID_MONTHLY:     price_... for Premium Monthly $6
  STRIPE_PRICE_ID_ANNUAL:      price_... for Premium Annual $40
  STRIPE_WEBHOOK_SECRET:       whsec_..., issued after webhook
                               endpoint registered in Stripe
  STRIPE_DISABLED:             '1' / 'true' to disable (tests/CI)

7-day trial is configured per-Checkout-Session via
subscription_data.trial_period_days for the annual plan only,
NOT baked into the Price object — keeps trial duration tunable
in code without touching Stripe configuration.

All public functions log + swallow on error; analytics-style
failure handling. Webhook signature mismatch is the one place
we WARN loudly because it's a real signal.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_stripe: Optional[Any] = None
_initialized: bool = False
_disabled: bool = False


def _get_client() -> Optional[Any]:
    """Return the stripe module with api_key set, or None if disabled."""
    global _stripe, _initialized, _disabled
    if _initialized:
        return None if _disabled else _stripe

    _initialized = True

    if os.getenv("STRIPE_DISABLED", "").lower() in ("1", "true", "yes"):
        logger.info("STRIPE_DISABLED set — Stripe integration disabled")
        _disabled = True
        return None

    api_key = os.getenv("STRIPE_API_KEY", "").strip()
    if not api_key:
        logger.warning("STRIPE_API_KEY missing — Stripe integration disabled")
        _disabled = True
        return None

    try:
        import stripe
    except ImportError:
        logger.warning("stripe Python SDK not installed — disabled")
        _disabled = True
        return None

    stripe.api_key = api_key
    stripe.api_version = "2025-03-31.basil"
    _stripe = stripe
    logger.info(
        "Stripe SDK initialized (mode=%s, api_version=%s)",
        "live" if api_key.startswith("sk_live_") else "test",
        stripe.api_version,
    )
    return _stripe


def _resolve_price_id(plan: str) -> Optional[str]:
    if plan == "monthly":
        return os.getenv("STRIPE_PRICE_ID_MONTHLY", "").strip() or None
    if plan == "annual":
        return os.getenv("STRIPE_PRICE_ID_ANNUAL", "").strip() or None
    return None


def ensure_customer(db_client, user_data: dict) -> Optional[str]:
    """Idempotent. Reuse existing stripe_customer_id if present.

    Otherwise create a new Stripe Customer with metadata anchoring it to
    family_id / username / uid, persist the new customer.id to the user
    record + in-memory cache, and return it.

    Race-tolerant: two concurrent calls might both create customers; the
    second persistent write wins. Same race semantics as
    _ensure_family_id. The orphaned customer can be reconciled offline.
    """
    existing = user_data.get("stripe_customer_id")
    if existing:
        return existing

    stripe = _get_client()
    if stripe is None:
        return None

    family_id = user_data.get("family_id") or ""
    username = user_data.get("username") or ""
    uid = user_data.get("uid") or user_data.get("id") or ""

    try:
        customer = stripe.Customer.create(
            metadata={
                "family_id": family_id,
                "username": username,
                "uid": uid,
            },
        )
        customer_id = customer.id
    except Exception as e:
        logger.warning("Stripe Customer.create failed for uid=%s: %s", uid, e)
        return None

    try:
        db_client.collection("users").document(uid).update(
            {"stripe_customer_id": customer_id}
        )
        from app.dependencies import _local_users
        if uid in _local_users:
            _local_users[uid]["stripe_customer_id"] = customer_id
        user_data["stripe_customer_id"] = customer_id
    except Exception as e:
        logger.warning(
            "Persist stripe_customer_id failed for uid=%s: %s", uid, e
        )

    return customer_id


def create_checkout_session(
    customer_id: str,
    plan: str,
    family_id: str,
    success_url: str,
    cancel_url: str,
) -> Optional[str]:
    """Create a Stripe Checkout session, return the hosted URL.

    Annual plan gets a 7-day trial via subscription_data.trial_period_days.
    Monthly plan has no trial. Trial duration lives here — change in code,
    not Stripe Dashboard.
    """
    stripe = _get_client()
    if stripe is None:
        return None

    price_id = _resolve_price_id(plan)
    if not price_id:
        logger.warning("No price_id configured for plan=%s", plan)
        return None

    params = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": family_id,
        "metadata": {"family_id": family_id, "plan": plan},
    }

    if plan == "annual":
        params["subscription_data"] = {"trial_period_days": 7}

    try:
        session = stripe.checkout.Session.create(**params)
        return session.url
    except Exception as e:
        logger.warning("Stripe checkout.Session.create failed: %s", e)
        return None


def verify_webhook(payload_bytes: bytes, sig_header: str) -> Optional[Any]:
    """Verify the webhook signature, return the parsed Event.

    Returns None on bad signature, missing secret, missing SDK, or any
    other failure. Logs WARN on signature mismatch — that's a real
    signal, not a swallowed analytics failure.
    """
    stripe = _get_client()
    if stripe is None:
        return None

    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        logger.warning(
            "STRIPE_WEBHOOK_SECRET missing — cannot verify webhooks"
        )
        return None

    try:
        return stripe.Webhook.construct_event(payload_bytes, sig_header, secret)
    except Exception as e:
        logger.warning("Stripe webhook verification failed: %s", e)
        return None
