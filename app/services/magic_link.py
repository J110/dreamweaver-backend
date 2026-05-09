"""Magic-link auth core.

Implements the two-token model from docs/specs/auth-magic-link-v1.md:
  - auth_codes (new collection)  : short-lived 15-min single-use codes
  - tokens     (extended schema) : long-lived 30-day sliding sessions

Public API:
  request_magic_link(email, lang, context, initiator_ip) -> dict
  verify_code(code) -> dict
  poll_session(initiator_session_id) -> dict
  revoke_token(token, reason) -> bool
  request_claim(target_uid, target_email, lang, initiator_ip) -> dict

Internals:
  generate_code()                 — secrets.token_urlsafe(32)
  generate_session_id()           — uuid.uuid4()
  check_and_record_rate_limit()   — 3 per email per hour, in-memory
  _email_hash(email)              — sha256 for analytics distinct_id
  _lookup_user_by_email(email)    — LocalStore scan
  _create_user_with_email(...)    — username derivation with collision suffix

Side effects:
  - Sends email via Resend (best-effort; soft fail).
  - Emits PostHog events per spec §11.
  - Writes auth_codes + tokens rows in LocalStore.

Anti-enumeration: rate-limit excess and missing-email lookups still
return {status:"sent"}; we do not leak existence to the wire. The
`migration_marker.json` file gates a WARNING log for missed
login_existing lookups during the 30-day post-migration window.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from app.services.analytics_posthog import emit_event as ph_emit
from app.services.email_send import send_email_via_resend
from app.services.email_templates import build_magic_link_email
from app.services.local_store import get_local_store
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants per spec ──────────────────────────────────────

CODE_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=30)
SESSION_REFRESH_GATE = timedelta(hours=24)

RATE_LIMIT_WINDOW_SECONDS = 3600
RATE_LIMIT_MAX_REQUESTS = 3

VALID_CONTEXTS = ("signup_new", "login_existing", "claim_existing")

# Rate-limit bucket — in-memory, prune-on-access.
_link_rate_buckets: dict[str, list[float]] = {}

# Migration marker (written by scripts/invalidate_old_tokens.py at deploy).
# When present and within 30 days, missed login_existing lookups log WARNING.
MIGRATION_MARKER_PATH = Path("data/migration_marker.json")


# ── Generators ───────────────────────────────────────────────


def generate_code() -> str:
    """Unguessable, URL-safe, 32-byte (~43-char) magic-link code."""
    return secrets.token_urlsafe(32)


def generate_session_id() -> str:
    """initiator_session_id — UUIDv4 stringified."""
    return str(uuid.uuid4())


def generate_session_token() -> str:
    """Bearer session token; replaces the legacy sha256(uid:time) format."""
    return secrets.token_urlsafe(32)


def _email_hash(email: str) -> str:
    return hashlib.sha256((email or "").lower().encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts() -> float:
    return time.time()


# ── Rate limiting ────────────────────────────────────────────


def check_and_record_rate_limit(email_lc: str) -> bool:
    """Return True if request is allowed, False if over the 3/hour budget.

    Prunes entries > 1h on every call. State loss on container restart is
    acceptable — the window is too small for restart abuse to matter.
    """
    now = _ts()
    bucket = _link_rate_buckets.setdefault(email_lc, [])
    bucket[:] = [t for t in bucket if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
        return False
    bucket.append(now)
    return True


# ── Migration window detection ──────────────────────────────


def _within_migration_window() -> bool:
    """Read data/migration_marker.json. True if present + non-expired."""
    try:
        if not MIGRATION_MARKER_PATH.exists():
            return False
        with open(MIGRATION_MARKER_PATH) as f:
            data = json.load(f)
        expires_at = data.get("expires_at")
        if not expires_at:
            return False
        return datetime.fromisoformat(expires_at) > datetime.now(timezone.utc)
    except Exception as e:
        logger.warning("migration_marker read failed: %s", e)
        return False


# ── User lookup helpers ─────────────────────────────────────


def _lookup_user_by_email(store, email_lc: str) -> Optional[dict]:
    """Find a user record by lowercased email. None if not found."""
    if not email_lc:
        return None
    try:
        # LocalStore .where() returns CollectionRef-like; .get() returns list of snapshots.
        rows = store.collection("users").where("email", "==", email_lc).get()
        for doc in rows:
            data = doc.to_dict()
            if data and data.get("email", "").lower() == email_lc:
                return data
    except Exception as e:
        logger.warning("user lookup by email failed: %s", e)
    return None


def _username_taken(store, username: str) -> bool:
    """Case-insensitive existence check via username_lowercase.

    Phase 0 step 1.5e. Falls back to a case-sensitive scan over the
    original `username` field for legacy records that lack
    username_lowercase (the lazy backfill in get_current_user populates
    it on next read; this fallback ensures a fresh signup can't false-
    negative against an un-backfilled record).
    """
    target = (username or "").lower()
    if not target:
        return False
    try:
        rows = store.collection("users").where("username_lowercase", "==", target).get()
        if any(doc.exists for doc in rows):
            return True
    except Exception:
        pass
    # Fallback: case-sensitive scan for un-backfilled records.
    try:
        rows = store.collection("users").where("username", "==", username).get()
        return any(doc.exists for doc in rows)
    except Exception:
        return False


def _derive_unique_username(store, email_lc: str) -> str:
    """email local-part with collision suffix: alice, alice2, alice3, ..."""
    local_part = email_lc.split("@", 1)[0]
    base = re.sub(r"[^a-z0-9_]", "", local_part) or "user"
    if not _username_taken(store, base):
        return base
    for n in range(2, 1000):
        candidate = f"{base}{n}"
        if not _username_taken(store, candidate):
            return candidate
    # Fallback — extremely unlikely to hit
    return f"{base}_{secrets.token_hex(3)}"


def _create_user_with_email(store, email_lc: str) -> dict:
    """Mint a brand-new user record. signup_new path.

    Username derived from email local-part with collision suffix.
    family_id minted upfront (consistent with auth.py:signup pattern).
    Password field intentionally absent (Phase 1 drops password storage).
    """
    uid = hashlib.sha256(f"{email_lc}:{secrets.token_hex(8)}".encode()).hexdigest()[:28]
    username = _derive_unique_username(store, email_lc)
    family_id = str(uuid.uuid4())
    created_at = _now_iso()
    user_data = {
        "id": uid,
        "uid": uid,
        "username": username,
        # Phase 0 step 1.5e: username_lowercase is the canonical
        # case-insensitive lookup key. Derived usernames are already
        # lowercase (from email local-part), but write explicitly for
        # consistency with future case-mixed signup paths.
        "username_lowercase": username.lower(),
        "email": email_lc,
        "email_verified": True,
        "child_age": 5,  # default; updated via /users/me later
        "subscription_tier": "free",
        "created_at": created_at,
        "daily_usage": 0,
        "preferences": {},
        "family_id": family_id,
    }
    store.collection("users").document(uid).set(user_data)
    # Update in-memory cache too, so subsequent token-verify reads see it.
    try:
        from app.dependencies import _local_users
        _local_users[uid] = user_data
    except Exception:
        pass
    logger.info("New user created via magic-link: username=%s uid=%s family_id=%s", username, uid, family_id)
    return user_data


def _set_user_email_verified(store, uid: str, email_lc: Optional[str]) -> None:
    """Persist email_verified=true and (optionally) email on a user record."""
    update = {"email_verified": True}
    if email_lc:
        update["email"] = email_lc
    try:
        store.collection("users").document(uid).update(update)
        from app.dependencies import _local_users
        if uid in _local_users:
            _local_users[uid].update(update)
    except Exception as e:
        logger.warning("set_user_email_verified failed uid=%s: %s", uid, e)


# ── Auth codes ───────────────────────────────────────────────


def _write_auth_code(
    store,
    code: str,
    email_lc: str,
    context: str,
    lang: str,
    initiator_session_id: str,
    initiator_ip: Optional[str],
    target_uid: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)
    row = {
        "code": code,
        "email": email_lc,
        "context": context,
        "lang": lang,
        "created_at": now.isoformat(),
        "expires_at": (now + CODE_TTL).isoformat(),
        "consumed_at": None,
        "initiator_session_id": initiator_session_id,
        "initiator_ip": initiator_ip,
        "claimed_token": None,
        "target_uid": target_uid,
    }
    store.collection("auth_codes").document(code).set(row)


def _read_auth_code(store, code: str) -> Optional[dict]:
    try:
        doc = store.collection("auth_codes").document(code).get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        logger.warning("auth_code read failed code=%s: %s", code, e)
    return None


def _read_auth_code_by_session(store, session_id: str) -> Optional[dict]:
    try:
        rows = store.collection("auth_codes").where("initiator_session_id", "==", session_id).get()
        for doc in rows:
            data = doc.to_dict()
            if data and data.get("initiator_session_id") == session_id:
                return data
    except Exception as e:
        logger.warning("auth_code lookup by session failed: %s", e)
    return None


def _delete_auth_code(store, code: str) -> None:
    """Best-effort deletion. LocalStore exposes no .delete(); set-with-tombstone."""
    try:
        # LocalStore has no delete primitive in our wrapper. Mark consumed + clear claimed_token
        # so re-poll returns waiting/expired and the row is harmless.
        store.collection("auth_codes").document(code).update({
            "claimed_token": None,
            "consumed_at": _now_iso(),
        })
    except Exception as e:
        logger.warning("auth_code soft-delete failed code=%s: %s", code, e)


# ── Session tokens ──────────────────────────────────────────


def _persist_token_row(
    store,
    token: str,
    uid: str,
    claimed_by_session_id: str,
) -> None:
    now = datetime.now(timezone.utc)
    row = {
        "id": token,
        "token": token,
        "uid": uid,
        "created_at": now.isoformat(),
        "expires_at": (now + SESSION_TTL).isoformat(),
        "last_used_at": now.isoformat(),
        "revoked_at": None,
        "revocation_reason": None,
        "claimed_by_session_id": claimed_by_session_id,
    }
    store.collection("tokens").document(token).set(row)
    # Also seed the in-memory cache so verify_token works without disk read.
    try:
        from app.dependencies import _local_tokens
        _local_tokens[token] = uid
    except Exception:
        pass


def revoke_token(token: str, reason: str = "logout") -> bool:
    """Set revoked_at on the token row. Used by /auth/logout."""
    if not token:
        return False
    try:
        store = get_local_store()
        store.collection("tokens").document(token).update({
            "revoked_at": _now_iso(),
            "revocation_reason": reason,
        })
        # Drop from in-memory cache so verify_token returns None immediately.
        try:
            from app.dependencies import _local_tokens
            _local_tokens.pop(token, None)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.warning("revoke_token failed: %s", e)
        return False


# ── Public API ──────────────────────────────────────────────


async def request_magic_link(
    email: str,
    lang: str,
    context: str,
    initiator_ip: Optional[str] = None,
) -> dict:
    """Issue a magic-link code + send the email.

    Always returns {"initiator_session_id", "status": "sent"} regardless of
    whether email actually exists / was rate-limited / send failed —
    anti-enumeration. The session_id binds the eventual token to this
    initiator device via Pattern A polling.
    """
    if context not in VALID_CONTEXTS or context == "claim_existing":
        # claim_existing routes through request_claim() which adds target_uid
        raise ValueError(f"invalid context for request_magic_link: {context}")

    email_lc = (email or "").strip().lower()
    initiator_session_id = generate_session_id()
    lang = "hi" if lang == "hi" else "en"

    # Rate-limit gate — return generic-sent without sending.
    if not check_and_record_rate_limit(email_lc):
        ph_emit(
            _email_hash(email_lc),
            "auth_rate_limited",
            {"email_hash": _email_hash(email_lc), "lang": lang, "context": context},
        )
        ph_emit(
            _email_hash(email_lc),
            "auth_request_link",
            {
                "email_hash": _email_hash(email_lc),
                "lang": lang,
                "context": context,
                "rate_limited": True,
            },
        )
        return {"initiator_session_id": initiator_session_id, "status": "sent"}

    store = get_local_store()
    user = _lookup_user_by_email(store, email_lc)

    # Silently switch context to match reality (anti-enumeration).
    effective_context = context
    if user and context == "signup_new":
        effective_context = "login_existing"
    elif not user and context == "login_existing":
        effective_context = "signup_new"
        if _within_migration_window():
            logger.warning(
                "login_existing email not matched during migration window — "
                "possible stuck legacy user. email=%s lang=%s ts=%s ip=%s",
                email_lc, lang, _now_iso(), initiator_ip,
            )

    code = generate_code()
    _write_auth_code(
        store, code, email_lc, effective_context, lang,
        initiator_session_id, initiator_ip,
    )

    base = os.getenv("WEB_BASE_URL", "https://dreamvalley.app").rstrip("/")
    magic_url = f"{base}/auth/verify?code={code}&lang={lang}"
    subject, html = build_magic_link_email(
        magic_url, effective_context, lang,
        username=(user or {}).get("username", ""),
    )

    sent = await send_email_via_resend(email_lc, subject, html)
    if not sent:
        logger.warning(
            "magic-link send failed (returning generic-sent anyway) email=%s context=%s",
            email_lc, effective_context,
        )

    ph_emit(
        _email_hash(email_lc),
        "auth_request_link",
        {
            "email_hash": _email_hash(email_lc),
            "lang": lang,
            "context": effective_context,
            "rate_limited": False,
        },
    )
    return {"initiator_session_id": initiator_session_id, "status": "sent"}


async def request_claim(
    target_uid: str,
    target_email: str,
    lang: str,
    initiator_ip: Optional[str] = None,
) -> dict:
    """Claim flow for an authenticated existing user adding their email.

    Same rate-limit + send pattern as request_magic_link, but uses
    claim_existing template. The auth_codes row carries target_uid so
    verify_code knows to attach the email to that record (NOT create new).
    """
    email_lc = (target_email or "").strip().lower()
    initiator_session_id = generate_session_id()
    lang = "hi" if lang == "hi" else "en"

    if not check_and_record_rate_limit(email_lc):
        ph_emit(
            _email_hash(email_lc),
            "auth_rate_limited",
            {"email_hash": _email_hash(email_lc), "lang": lang, "context": "claim_existing"},
        )
        return {"initiator_session_id": initiator_session_id, "status": "sent"}

    store = get_local_store()
    code = generate_code()
    _write_auth_code(
        store, code, email_lc, "claim_existing", lang,
        initiator_session_id, initiator_ip, target_uid=target_uid,
    )

    # Look up user for username to personalize the email.
    user = None
    try:
        doc = store.collection("users").document(target_uid).get()
        if doc.exists:
            user = doc.to_dict()
    except Exception:
        pass

    base = os.getenv("WEB_BASE_URL", "https://dreamvalley.app").rstrip("/")
    magic_url = f"{base}/auth/verify?code={code}&lang={lang}"
    subject, html = build_magic_link_email(
        magic_url, "claim_existing", lang,
        username=(user or {}).get("username", ""),
    )

    await send_email_via_resend(email_lc, subject, html)

    ph_emit(
        _email_hash(email_lc),
        "auth_request_link",
        {
            "email_hash": _email_hash(email_lc),
            "lang": lang,
            "context": "claim_existing",
            "rate_limited": False,
        },
    )
    return {"initiator_session_id": initiator_session_id, "status": "sent"}


def verify_code(code: str) -> dict:
    """Consume a magic-link code, mint a session token bound to the initiator.

    Returns {"status": "claimed"|"already_used"|"expired"|"invalid",
             "context": str|None}.
    Never returns the token here — the clicker device must not log in.
    The token is fetched by the initiator via /auth/poll.
    """
    store = get_local_store()
    row = _read_auth_code(store, code)
    if not row:
        return {"status": "invalid", "context": None}

    context = row.get("context")
    family_id = None
    is_new_user = False

    if row.get("consumed_at"):
        ph_emit(_email_hash(row.get("email", "")), "auth_link_already_used", {"context": context})
        return {"status": "already_used", "context": context}

    try:
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            ph_emit(_email_hash(row.get("email", "")), "auth_link_expired", {"context": context})
            return {"status": "expired", "context": context}
    except Exception:
        return {"status": "invalid", "context": context}

    email_lc = row.get("email", "")

    # Resolve user per context.
    if context == "claim_existing":
        target_uid = row.get("target_uid")
        if not target_uid:
            logger.warning("claim_existing code missing target_uid: %s", code)
            return {"status": "invalid", "context": context}
        try:
            doc = store.collection("users").document(target_uid).get()
            if not doc.exists:
                return {"status": "invalid", "context": context}
            user_data = doc.to_dict()
            family_id = user_data.get("family_id")
            _set_user_email_verified(store, target_uid, email_lc)
        except Exception as e:
            logger.warning("claim_existing user resolve failed: %s", e)
            return {"status": "invalid", "context": context}
        uid = target_uid
    else:
        user_data = _lookup_user_by_email(store, email_lc)
        if user_data is None:
            if context == "login_existing":
                # Drift from request-time. Treat as signup_new for safety.
                user_data = _create_user_with_email(store, email_lc)
                is_new_user = True
            else:
                user_data = _create_user_with_email(store, email_lc)
                is_new_user = True
        else:
            _set_user_email_verified(store, user_data["uid"], None)
        uid = user_data["uid"]
        family_id = user_data.get("family_id")

    # Mint session token, bind to initiator session.
    session_id = row["initiator_session_id"]
    token = generate_session_token()
    _persist_token_row(store, token, uid, session_id)

    # Mark code consumed + stash claimed_token so poll picks it up.
    try:
        store.collection("auth_codes").document(code).update({
            "consumed_at": _now_iso(),
            "claimed_token": token,
        })
    except Exception as e:
        logger.warning("auth_code consume update failed: %s", e)

    # Time-to-click for funnel analytics.
    seconds_to_click = None
    try:
        seconds_to_click = int(
            (datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"])).total_seconds()
        )
    except Exception:
        pass

    ph_emit(family_id or _email_hash(email_lc), "auth_link_clicked", {
        "context": context,
        "time_to_click_seconds": seconds_to_click,
    })
    ph_emit(family_id or _email_hash(email_lc), "auth_verified", {
        "uid": uid,
        "family_id": family_id,
        "context": context,
        "is_new_user": is_new_user,
    })

    return {"status": "claimed", "context": context}


def poll_session(initiator_session_id: str) -> dict:
    """Initiator polls for the claimed token.

    Returns one of:
      {"status": "waiting"}
      {"status": "ready", token, uid, username, family_id, email_verified, context}
      {"status": "expired"}

    First successful read deletes the auth_codes row (soft-delete via
    consumed_at + claimed_token=None) so the token cannot be re-fetched.
    """
    if not initiator_session_id:
        return {"status": "expired"}

    store = get_local_store()
    row = _read_auth_code_by_session(store, initiator_session_id)
    if not row:
        return {"status": "expired"}

    claimed_token = row.get("claimed_token")
    if not claimed_token:
        # Still pending — but maybe expired without being claimed.
        try:
            if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
                return {"status": "expired"}
        except Exception:
            return {"status": "expired"}
        return {"status": "waiting"}

    # Resolve user fields for the response.
    try:
        token_doc = store.collection("tokens").document(claimed_token).get()
        token_row = token_doc.to_dict() if token_doc.exists else None
        if not token_row:
            return {"status": "expired"}
        uid = token_row["uid"]
        user_doc = store.collection("users").document(uid).get()
        user_data = user_doc.to_dict() if user_doc.exists else {}
    except Exception as e:
        logger.warning("poll resolve failed: %s", e)
        return {"status": "expired"}

    response = {
        "status": "ready",
        "token": claimed_token,
        "uid": uid,
        "username": user_data.get("username", ""),
        "family_id": user_data.get("family_id", ""),
        "email_verified": bool(user_data.get("email_verified")),
        "context": row.get("context"),
    }

    # First read wins: scrub claimed_token so re-poll returns expired.
    _delete_auth_code(store, row.get("code", ""))
    return response
