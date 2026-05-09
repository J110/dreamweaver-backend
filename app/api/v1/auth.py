"""Authentication endpoints — magic-link auth (Phase 0 step 1.5).

Replaces the legacy username + hardcoded-password signup/login flow.

New endpoints:
  POST /auth/request_link       — issue magic link, send via Resend
  POST /auth/verify_link        — consume code, mint session token (Pattern A)
  GET  /auth/poll               — initiator polls for claimed token
  POST /auth/logout             — revoke current bearer token
  POST /auth/claim_existing     — auth'd user adds email to claim record

Removed:
  POST /auth/signup → 410 Gone (replacement pointer)
  POST /auth/login  → 410 Gone (replacement pointer)

Spec: docs/specs/auth-magic-link-v1.md
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.dependencies import get_current_user
from app.services import magic_link as ml
from app.services.analytics_posthog import emit_event as ph_emit
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ── Models ───────────────────────────────────────────────────


class RequestLinkBody(BaseModel):
    email: EmailStr
    lang: str = Field(default="en", pattern="^(en|hi)$")
    context: str = Field(default="login_existing", pattern="^(signup_new|login_existing)$")


class VerifyLinkBody(BaseModel):
    code: str = Field(min_length=10, max_length=128)


class ClaimExistingBody(BaseModel):
    email: EmailStr
    lang: str = Field(default="en", pattern="^(en|hi)$")


# ── New endpoints ────────────────────────────────────────────


@router.post("/request_link")
async def request_link(body: RequestLinkBody, request: Request) -> dict:
    """Send a magic-link email to the supplied address.

    Anti-enumeration: always returns {status:'sent'}. The actual email may
    or may not have been sent (rate-limited, missing user, send failure) —
    no signal leaks to the wire.
    """
    initiator_ip = (request.client.host if request.client else None)
    try:
        return await ml.request_magic_link(
            email=str(body.email),
            lang=body.lang,
            context=body.context,
            initiator_ip=initiator_ip,
        )
    except Exception as e:
        logger.warning("request_link error: %s", e)
        # Still anti-enumerate on error.
        return {"initiator_session_id": ml.generate_session_id(), "status": "sent"}


@router.post("/verify_link")
async def verify_link(body: VerifyLinkBody) -> dict:
    """Consume a magic-link code. Returns status + context.

    Never returns the session token here — the clicker device must not log
    itself in. Token is fetched by the initiator via /auth/poll.
    """
    return ml.verify_code(body.code)


@router.get("/poll")
async def poll(session_id: str = Query(..., min_length=8)) -> dict:
    """Initiator polls for token claim.

    Returns {status:'waiting'|'ready'|'expired', ...}. On 'ready', also
    returns token + uid + username + family_id + email_verified + context.
    First successful read scrubs the auth_codes row so token cannot be
    re-fetched.
    """
    return ml.poll_session(session_id)


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)) -> dict:
    """Revoke the current bearer token.

    Sets revoked_at on the tokens row. Subsequent requests with this token
    return 401 from local_verify_token's revocation check.
    """
    token = current_user.get("_token", "")
    family_id = current_user.get("family_id", "")
    revoked = ml.revoke_token(token, reason="logout")
    if revoked:
        ph_emit(family_id, "auth_logout", {})
    return {"success": revoked}


@router.post("/claim_existing")
async def claim_existing(
    body: ClaimExistingBody,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Authenticated user requests a claim_existing magic-link.

    Used during the migration window: a user with a valid (legacy or new)
    token who needs to associate an email with their record. The verify
    step will set email + email_verified=true on the existing user record
    identified by current_user['uid'] — does NOT create a new user.
    """
    initiator_ip = (request.client.host if request.client else None)
    return await ml.request_claim(
        target_uid=current_user["uid"],
        target_email=str(body.email),
        lang=body.lang,
        initiator_ip=initiator_ip,
    )


# ── Deprecated endpoints — 410 Gone ──────────────────────────


@router.post("/signup", status_code=status.HTTP_410_GONE)
async def signup_deprecated() -> dict:
    """Removed in Phase 0 step 1.5. Replaced by magic-link auth."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "endpoint_removed",
            "message": "Replaced by magic-link auth.",
            "replacement": "POST /api/v1/auth/request_link with context=signup_new",
        },
    )


@router.post("/login", status_code=status.HTTP_410_GONE)
async def login_deprecated() -> dict:
    """Removed in Phase 0 step 1.5. Replaced by magic-link auth."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "endpoint_removed",
            "message": "Replaced by magic-link auth.",
            "replacement": "POST /api/v1/auth/request_link with context=login_existing",
        },
    )
