"""RevenueCat webhook endpoint.

Security boundary for native IAP: a forged webhook could grant premium, so
auth is verified FIRST (constant-time) before any body parsing or DB work.
Mirrors the Stripe webhook's idempotency flow over `revenuecat_webhook_events`
(A1), maps the event to an entitlement source (A2's map_event_to_source), and
projects via the sole tier-writer (`_apply_tier`). RevenueCat is write-only —
the read/gating path never imports this module.
"""

from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.v1.billing import (
    _apply_tier,
    _open_billing_db,
    _persist_user_update,
)
from app.dependencies import get_db_client
from app.utils.revenuecat_mapping import map_event_to_source
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _authorized(request: Request) -> bool:
    """Constant-time compare of the Authorization header against the configured
    shared secret. Unset secret or missing header => unauthorized (fail closed)."""
    secret = os.getenv("REVENUECAT_WEBHOOK_SECRET")
    if not secret:
        return False
    provided = request.headers.get("Authorization")
    if not provided:
        return False
    return hmac.compare_digest(provided, secret)


@router.post("/webhook")
async def webhook(request: Request, db_client=Depends(get_db_client)) -> dict:
    # 1. AUTH FIRST — never process an unauthenticated request.
    if not _authorized(request):
        logger.warning("revenuecat webhook rejected: bad/missing Authorization")
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 2. Parse body.
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    event = body.get("event") if isinstance(body, dict) else None
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Missing event")

    event_id = event.get("id") or ""
    event_type = event.get("type") or ""

    # 3. Idempotency — mirror the Stripe flow over revenuecat_webhook_events.
    conn = _open_billing_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO revenuecat_webhook_events "
            "(event_id, event_type, received_at) VALUES (?, ?, ?)",
            (event_id, event_type, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        first_time = cur.rowcount > 0

        if not first_time:
            existing = conn.execute(
                "SELECT status FROM revenuecat_webhook_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if existing and existing["status"] == "processed":
                logger.info(
                    "revenuecat webhook %s already processed — ack-only", event_id
                )
                return {"received": True, "deduped": True}

        try:
            _process_event(db_client, event)
        except Exception as e:
            logger.error(
                "revenuecat webhook handler failed event_id=%s type=%s: %s",
                event_id, event_type, e, exc_info=True,
            )
            conn.execute(
                "UPDATE revenuecat_webhook_events "
                "SET status='failed', error=? WHERE event_id=?",
                (str(e)[:1000], event_id),
            )
            conn.commit()
            raise HTTPException(status_code=500, detail="Handler error")

        conn.execute(
            "UPDATE revenuecat_webhook_events "
            "SET status='processed', processed_at=? WHERE event_id=?",
            (datetime.now(timezone.utc).isoformat(), event_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {"received": True}


def _process_event(db_client, event: dict) -> None:
    # 4. Map to an entitlement source; ignorable / unknown-store events are acked.
    source = map_event_to_source(event)
    if source is None:
        logger.info(
            "revenuecat webhook event type=%s ack-only (not entitlement-affecting)",
            event.get("type"),
        )
        return

    # 5. Resolve uid (== our uid via logIn link). Unknown user => warn + ack.
    uid = event.get("app_user_id")
    if not uid:
        logger.warning("revenuecat webhook missing app_user_id — ack-only")
        return
    doc = db_client.collection("users").document(uid).get()
    if not doc.exists:
        logger.warning(
            "revenuecat webhook for unknown uid=%s — ack-only (no write)", uid
        )
        return

    # 6. Merge the source into a COPY of entitlements (preserve sibling sources).
    user = doc.to_dict() or {}
    ent = dict(user.get("entitlements") or {})
    ent[source["store"]] = {
        "status": source["status"],
        "expires": source["expires"],
        "product_id": event.get("product_id"),
        "store": source["store"],
        "environment": event.get("environment"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _persist_user_update(db_client, uid, {"entitlements": ent})

    # 7. Recompute the projection (sole tier-writer).
    _apply_tier(db_client, uid)
