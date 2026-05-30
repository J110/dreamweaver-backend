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


class LoginUsernameBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    child_age: Optional[int] = Field(default=None, ge=0, le=18)
    lang: Optional[str] = Field(default=None, pattern="^(en|hi)$")


# ── New endpoints ────────────────────────────────────────────


@router.post("/request_link")
async def request_link(body: RequestLinkBody, request: Request) -> dict:
    """Send a magic-link email to the supplied address.

    Returns one of:
      {"initiator_session_id", "status": "sent"} — link issued (whether or
        not the email actually exists: missing-email path still writes a
        real auth_code and silently doesn't send, preserving anti-
        enumeration on user existence).
      {"status": "rate_limited", "retry_after_seconds": N} — caller has
        hit the 3-per-hour budget on this email. Frontend renders an
        explicit retry-after card instead of routing through the poll
        path (which would mis-render as 'Link expired').
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
        # Anti-enumerate on unexpected error: present as a normal sent.
        return {"initiator_session_id": ml.generate_session_id(), "status": "sent"}


@router.post("/verify_link")
async def verify_link(body: VerifyLinkBody) -> dict:
    """Consume a magic-link code.

    On status='claimed' the response includes the session token and user
    fields so the clicker device can log itself in directly (fixes the
    mobile flow where the requesting device has no polling tab open).
    The /auth/poll path is preserved for graceful auto-completion on a
    still-open originator tab.
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

    Same response shape as /request_link: 'sent' on issue, 'rate_limited'
    with retry_after_seconds when over the 3-per-hour budget.
    """
    initiator_ip = (request.client.host if request.client else None)
    return await ml.request_claim(
        target_uid=current_user["uid"],
        target_email=str(body.email),
        lang=body.lang,
        initiator_ip=initiator_ip,
    )


# ── Username-only login ──────────────────────────────────────


@router.post("/login_username")
async def login_username(body: LoginUsernameBody) -> dict:
    """DEPRECATED COMPAT SHIM. Find-existing-by-username login is removed
    (impersonation vector). Now always-creates a device account, identical
    to /auth/device_account, so a mid-deploy old-frontend session keeps
    working. Remove this route in a follow-up once no old frontend remains.
    """
    from app.services.local_store import get_local_store
    from app.services import magic_link as ml
    store = get_local_store()
    user = ml._create_device_user(store, body.username, child_age=getattr(body, "child_age", None), lang=getattr(body, "lang", "en") or "en")
    token = ml.mint_device_token(store, user["uid"])
    return {
        "token": token,
        "user": {
            "uid": user["uid"],
            "username": user["username"],
            "family_id": user["family_id"],
            "child_age": user.get("child_age"),
            "preferred_lang": user.get("preferred_lang"),
            "subscription_tier": "free",
            "onboarding_complete": True,
        },
    }


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


class DeviceAccountBody(BaseModel):
    username: str
    child_age: int | None = None
    lang: str = "en"


class RenewBody(BaseModel):
    token: str
    family_id: str


def _renew_logic(token: str, family_id: str) -> dict:
    """Renew a session. Requires the stored token (proof of a prior real
    session) + matching family_id — family_id alone can never mint (closes
    the leaked-UUID hole). Returns {token} on success; raises 410
    'dormant_reauth_required' when the token row is gone/revoked/expired or
    the family_id doesn't match (the ONLY fall-through trigger, spec §3).
    """
    from datetime import datetime, timezone
    from app.services.local_store import get_local_store
    from app.services import magic_link as ml
    store = get_local_store()
    doc = store.collection("tokens").document(token).get()
    row = doc.to_dict() if doc.exists else None
    if not row or row.get("revoked_at"):
        raise HTTPException(status_code=410, detail="dormant_reauth_required")
    uid = row.get("uid")
    user_doc = store.collection("users").document(uid).get() if uid else None
    user = user_doc.to_dict() if (user_doc and user_doc.exists) else None
    if not user or (user.get("family_id") or "") != family_id:
        raise HTTPException(status_code=410, detail="dormant_reauth_required")
    exp = row.get("expires_at")
    if exp:
        try:
            if datetime.fromisoformat(exp) < datetime.now(timezone.utc):
                raise HTTPException(status_code=410, detail="dormant_reauth_required")
        except HTTPException:
            raise
        except Exception:
            pass
    new_token = ml.mint_device_token(store, uid)
    return {"token": new_token}


@router.post("/renew")
async def renew(body: RenewBody) -> dict:
    return _renew_logic(body.token, body.family_id)


@router.post("/device_account")
async def device_account(body: DeviceAccountBody) -> dict:
    """Always-create a fresh device account + 365d token. Username is a
    cosmetic label (collisions fine). The ONLY mint path for new devices;
    there is no find-existing-by-username login (impersonation vector).
    """
    from app.services.local_store import get_local_store
    from app.services import magic_link as ml
    store = get_local_store()
    user = ml._create_device_user(store, body.username, child_age=body.child_age, lang=body.lang)
    token = ml.mint_device_token(store, user["uid"])
    return {
        "token": token,
        "user": {
            "uid": user["uid"],
            "username": user["username"],
            "family_id": user["family_id"],
            "child_age": user.get("child_age"),
            "preferred_lang": user.get("preferred_lang"),
            "subscription_tier": user.get("subscription_tier") or "free",
            "onboarding_complete": True,
        },
    }
