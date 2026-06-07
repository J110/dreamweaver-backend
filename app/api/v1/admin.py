"""Admin endpoints for backend management (content reload, etc.)."""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel

from app.dependencies import _check_local_mode, get_db_client
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class ReloadResponse(BaseModel):
    success: bool
    data: dict
    message: str


@router.post("/reload", response_model=ReloadResponse)
async def reload_content(
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
) -> ReloadResponse:
    """
    Reload content from seed_output/content.json without restarting.

    Requires X-Admin-Key header matching ADMIN_API_KEY env var.
    Called by the pipeline after writing new content.
    """
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key not configured",
        )

    if x_admin_key != admin_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key",
        )

    if not _check_local_mode():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reload only available in LocalStore mode",
        )

    from app.services.local_store import get_local_store
    store = get_local_store()
    result = store.reload_content()

    logger.info(
        "Content reloaded via admin API: %d -> %d items (%+d)",
        result["previous_count"],
        result["current_count"],
        result["added"],
    )

    return ReloadResponse(
        success=True,
        data=result,
        message=f"Reloaded. {result['current_count']} items ({result['added']:+d} new).",
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST-ONLY — DO NOT MERGE TO main / prod.
# Lives only on the `test-env` branch. A tier-setter gated solely by an admin
# key is a privilege-escalation hole in production; it exists here only to stage
# scenario-4 (was-premium-then-cancelled) on the throwaway test backend.
# ─────────────────────────────────────────────────────────────────────────────


class SetTierRequest(BaseModel):
    email: Optional[str] = None
    uid: Optional[str] = None
    subscription_tier: str = "free"
    subscription_status: str = "canceled"


class SetTierResponse(BaseModel):
    success: bool
    uid: str
    subscription_tier: str
    subscription_status: str


@router.post("/set-tier", response_model=SetTierResponse)
async def set_tier(
    body: SetTierRequest,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
    db_client=Depends(get_db_client),
) -> SetTierResponse:
    """TEST-ONLY entitlement override — MUST stay on the test-env branch.

    Stages scenario 4 (was-premium-then-cancelled = logged-in-but-free) on the
    ephemeral test backend, where a raw users.json edit is invisible (the user
    cache loads once and is never re-read). Writes memory+disk live via the same
    _persist_user_update the Stripe webhooks use, so it takes effect with no
    restart. NEVER merge to main/prod.
    """
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key not configured",
        )
    if x_admin_key != admin_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key",
        )
    if not _check_local_mode():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="set-tier only available in LocalStore mode",
        )

    uid = (body.uid or "").strip()
    if uid:
        from app.dependencies import _load_persisted_tokens, _local_users
        _load_persisted_tokens()
        if uid not in _local_users:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No user for uid={uid}",
            )
    else:
        if not body.email:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provide uid or email",
            )
        from app.services.restore_codes import _lookup_user_by_recovery_email
        user = _lookup_user_by_recovery_email(body.email.strip().lower())
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No user for email={body.email}",
            )
        uid = user["uid"]

    fields = {
        "subscription_tier": body.subscription_tier,
        "subscription_status": body.subscription_status,
    }
    from app.api.v1.billing import _persist_user_update
    _persist_user_update(db_client, uid, fields)
    logger.warning("[TEST set-tier] uid=%s -> %s", uid, fields)

    return SetTierResponse(
        success=True,
        uid=uid,
        subscription_tier=body.subscription_tier,
        subscription_status=body.subscription_status,
    )
