"""
Shared application dependencies.
Supports both Firebase mode and local development mode.
"""

import os
import time
import uuid
import hashlib
from typing import Dict, Optional

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Global Instances
_db_client = None
_groq_client = None
_is_local_mode = None


def _check_local_mode() -> bool:
    """Determine if we should use local mode (no Firebase)."""
    global _is_local_mode
    if _is_local_mode is not None:
        return _is_local_mode

    settings = get_settings()
    cred_path = settings.firebase_credentials_path

    if not cred_path or not os.path.exists(cred_path):
        logger.info("Firebase credentials not found - running in LOCAL DEV mode")
        _is_local_mode = True
    else:
        _is_local_mode = False

    return _is_local_mode


def get_db_client(settings: Settings = Depends(get_settings)):
    """Get database client - Firestore in prod, LocalStore in dev."""
    global _db_client
    if _db_client is not None:
        return _db_client

    if _check_local_mode():
        from app.services.local_store import get_local_store
        _db_client = get_local_store()
        logger.info("Using LocalStore (in-memory) database")
    else:
        from firebase_admin import firestore
        _db_client = firestore.client()
        logger.info("Using Firestore database")

    return _db_client


def get_groq_client(settings: Settings = Depends(get_settings)):
    """Get Groq API client instance."""
    global _groq_client
    if _groq_client is not None:
        return _groq_client

    api_key = settings.groq_api_key
    if not api_key:
        logger.warning("No Groq API key - AI generation will use mock data")
        return None

    try:
        from groq import Groq
        _groq_client = Groq(api_key=api_key)
        logger.info("Groq client initialized")
        return _groq_client
    except ImportError:
        logger.warning("groq package not installed - AI generation will use mock data")
        return None


# Local Auth Store (for dev mode without Firebase)
_local_users: Dict[str, dict] = {}
_local_tokens: Dict[str, str] = {}  # token -> uid


def _persist_token(token: str, uid: str):
    """Persist a token to LocalStore so it survives Docker restarts."""
    try:
        from app.services.local_store import get_local_store
        store = get_local_store()
        store.collection("tokens").document(token).set({
            "id": token,
            "token": token,
            "uid": uid,
            "created_at": time.time(),
        })
    except Exception:
        pass  # Don't crash if persist fails


def _load_persisted_tokens():
    """Load persisted tokens from LocalStore on first use."""
    global _local_tokens, _local_users
    if _local_tokens:
        return  # Already loaded
    try:
        from app.services.local_store import get_local_store
        store = get_local_store()
        token_docs = store.collection("tokens").get()
        for doc in token_docs:
            data = doc.to_dict()
            tok = data.get("token")
            uid = data.get("uid")
            if tok and uid:
                _local_tokens[tok] = uid

        # Also reload users from LocalStore into _local_users cache
        user_docs = store.collection("users").get()
        for doc in user_docs:
            data = doc.to_dict()
            uid = data.get("uid") or data.get("id")
            if uid:
                _local_users[uid] = data
    except Exception:
        pass  # Don't crash on load failure


# NOTE: Phase 0 step 1.5 (magic-link auth migration) deleted local_login()
# entirely and dropped password storage from local_create_user(). Three
# critical security holes closed:
#   - "not stored_pw" accept branch (records w/ empty password were
#     accessible by username alone)
#   - plaintext-password fallback branch
#   - new-user records minted with sha256(plain) instead of bcrypt/argon2
# The magic-link service (app/services/magic_link.py) is the new mint path
# for both new users and existing-user re-auth. local_create_user remains
# only for backward-compat callers; it now mints without a password and is
# slated for removal once those callers are gone.


def local_create_user(username: str, password: str = "") -> dict:
    """DEPRECATED — use app.services.magic_link instead.

    Phase 0 step 1.5 dropped password storage. Signature kept for backward
    compat with existing imports (none expected post-migration). The
    `password` argument is ignored; the user record is created without a
    password field.
    """
    uid = hashlib.sha256(username.encode()).hexdigest()[:28]
    _local_users[uid] = {
        "uid": uid,
        "username": username,
        "email": f"{username}@dreamweaver.app",  # vestigial synthetic; cleaned post-migration
    }
    token = hashlib.sha256(f"{uid}:{time.time()}".encode()).hexdigest()
    _local_tokens[token] = uid
    _persist_token(token, uid)
    return {"uid": uid, "token": token, "username": username}


