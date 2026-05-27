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
    """Username-only sign-in. Mints a 30-day session token.

    Magic-link UI was scrapped; this is the surfaced path for existing
    users to re-authenticate. Security model: anyone who knows a username
    can impersonate that user — an accepted tradeoff per the simplified
    UX. Returns 404 if the username isn't found (caller should fall
    through to anon onboarding to create a new account).

    Optional child_age / lang on the body update the existing user's
    settings as a side-effect, mirroring the post-auth completeOnboarding
    call so the onboarding form's age/language selections persist.
    """
    import uuid as _uuid
    from app.services.local_store import get_local_store
    from app.services.magic_link import _persist_token_row

    uname_lc = body.username.strip().lower()
    if not uname_lc:
        raise HTTPException(status_code=400, detail="username required")

    store = get_local_store()
    target = None
    target_uid = None
    for doc in store.collection("users").get():
        data = doc.to_dict()
        lc = (data.get("username_lowercase") or (data.get("username") or "").lower())
        if lc == uname_lc:
            target = data
            target_uid = data.get("uid") or data.get("id")
            break

    if target is None or not target_uid:
        raise HTTPException(status_code=404, detail="user_not_found")

    updates = {}
    if body.child_age is not None and body.child_age != target.get("child_age"):
        updates["child_age"] = body.child_age
    if body.lang and body.lang != target.get("preferred_lang"):
        updates["preferred_lang"] = body.lang
    if updates:
        updates["onboarding_complete"] = True
        store.collection("users").document(target_uid).update(updates)
        target.update(updates)
        try:
            from app.dependencies import _local_users
            if target_uid in _local_users:
                _local_users[target_uid].update(updates)
        except Exception:
            pass

    token = _uuid.uuid4().hex
    session_id = f"username-login-{_uuid.uuid4().hex[:8]}"
    _persist_token_row(store, token, target_uid, session_id)

    logger.info("username_login uid=%s", target_uid)
    ph_emit(target.get("family_id") or "", "auth_username_login", {})

    return {
        "token": token,
        "user": {
            "uid": target_uid,
            "username": target.get("username"),
            "family_id": target.get("family_id"),
            "email": target.get("email"),
            "child_age": target.get("child_age"),
            "preferred_lang": target.get("preferred_lang"),
            "subscription_tier": target.get("subscription_tier") or "free",
            "subscription_status": target.get("subscription_status"),
            "credits_remaining": target.get("credits_remaining"),
            "onboarding_complete": target.get("onboarding_complete", True),
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
