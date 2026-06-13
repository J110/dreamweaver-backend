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
    recovery_email: Optional[str] = None
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
    restart. Pass a new uid + recovery_email to SEED a restorable premium
    family (scenario 2/3) without Stripe. NEVER merge to main/prod.
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

    recovery_email = (body.recovery_email or "").strip().lower()
    uid = (body.uid or "").strip()
    if uid:
        from app.dependencies import _load_persisted_tokens, _local_users
        _load_persisted_tokens()
        if uid not in _local_users:
            if not recovery_email:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No user for uid={uid} (pass recovery_email to seed one)",
                )
            seed_doc = {
                "uid": uid,
                "family_id": uid,
                "username": uid,
                "onboarding_complete": True,
            }
            _local_users[uid] = seed_doc
            db_client.collection("users").document(uid).set(seed_doc)
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
    if recovery_email:
        fields["recovery_email"] = recovery_email
        fields["billing_email"] = recovery_email
    from app.dependencies import _local_users
    _local_users.setdefault(uid, {"uid": uid}).update(fields)
    from app.api.v1.billing import _persist_user_update
    _persist_user_update(db_client, uid, fields)
    logger.warning("[TEST set-tier] uid=%s -> %s", uid, fields)

    return SetTierResponse(
        success=True,
        uid=uid,
        subscription_tier=body.subscription_tier,
        subscription_status=body.subscription_status,
    )


class RestoreCodePeekRequest(BaseModel):
    email: str


class RestoreCodePeekResponse(BaseModel):
    email: str
    code: str
    family_id: str


@router.post("/restore-code", response_model=RestoreCodePeekResponse)
async def peek_restore_code(
    body: RestoreCodePeekRequest,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
    db_client=Depends(get_db_client),
) -> RestoreCodePeekResponse:
    """TEST-ONLY restore-code minter — MUST stay on the test-env branch.

    jt34 has no RESEND_API_KEY, so the restore-code email never sends. This
    mints a valid code for an existing recovery_email family and RETURNS it
    (writing the same code row verify-code reads), so restore completes without
    email. A "read any restore code" endpoint in prod is an account-takeover
    hole — test-env ONLY, admin-key gated, LocalStore-only, NEVER merge to prod.
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
            detail="restore-code only available in LocalStore mode",
        )

    from app.services.restore_codes import (
        _norm_email,
        _lookup_user_by_recovery_email,
        _generate_code,
        _write_code_row,
    )
    email_lc = _norm_email(body.email)
    user = _lookup_user_by_recovery_email(email_lc)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No family for recovery_email={email_lc}",
        )
    code = _generate_code()
    _write_code_row(email_lc, user.get("family_id", ""), code)
    logger.warning(
        "[TEST restore-code] email=%s family=%s", email_lc, user.get("family_id", "")
    )
    return RestoreCodePeekResponse(
        email=email_lc,
        code=code,
        family_id=user.get("family_id", ""),
    )