def local_login(username: str, password: str) -> Optional[dict]:
    """REMOVED — Phase 0 step 1.5.

    Password-based login is gone. The magic-link flow
    (app/services/magic_link.py) replaces it. Calling this function now
    raises NotImplementedError to surface any forgotten callers loudly.
    """
    raise NotImplementedError(
        "local_login was removed in Phase 0 step 1.5. "
        "Use app.services.magic_link.request_magic_link / verify_code instead."
    )


def _ensure_family_id(db_client, uid: str, user_data: dict) -> str:
    """Mint family_id (UUIDv4) if missing on the user record and persist.

    Returns the family_id (existing or newly minted).

    Benign race: two concurrent reads for the same user without family_id can
    both mint UUIDs; the second persistent write wins. Brief identity
    divergence on emitted events resolves on the next read; PostHog's alias
    model handles the rare merge case. Not worth a lock.
    """
    fid = user_data.get("family_id")
    if fid:
        return fid
    fid = str(uuid.uuid4())
    try:
        # Update both the persistent users collection AND the in-memory cache,
        # so subsequent token-verifications see the new field without a disk hit.
        db_client.collection("users").document(uid).update({"family_id": fid})
        if uid in _local_users:
            _local_users[uid]["family_id"] = fid
        # Annotate the caller's dict so they don't need to re-read.
        user_data["family_id"] = fid
    except Exception as e:
        logger.warning(f"family_id backfill persist failed for uid={uid}: {e}")
    return fid


SUBSCRIPTION_FIELD_DEFAULTS = {
    "stripe_customer_id": None,
    "stripe_subscription_id": None,
    "subscription_status": "free",
    "current_period_end": None,
    "billing_email": None,
}


def _ensure_subscription_fields(db_client, uid: str, user_data: dict) -> None:
    """Idempotent: add any missing subscription fields with defaults.

    Persists only the diff. No-op when all five fields already exist.
    Same race semantics as _ensure_family_id (last-write-wins, brief
    divergence acceptable).
    """
    missing = {
        k: v
        for k, v in SUBSCRIPTION_FIELD_DEFAULTS.items()
        if k not in user_data
    }
    if not missing:
        return
    user_data.update(missing)
    try:
        db_client.collection("users").document(uid).update(missing)
        if uid in _local_users:
            _local_users[uid].update(missing)
    except Exception as e:
        logger.warning(
            f"subscription field backfill failed for uid={uid}: {e}"
        )


CREDIT_FIELD_DEFAULTS = {
    "lifetime_free_remaining": 3,
    "credits_remaining": 0,
    "topup_credits_remaining": 0,
    "credits_period_start": None,
    "credits_period_end": None,
    "credits_frozen": False,
}


def _ensure_credit_fields(db_client, uid: str, user_data: dict) -> None:
    """Idempotent: lazy-add credit machinery fields with defaults.

    Phase 0 step 1.4e narrow build. Schema only — Phase 1 ships the
    consumer (POST /content/generate) that reads credits_remaining and
    decrements per generation. Lazy backfill mirrors _ensure_family_id
    / _ensure_subscription_fields / _ensure_email_field shapes.

    Defaults:
      lifetime_free_remaining = 3   (everyone gets the onboarding burst,
                                     even existing users — they've never
                                     been gated, so 3 fresh starts is
                                     fair)
      credits_remaining       = 0   (premium users get 30 seeded by
                                     subscription.created webhook)
      topup_credits_remaining = 0
      credits_period_*        = null
      credits_frozen          = false

    Same race semantics as the other ensure helpers.
    """
    missing = {
        k: v
        for k, v in CREDIT_FIELD_DEFAULTS.items()
        if k not in user_data
    }
    if not missing:
        return
    user_data.update(missing)
    try:
        db_client.collection("users").document(uid).update(missing)
        if uid in _local_users:
            _local_users[uid].update(missing)
    except Exception as e:
        logger.warning(f"credit field backfill failed for uid={uid}: {e}")


