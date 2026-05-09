"""Billing endpoints: Stripe checkout + webhook.

Phase 0 step 1.4b. Test mode only — live mode flip after 1.4d.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.dependencies import (
    get_current_user,
    get_db_client,
    _ensure_subscription_fields,
    _local_users,
)
from app.services.stripe_client import (
    ensure_customer,
    create_checkout_session,
    verify_webhook,
)
from app.services.analytics_posthog import emit_event as ph_emit
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

BILLING_DB_PATH = Path("data/billing.db")


# ── Models ─────────────────────────────────────────────────────


class StartCheckoutRequest(BaseModel):
    plan: str = Field(..., pattern="^(monthly|annual)$")


# ── Idempotency store ──────────────────────────────────────────


def _open_billing_db() -> sqlite3.Connection:
    BILLING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(BILLING_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    # TODO(1.4c): periodic pruning — DELETE WHERE status='processed' AND
    # received_at < datetime('now', '-30 days') when row count grows.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stripe_webhook_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            received_at TEXT NOT NULL,
            processed_at TEXT,
            status TEXT NOT NULL DEFAULT 'received',
            error TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_swh_received_at "
        "ON stripe_webhook_events(received_at)"
    )
    conn.commit()
    return conn


# ── Customer -> user lookup ────────────────────────────────────


def _find_user_by_customer(db_client, customer_id: str) -> Optional[dict]:
    """Find user record by stripe_customer_id.

    TODO(1.4c): replace LocalStore scan with an index when user count
    grows substantially. O(n) over _local_users is acceptable at current
    scale (~hundreds of users); becomes a hotspot above ~10k.
    """
    for uid, user in _local_users.items():
        if user.get("stripe_customer_id") == customer_id:
            try:
                doc = db_client.collection("users").document(uid).get()
                if doc.exists:
                    data = doc.to_dict()
                    data.setdefault("uid", uid)
                    return data
            except Exception:
                pass
            return {**user, "uid": uid}
    return None


def _persist_user_update(db_client, uid: str, fields: dict) -> None:
    try:
        db_client.collection("users").document(uid).update(fields)
        if uid in _local_users:
            _local_users[uid].update(fields)
    except Exception as e:
        logger.warning("user record update failed uid=%s: %s", uid, e)


def _iso_from_ts(ts: Optional[int]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


# ── Event handlers ─────────────────────────────────────────────


def _handle_sub_created(db_client, event) -> None:
    sub = event["data"]["object"]
    customer_id = sub.get("customer")
    user = _find_user_by_customer(db_client, customer_id)
    if not user:
        logger.warning(
            "subscription.created: no user found for customer=%s", customer_id
        )
        return

    family_id = user.get("family_id") or ""
    fields = {
        "stripe_subscription_id": sub.get("id"),
        "subscription_status": sub.get("status") or "active",
        "subscription_tier": "premium",
        "current_period_end": _iso_from_ts(sub.get("current_period_end")),
    }

    # Capture billing_email from the customer object.
    try:
        from app.services.stripe_client import _get_client
        stripe = _get_client()
        if stripe is not None:
            cust = stripe.Customer.retrieve(customer_id)
            email = cust.get("email") if cust else None
            if email:
                fields["billing_email"] = email
    except Exception as e:
        logger.info("billing_email fetch skipped: %s", e)

    _persist_user_update(db_client, user["uid"], fields)

    ph_emit(
        family_id,
        "subscription_started",
        {
            "plan": (sub.get("metadata") or {}).get("plan"),
            "status": sub.get("status"),
            "current_period_end": fields["current_period_end"],
            "trial": bool(sub.get("trial_end")),
        },
    )


def _handle_sub_updated(db_client, event) -> None:
    sub = event["data"]["object"]
    customer_id = sub.get("customer")
    user = _find_user_by_customer(db_client, customer_id)
    if not user:
        logger.warning(
            "subscription.updated: no user found for customer=%s", customer_id
        )
        return

    status_str = sub.get("status") or "active"
    fields = {
        "stripe_subscription_id": sub.get("id"),
        "subscription_status": status_str,
        "current_period_end": _iso_from_ts(sub.get("current_period_end")),
    }

    if status_str in ("trialing", "active", "past_due"):
        fields["subscription_tier"] = "premium"
    elif status_str == "canceled":
        # Don't downgrade tier here; deletion handler / period-end cron
        # owns that.
        pass
    elif status_str in ("incomplete", "incomplete_expired", "unpaid"):
        logger.warning(
            "subscription.updated unusual status=%s sub=%s — treating as free",
            status_str, sub.get("id"),
        )
        fields["subscription_tier"] = "free"

    _persist_user_update(db_client, user["uid"], fields)

    ph_emit(
        user.get("family_id") or "",
        "subscription_updated",
        {
            "status": status_str,
            "current_period_end": fields["current_period_end"],
        },
    )


def _handle_sub_deleted(db_client, event) -> None:
    sub = event["data"]["object"]
    customer_id = sub.get("customer")
    user = _find_user_by_customer(db_client, customer_id)
    if not user:
        logger.warning(
            "subscription.deleted: no user found for customer=%s", customer_id
        )
        return

    # Mark canceled but DO NOT downgrade tier — premium remains until
    # current_period_end. A 1.4c cron downgrades past-period-end subs.
    fields = {
        "subscription_status": "canceled",
        "current_period_end": _iso_from_ts(sub.get("current_period_end")),
    }
    _persist_user_update(db_client, user["uid"], fields)

    ph_emit(
        user.get("family_id") or "",
        "subscription_canceled",
        {
            "current_period_end": fields["current_period_end"],
            "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
        },
    )


def _handle_invoice_failed(db_client, event) -> None:
    invoice = event["data"]["object"]
    customer_id = invoice.get("customer")
    user = _find_user_by_customer(db_client, customer_id)
    if not user:
        logger.warning(
            "invoice.payment_failed: no user found for customer=%s", customer_id
        )
        return

    # Past-due, but DO NOT downgrade tier — Stripe will dunning-retry.
    _persist_user_update(
        db_client,
        user["uid"],
        {"subscription_status": "past_due"},
    )

    ph_emit(
        user.get("family_id") or "",
        "subscription_payment_failed",
        {
            "invoice_id": invoice.get("id"),
            "attempt_count": invoice.get("attempt_count"),
            "amount_due": invoice.get("amount_due"),
        },
    )


_HANDLERS = {
    "customer.subscription.created": _handle_sub_created,
    "customer.subscription.updated": _handle_sub_updated,
    "customer.subscription.deleted": _handle_sub_deleted,
    "invoice.payment_failed": _handle_invoice_failed,
}


# ── Endpoints ──────────────────────────────────────────────────


@router.post("/checkout/start")
async def start_checkout(
    request: StartCheckoutRequest,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> dict:
    uid = current_user["uid"]
    user_doc = db_client.collection("users").document(uid).get()
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = user_doc.to_dict()
    user_data.setdefault("uid", uid)

    _ensure_subscription_fields(db_client, uid, user_data)

    customer_id = ensure_customer(db_client, user_data)
    if not customer_id:
        raise HTTPException(
            status_code=503,
            detail="Billing temporarily unavailable",
        )

    base = os.getenv("WEB_BASE_URL", "https://dreamvalley.app").rstrip("/")
    success_url = f"{base}/upgrade/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/upgrade/cancelled"

    family_id = user_data.get("family_id") or ""
    url = create_checkout_session(
        customer_id=customer_id,
        plan=request.plan,
        family_id=family_id,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    if not url:
        raise HTTPException(
            status_code=503,
            detail="Could not create checkout session",
        )

    logger.info(
        "checkout session created uid=%s plan=%s customer=%s",
        uid, request.plan, customer_id,
    )
    return {"checkout_url": url}


@router.post("/portal/start")
async def start_portal(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> dict:
    """Create a Stripe Customer Portal session for subscription management.

    User must already have a stripe_customer_id (i.e. has gone through
    checkout at least once). Returns 503 if no customer exists.

    Phase 0 step 1.4d. Bundled here rather than 1.4c so settings UI
    doesn't ship with a placeholder 'Manage subscription' button.
    """
    uid = current_user["uid"]
    user_doc = db_client.collection("users").document(uid).get()
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = user_doc.to_dict()

    customer_id = user_data.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(
            status_code=503,
            detail="No subscription found — start a checkout first",
        )

    from app.services.stripe_client import _get_client
    stripe = _get_client()
    if stripe is None:
        raise HTTPException(
            status_code=503,
            detail="Billing temporarily unavailable",
        )

    base = os.getenv("WEB_BASE_URL", "https://dreamvalley.app").rstrip("/")
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{base}/settings",
        )
    except Exception as e:
        logger.warning("Stripe billing_portal.Session.create failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Could not create portal session",
        )

    logger.info("portal session created uid=%s customer=%s", uid, customer_id)
    return {"portal_url": session.url}


@router.post("/webhook")
async def webhook(request: Request, db_client=Depends(get_db_client)) -> dict:
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature", "")

    event = verify_webhook(payload, sig)
    if event is None:
        raise HTTPException(status_code=400, detail="Bad signature")

    event_id = event.get("id") or ""
    event_type = event.get("type") or ""

    conn = _open_billing_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO stripe_webhook_events "
            "(event_id, event_type, received_at) "
            "VALUES (?, ?, ?)",
            (event_id, event_type, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        first_time = cur.rowcount > 0

        if not first_time:
            existing = conn.execute(
                "SELECT status FROM stripe_webhook_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if existing and existing["status"] == "processed":
                logger.info(
                    "webhook %s already processed — ack-only", event_id
                )
                return {"received": True, "deduped": True}

        handler = _HANDLERS.get(event_type)
        if handler is None:
            logger.info("webhook event type=%s ack-only", event_type)
            conn.execute(
                "UPDATE stripe_webhook_events "
                "SET status='processed', processed_at=? WHERE event_id=?",
                (datetime.now(timezone.utc).isoformat(), event_id),
            )
            conn.commit()
            return {"received": True}

        try:
            handler(db_client, event)
        except Exception as e:
            logger.error(
                "webhook handler failed event_id=%s type=%s: %s",
                event_id, event_type, e, exc_info=True,
            )
            conn.execute(
                "UPDATE stripe_webhook_events "
                "SET status='failed', error=? WHERE event_id=?",
                (str(e)[:1000], event_id),
            )
            conn.commit()
            # Return 500 so Stripe retries.
            raise HTTPException(status_code=500, detail="Handler error")

        conn.execute(
            "UPDATE stripe_webhook_events "
            "SET status='processed', processed_at=? WHERE event_id=?",
            (datetime.now(timezone.utc).isoformat(), event_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {"received": True}
