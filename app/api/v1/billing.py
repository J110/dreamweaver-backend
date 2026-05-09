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
    period_start_iso = _iso_from_ts(sub.get("current_period_start"))
    period_end_iso = _iso_from_ts(sub.get("current_period_end"))
    fields = {
        "stripe_subscription_id": sub.get("id"),
        "subscription_status": sub.get("status") or "active",
        "subscription_tier": "premium",
        "current_period_end": period_end_iso,
        # Phase 0 step 1.4e: seed monthly credits on subscription start
        # (covers both new signups and trial starts; trial users get
        # the same 30 credits during their 7-day trial).
        "credits_remaining": 30,
        "credits_period_start": period_start_iso,
        "credits_period_end": period_end_iso,
        "credits_frozen": False,
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
    # Phase 0 step 1.4e: freeze credits during past_due so a non-paying
    # user can't burn through their pool. The next successful invoice
    # clears credits_frozen back to False.
    _persist_user_update(
        db_client,
        user["uid"],
        {
            "subscription_status": "past_due",
            "credits_frozen": True,
        },
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


def _handle_invoice_paid(db_client, event) -> None:
    """Renewal happy path. Fired on every successful subscription invoice."""
    invoice = event["data"]["object"]
    customer_id = invoice.get("customer")
    user = _find_user_by_customer(db_client, customer_id)
    if not user:
        logger.warning(
            "invoice.payment_succeeded: no user found for customer=%s", customer_id
        )
        return

    # Period end + plan from the first subscription line item.
    period_end_ts = None
    plan_id = None
    try:
        lines = (invoice.get("lines") or {}).get("data") or []
        if lines:
            period = lines[0].get("period") or {}
            period_end_ts = period.get("end")
            price = lines[0].get("price") or {}
            plan_id = price.get("id")
    except Exception:
        pass

    fields = {
        "subscription_status": "active",
        "subscription_tier": "premium",
        # Phase 0 step 1.4e: reset monthly credits on every successful
        # invoice (covers post-trial first charge AND every renewal).
        # Top-up credits (topup_credits_remaining) are NOT touched —
        # they survive the period boundary by design.
        "credits_remaining": 30,
        "credits_frozen": False,
    }
    iso_end = _iso_from_ts(period_end_ts)
    if iso_end:
        fields["current_period_end"] = iso_end
        fields["credits_period_end"] = iso_end
    # Period start: line item period.start, fall back to invoice period_start.
    period_start_iso = None
    try:
        lines = (invoice.get("lines") or {}).get("data") or []
        if lines:
            period = lines[0].get("period") or {}
            period_start_iso = _iso_from_ts(period.get("start"))
    except Exception:
        pass
    if period_start_iso is None:
        period_start_iso = _iso_from_ts(invoice.get("period_start"))
    if period_start_iso:
        fields["credits_period_start"] = period_start_iso

    # Stripe occasionally surfaces an updated email on the invoice — sync it.
    customer_email = invoice.get("customer_email")
    if customer_email and user.get("billing_email") != customer_email:
        fields["billing_email"] = customer_email

    _persist_user_update(db_client, user["uid"], fields)

    ph_emit(
        user.get("family_id") or "",
        "subscription_renewed",
        {
            "invoice_id": invoice.get("id"),
            "amount_paid": invoice.get("amount_paid"),
            "currency": invoice.get("currency"),
            "plan": plan_id,
            "current_period_end": iso_end,
        },
    )


def _handle_trial_will_end(db_client, event) -> None:
    """Informational. Fired ~3 days before trial ends. No state change here.

    Future hook: this is where a 'your trial ends in 3 days' email via
    Resend would fire. Not implemented in 1.4c — log + PostHog only.
    """
    sub = event["data"]["object"]
    customer_id = sub.get("customer")
    user = _find_user_by_customer(db_client, customer_id)
    if not user:
        logger.warning(
            "subscription.trial_will_end: no user found for customer=%s", customer_id
        )
        return

    trial_end_iso = _iso_from_ts(sub.get("trial_end"))
    plan_id = None
    try:
        item = ((sub.get("items") or {}).get("data") or [{}])[0]
        plan_id = (item.get("price") or {}).get("id")
    except Exception:
        pass

    logger.info(
        "trial_will_end customer=%s sub=%s trial_end=%s plan=%s — informational only",
        customer_id, sub.get("id"), trial_end_iso, plan_id,
    )

    ph_emit(
        user.get("family_id") or "",
        "subscription_trial_ending",
        {
            "trial_end": trial_end_iso,
            "plan": plan_id,
        },
    )


def _handle_charge_dispute(db_client, event) -> None:
    """Defensive: revoke premium access immediately on dispute.

    Stripe doesn't put `customer` directly on the dispute object; we fetch
    the underlying charge to resolve it. Auto-cancellation of the Stripe
    subscription is NOT performed — that's a manual decision after review.
    """
    dispute = event["data"]["object"]
    charge_id = dispute.get("charge")
    dispute_id = dispute.get("id")

    customer_id = None
    try:
        from app.services.stripe_client import _get_client
        stripe = _get_client()
        if stripe is not None and charge_id:
            charge = stripe.Charge.retrieve(charge_id)
            if charge:
                customer_id = charge.get("customer")
    except Exception as e:
        logger.warning(
            "dispute charge fetch failed dispute=%s charge=%s: %s",
            dispute_id, charge_id, e,
        )

    if not customer_id:
        logger.warning(
            "charge.dispute.created: could not resolve customer for charge=%s dispute=%s",
            charge_id, dispute_id,
        )
        return

    user = _find_user_by_customer(db_client, customer_id)
    if not user:
        logger.warning(
            "charge.dispute.created: no user found for customer=%s dispute=%s",
            customer_id, dispute_id,
        )
        return

    fields = {
        "subscription_tier": "free",
        "subscription_status": "disputed",
        "disputed_at": datetime.now(timezone.utc).isoformat(),
    }
    _persist_user_update(db_client, user["uid"], fields)

    logger.warning(
        "DISPUTE: customer=%s dispute=%s reason=%s amount=%s — premium revoked, "
        "manual review required (Stripe subscription NOT auto-cancelled)",
        customer_id, dispute_id, dispute.get("reason"), dispute.get("amount"),
    )

    ph_emit(
        user.get("family_id") or "",
        "subscription_disputed",
        {
            "dispute_id": dispute_id,
            "amount": dispute.get("amount"),
            "currency": dispute.get("currency"),
            "reason": dispute.get("reason"),
            "status": dispute.get("status"),
        },
    )


def _handle_checkout_session_completed(db_client, event) -> None:
    """Top-up purchase fulfillment.

    Phase 0 step 1.4e. Fires for both subscription and one-time payment
    sessions. We only act on mode=payment with metadata.kind="topup".
    Subscription-mode sessions are handled by customer.subscription.created
    (the canonical event for subscription state).
    """
    session = event["data"]["object"]
    mode = session.get("mode")
    metadata = session.get("metadata") or {}

    if mode != "payment":
        # Subscription-mode session — handled elsewhere. Ack and return.
        return
    if metadata.get("kind") != "topup":
        # Some other one-time payment we didn't initiate. Log and skip.
        logger.info(
            "checkout.session.completed mode=payment but kind=%s — ignoring",
            metadata.get("kind"),
        )
        return

    customer_id = session.get("customer")
    user = _find_user_by_customer(db_client, customer_id)
    if not user:
        logger.warning(
            "topup checkout: no user found for customer=%s session=%s",
            customer_id, session.get("id"),
        )
        return

    pack_credits = int(metadata.get("credits") or 10)
    current_topup = int(user.get("topup_credits_remaining") or 0)
    new_topup = current_topup + pack_credits
    _persist_user_update(
        db_client, user["uid"],
        {"topup_credits_remaining": new_topup},
    )
    logger.info(
        "topup applied uid=%s pack=%d total_topup=%d",
        user["uid"], pack_credits, new_topup,
    )

    ph_emit(
        user.get("family_id") or "",
        "topup_purchased",
        {
            "session_id": session.get("id"),
            "pack_credits": pack_credits,
            "amount_total": session.get("amount_total"),
            "currency": session.get("currency"),
            "topup_balance_after": new_topup,
        },
    )


_HANDLERS = {
    "customer.subscription.created": _handle_sub_created,
    "customer.subscription.updated": _handle_sub_updated,
    "customer.subscription.deleted": _handle_sub_deleted,
    "invoice.payment_failed": _handle_invoice_failed,
    "invoice.payment_succeeded": _handle_invoice_paid,
    "customer.subscription.trial_will_end": _handle_trial_will_end,
    "charge.dispute.created": _handle_charge_dispute,
    "checkout.session.completed": _handle_checkout_session_completed,
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


@router.post("/topup/start")
async def start_topup(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> dict:
    """Start a $2 / 10-credit top-up Stripe Checkout (one-time payment).

    Phase 0 step 1.4e. Premium users only — Free per-gen micro-packs
    ship in Phase 1 alongside the creator stream.

    Returns 503 if the user has no stripe_customer_id (indicates they
    never went through subscription checkout, so probably not Premium).

    On success the customer pays $2; the checkout.session.completed
    webhook adds 10 credits to topup_credits_remaining (which survives
    cancellation by design).
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
            detail="No subscription found — top-ups require an active Premium subscription",
        )

    from app.services.stripe_client import _get_client
    stripe = _get_client()
    if stripe is None:
        raise HTTPException(
            status_code=503,
            detail="Billing temporarily unavailable",
        )

    base = os.getenv("WEB_BASE_URL", "https://dreamvalley.app").rstrip("/")
    family_id = user_data.get("family_id") or ""
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            customer=customer_id,
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": 200,  # $2.00 in cents
                    "product_data": {
                        "name": "Dream Valley — 10 story credits",
                        "description": "Top-up: 10 personalized story credits. Credits never expire.",
                    },
                },
                "quantity": 1,
            }],
            success_url=f"{base}/upgrade/topup-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/settings",
            client_reference_id=family_id,
            metadata={
                "kind": "topup",
                "family_id": family_id,
                "credits": "10",
            },
        )
    except Exception as e:
        logger.warning("Stripe topup checkout.Session.create failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Could not create top-up session",
        )

    logger.info(
        "topup checkout session created uid=%s customer=%s",
        uid, customer_id,
    )
    return {"checkout_url": session.url}


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