def _ensure_onboarding_complete(db_client, uid: str, user_data: dict) -> None:
    """Lazy-backfill onboarding_complete bool.

    Phase 0 onboarding gate fix. Existing 53 records have username +
    child_age from the legacy hardcoded-password signup flow → marked
    complete=true on first read so AppShell doesn't bounce them.

    New magic-link signup_new users have neither field populated →
    marked complete=false so AppShell routes them to /onboarding to
    pick username + child_age + language preference.

    Same race semantics as the other ensure_* helpers (last-write-wins,
    brief divergence acceptable). Idempotent.
    """
    if "onboarding_complete" in user_data:
        return
    has_username = bool(user_data.get("username"))
    has_child_age = user_data.get("child_age") is not None
    complete = bool(has_username and has_child_age)
    user_data["onboarding_complete"] = complete
    try:
        db_client.collection("users").document(uid).update({"onboarding_complete": complete})
        if uid in _local_users:
            _local_users[uid]["onboarding_complete"] = complete
    except Exception as e:
        logger.warning(f"onboarding_complete backfill failed uid={uid}: {e}")


def _ensure_username_lowercase(db_client, uid: str, user_data: dict) -> None:
    """Lazy-backfill username_lowercase on user records.

    Phase 0 step 1.5e (case-insensitive lookup fix). Original `username`
    field preserved for display; `username_lowercase` becomes the
    canonical case-insensitive lookup key. Idempotent — no-op when the
    field is already present.

    Same race semantics as the other ensure_* helpers (last-write-wins,
    brief divergence acceptable).
    """
    if "username_lowercase" in user_data:
        return
    username = user_data.get("username") or ""
    if not username:
        return
    lc = username.lower()
    user_data["username_lowercase"] = lc
    try:
        db_client.collection("users").document(uid).update({"username_lowercase": lc})
        if uid in _local_users:
            _local_users[uid]["username_lowercase"] = lc
    except Exception as e:
        logger.warning(f"username_lowercase backfill failed uid={uid}: {e}")


def _ensure_email_field(db_client, uid: str, user_data: dict) -> None:
    """Idempotent: lazy-add email=null on records missing the field.

    CRITICAL: does NOT add email_verified. The absence of email_verified is
    the legacy-tolerance signal the AppShell gate relies on (see spec
    section "Frontend surface > AppShell.js"). email_verified is set true
    ONLY by app.services.magic_link.verify_code.
    """
    if "email" in user_data:
        return
    user_data["email"] = None
    try:
        db_client.collection("users").document(uid).update({"email": None})
        if uid in _local_users:
            _local_users[uid]["email"] = None
    except Exception as e:
        logger.warning(f"email field backfill failed for uid={uid}: {e}")


# Phase 0 step 1.5: token TTL + sliding refresh.
# Tokens minted pre-1.5 lack expires_at — treated as legacy until the
# migration script revokes them en masse.
_SESSION_TTL_SECONDS = 30 * 24 * 3600
_SESSION_REFRESH_GATE_SECONDS = 24 * 3600


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _iso_to_dt(iso: Optional[str]):
    if not iso:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return None


def local_verify_token(token: str) -> Optional[dict]:
    """Verify a bearer token.

    Rules:
      - Token must exist in tokens collection.
      - revoked_at must be null (revocation enforced).
      - expires_at, if present, must be in the future (legacy tokens
        without expires_at fall through — they're tolerated until the
        migration script revokes them).
      - Sliding refresh: if last_used_at > 24h ago, extend expires_at by
        30 days and bump last_used_at. Skipped on legacy tokens.
    """
    _load_persisted_tokens()
    uid = _local_tokens.get(token)
    if not uid or uid not in _local_users:
        return None

    # Read the persistent token row for status fields.
    try:
        from app.services.local_store import get_local_store
        store = get_local_store()
        token_doc = store.collection("tokens").document(token).get()
        token_row = token_doc.to_dict() if token_doc.exists else None
    except Exception:
        token_row = None

    if token_row:
        if token_row.get("revoked_at"):
            # Hard reject + scrub cache so subsequent requests don't re-hit disk.
            _local_tokens.pop(token, None)
            return None
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        expires_dt = _iso_to_dt(token_row.get("expires_at"))
        if expires_dt is not None:
            if expires_dt < now:
                _local_tokens.pop(token, None)
                return None
            # Sliding refresh gate
            last_used_dt = _iso_to_dt(token_row.get("last_used_at"))
            if last_used_dt is None or (now - last_used_dt).total_seconds() > _SESSION_REFRESH_GATE_SECONDS:
                try:
                    store.collection("tokens").document(token).update({
                        "last_used_at": now.isoformat(),
                        "expires_at": (now + timedelta(seconds=_SESSION_TTL_SECONDS)).isoformat(),
                    })
                except Exception as e:
                    logger.warning(f"sliding refresh failed for token: {e}")
        # Else: legacy token (no expires_at) — accepted until migration revokes.

    return _local_users[uid]


async def get_current_user(
    authorization: Optional[str] = Header(None),
    settings: Settings = Depends(get_settings),
) -> Dict[str, str]:
    """Get current user from auth token."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
        )

    token = authorization.replace("Bearer ", "")

    if _check_local_mode():
        user = local_verify_token(token)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        # Lazy backfill chain. Each helper is idempotent and fast on cached records.
        family_id = user.get("family_id")
        if not family_id or "email" not in user:
            try:
                db = get_db_client()
                user_doc = db.collection("users").document(user["uid"]).get()
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    family_id = _ensure_family_id(db, user["uid"], user_data)
                    _ensure_subscription_fields(db, user["uid"], user_data)
                    _ensure_email_field(db, user["uid"], user_data)
                    _ensure_credit_fields(db, user["uid"], user_data)
                    _ensure_username_lowercase(db, user["uid"], user_data)
                    _ensure_onboarding_complete(db, user["uid"], user_data)
            except Exception as e:
                logger.warning(f"backfill chain in get_current_user failed: {e}")
        return {
            "uid": user["uid"],
            "email": user.get("email") or "",
            "username": user.get("username", ""),
            "family_id": family_id or "",
            "email_verified": bool(user.get("email_verified")),
            # subscription_tier surfaced so backlog gating can read it without
            # an extra disk hit. May be None for legacy records prior to 1.4b.
            "subscription_tier": user.get("subscription_tier") or "free",
            # Onboarding gate signal — frontend AppShell reads via /users/me.
            "onboarding_complete": bool(user.get("onboarding_complete")),
            "child_age": user.get("child_age"),
            "preferred_lang": user.get("preferred_lang"),
            # _token passes the bearer through so /auth/logout can revoke it.
            "_token": token,
        }
    else:
        try:
            from firebase_admin import auth as firebase_auth
            decoded = firebase_auth.verify_id_token(token)
            return {"uid": decoded["uid"], "email": decoded.get("email", "")}
        except Exception as e:
            logger.error(f"Firebase token verification failed: {e}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def admin_bypass(x_admin_key: Optional[str] = Header(None)) -> bool:
    """Return True iff caller passes a valid X-Admin-Key matching
    ADMIN_API_KEY env. Used by ops tooling (deploy_guard, content audit)
    to bypass tier-gated filters and see the full catalog.

    Anonymous + non-admin callers get False; backlog filter applies
    normally.
    """
    expected = os.getenv("ADMIN_API_KEY", "").strip()
    if not expected:
        return False
    return bool(x_admin_key) and x_admin_key == expected


async def get_optional_user(
    authorization: Optional[str] = Header(None),
    settings: Settings = Depends(get_settings),
) -> Optional[Dict[str, str]]:
    """Get current user if authenticated, otherwise None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return await get_current_user(authorization, settings)
    except HTTPException:
        return None


# Phase 0 step 1.4e: dropped check_rate_limit Depends function (was
# defined but never wired to any endpoint as a FastAPI dependency).
# Kept RateLimiter class — app/api/v1/blog.py instantiates it directly
# for blog comment/like rate limiting, distinct from the user-auth
# rate limit path. Per-tier enforcement is now in app/utils/backlog.py
# (the live backlog gating); credit gating ships with Phase 1's
# POST /content/generate.


class RateLimiter:
    """In-memory sliding-window rate limiter, keyed on caller-supplied id.

    Used by app/api/v1/blog.py for comment/like rate limiting. Not
    wired to user-auth flows (those use the magic-link rate limiter
    in app/services/magic_link.py).
    """

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, list] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        if key not in self.requests:
            self.requests[key] = []
        self.requests[key] = [t for t in self.requests[key] if t > cutoff]
        if len(self.requests[key]) < self.max_requests:
            self.requests[key].append(now)
            return True
        return False
