"""Restore codes — 6-digit email-CODE restore flow for native app sign-in.

Distinct from the magic-link service (auth_codes) which uses 32-byte URL-safe
codes embedded in clickable URLs. This module uses NUMERIC 6-digit codes
meant to be TYPED into the native app, so the resulting session token lands
in the WebView session (forwardable to native Keychain via the bridge) —
NOT in a browser tab the user clicked a link from.

Public API:
  request_restore_code(email)            — async, sends code via Resend
  verify_restore_code(email, code)       — sync, mints session token on success

Storage (direct disk-backed via LocalStore, NO in-memory cache by design —
sidesteps the load-on-boot risk class. Disk IS the cache for low-throughput
short-lived data):
  restore_codes/{email_lc}                — { email, family_id, code_hash, salt, attempts, ... }
  rate_limits/{key}                       — { timestamps: [t1, t2, ...] }

Anti-enumeration:
  - send-code: strictly uniform "sent" response regardless of email match.
    Rate-limit signal (429) is keyed on email — leaks only "this email has
    been spammed" not "this email is registered."
  - verify-code: returns "invalid_or_expired" for ALL failure modes EXCEPT
    one — when there's no row AND no matching user (the wrong-email path),
    returns "no_subscription". This single controlled breach fires only
    post-verify (not at send), so its enumeration value is marginal vs the
    anti-churn UX value of telling a confused user "try the email on your
    payment receipt." Wrong CODE for a valid email returns
    "invalid_or_expired" — never "no_subscription."

Token issuance:
  Mints via app.services.magic_link.mint_device_token — same shape as
  device-anchored auth (32-byte opaque, persisted in `tokens` collection,
  365d sliding TTL). No privilege inconsistency — restore gets the SAME
  credential a normal login gets. Audit distinguishes via session_id prefix.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from app.services.email_send import send_email_via_resend
from app.services.email_templates import build_restore_code_email
from app.services.local_store import get_local_store
from app.services.magic_link import mint_device_token
from app.utils.logger import get_logger

logger = get_logger(__name__)

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS_PER_CODE = 3
SEND_RATE_LIMIT_WINDOW_SECONDS = 3600
SEND_RATE_LIMIT_MAX = 5


# ── Helpers ────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _norm_email(email: str) -> str:
    """Lowercase + strip. No Gmail-dot stripping — false-positive merges are
    worse than the false-negative they prevent."""
    return (email or "").strip().lower()


def _generate_code() -> str:
    """6-digit numeric, zero-padded. secrets.randbelow → CSPRNG."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_code(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def _new_salt() -> str:
    return secrets.token_hex(16)


# ── User lookup ────────────────────────────────────────────────


def _lookup_user_by_recovery_email(email_lc: str) -> Optional[dict]:
    """Find user by recovery_email (primary) then billing_email (fallback).

    Match is on the lowercase comparison; storage is already lowercased on
    capture (webhook + backfill both normalize). The billing_email fallback
    handles users with a billing_email but no recovery_email yet — should
    be empty after the one-time backfill, but kept as defense-in-depth.
    """
    if not email_lc:
        return None
    # Force a load so a cold worker sees existing users (mirrors
    # _find_user_by_customer in billing.py).
    from app.dependencies import _load_persisted_tokens, _local_users
    _load_persisted_tokens()
    for uid, user in _local_users.items():
        re_ = (user.get("recovery_email") or "").lower()
        if re_ and re_ == email_lc:
            data = {**user}
            data.setdefault("uid", uid)
            return data
    for uid, user in _local_users.items():
        be_ = (user.get("billing_email") or "").lower()
        if be_ and be_ == email_lc:
            data = {**user}
            data.setdefault("uid", uid)
            return data
    return None


# ── Rate limit (disk-backed sliding window) ────────────────────


def _rate_limit_check_and_record(
    key: str, window_seconds: int, max_requests: int
) -> Tuple[bool, int]:
    """Sliding-window rate limit, disk-backed. Returns (allowed, retry_after).

    Storage: rate_limits/{sanitized_key} → { timestamps: [t1, t2, ...] }.
    Prunes > window on each access. Survives restart (disk-backed).
    """
    store = get_local_store()
    doc_id = key.replace(":", "_").replace("/", "_")
    now_ts = time.time()
    try:
        doc = store.collection("rate_limits").document(doc_id).get()
        existing = doc.to_dict() if doc.exists else {}
        timestamps = list(existing.get("timestamps") or [])
    except Exception:
        timestamps = []
    timestamps = [t for t in timestamps if now_ts - t < window_seconds]
    if len(timestamps) >= max_requests:
        oldest = timestamps[0]
        retry_after = int(window_seconds - (now_ts - oldest)) + 1
        return False, max(retry_after, 1)
    timestamps.append(now_ts)
    try:
        store.collection("rate_limits").document(doc_id).set({
            "key": key,
            "timestamps": timestamps,
            "updated_at": _now_iso(),
        })
    except Exception as e:
        logger.warning("rate_limit persist failed key=%s: %s", key, e)
    return True, 0


# ── Code store (disk-backed) ──────────────────────────────────


def _write_code_row(email_lc: str, family_id: str, code: str) -> None:
    store = get_local_store()
    salt = _new_salt()
    row = {
        "email": email_lc,
        "family_id": family_id,
        "code_hash": _hash_code(code, salt),
        "salt": salt,
        "created_at": _now_iso(),
        "expires_at": (_now() + CODE_TTL).isoformat(),
        "attempts": 0,
        "used": False,
    }
    store.collection("restore_codes").document(email_lc).set(row)


def _read_code_row(email_lc: str) -> Optional[dict]:
    store = get_local_store()
    try:
        doc = store.collection("restore_codes").document(email_lc).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.warning("restore_code read failed email=%s: %s", email_lc, e)
        return None


def _update_code_row(email_lc: str, fields: dict) -> None:
    store = get_local_store()
    try:
        store.collection("restore_codes").document(email_lc).update(fields)
    except Exception as e:
        logger.warning("restore_code update failed email=%s: %s", email_lc, e)


# ── Public API ────────────────────────────────────────────────


async def request_restore_code(email: str) -> dict:
    """Send a 6-digit code to email if it matches a subscriber.

    Returns:
      {"status": "sent"}                              — always on allow (uniform)
      {"status": "rate_limited", "retry_after_seconds": N} — on rate-limit

    The "sent" response is identical for matched and unmatched emails; existence
    is not leaked. Rate-limit (429) is keyed on email and leaks only
    "this email has been spammed," not "this email is registered."
    """
    email_lc = _norm_email(email)
    if not email_lc:
        return {"status": "sent"}

    allowed, retry_after = _rate_limit_check_and_record(
        f"restore_send:{email_lc}",
        SEND_RATE_LIMIT_WINDOW_SECONDS,
        SEND_RATE_LIMIT_MAX,
    )
    if not allowed:
        return {"status": "rate_limited", "retry_after_seconds": retry_after}

    user = _lookup_user_by_recovery_email(email_lc)

    if user:
        code = _generate_code()
        _write_code_row(email_lc, user.get("family_id", ""), code)
        subject, html = build_restore_code_email(code, lang="en")
        sent = await send_email_via_resend(email_lc, subject, html)
        if not sent:
            logger.warning(
                "restore_code email send failed email=%s (code generated, anti-enum response sent)",
                email_lc,
            )
    else:
        logger.info(
            "restore_code request for unknown email=%s (uniform response, no code generated)",
            email_lc,
        )

    return {"status": "sent"}


def verify_restore_code(email: str, code: str) -> dict:
    """Verify code; mint and return a session token on success.

    Returns one of:
      {"status": "claimed", "token": "...", "uid": "...", "family_id": "..."}
      {"status": "invalid_or_expired"}
      {"status": "no_subscription"}     — wrong-email path (controlled leak)
      {"status": "too_many_attempts"}

    Distinguishing logic:
      - WRONG CODE for a valid email          → invalid_or_expired
      - Code expired / consumed / not found   → invalid_or_expired
      - Wrong EMAIL (no row AND no user)      → no_subscription   ← controlled leak
      - Code attempts exhausted               → too_many_attempts

    The no_subscription leak fires ONLY on a failed verify (post-send), so
    its enumeration value is marginal — an attacker would need to type a
    6-digit code first. Wrong CODE for a real email stays uniform.
    """
    email_lc = _norm_email(email)
    code = (code or "").strip()
    if not email_lc or not code:
        return {"status": "invalid_or_expired"}

    user = _lookup_user_by_recovery_email(email_lc)
    row = _read_code_row(email_lc)

    # Wrong-email path: no row AND no matching user → controlled leak.
    if not row and not user:
        return {"status": "no_subscription"}

    # Row missing but user exists (code expired/swept). Uniform.
    if not row:
        return {"status": "invalid_or_expired"}

    if row.get("used"):
        return {"status": "invalid_or_expired"}

    try:
        if datetime.fromisoformat(row["expires_at"]) < _now():
            return {"status": "invalid_or_expired"}
    except Exception:
        return {"status": "invalid_or_expired"}

    if row.get("attempts", 0) >= MAX_ATTEMPTS_PER_CODE:
        return {"status": "too_many_attempts"}

    # Constant-time compare.
    submitted_hash = _hash_code(code, row.get("salt", ""))
    if not hmac.compare_digest(submitted_hash, row.get("code_hash", "")):
        new_attempts = row.get("attempts", 0) + 1
        update = {"attempts": new_attempts}
        if new_attempts >= MAX_ATTEMPTS_PER_CODE:
            update["used"] = True  # kill the code after 3 wrong tries
        _update_code_row(email_lc, update)
        return {"status": "invalid_or_expired"}

    # Success: mint session token, mark code consumed.
    if not user:
        # Race: code issued but user gone. Fail closed.
        return {"status": "invalid_or_expired"}

    uid = user.get("uid") or user.get("id")
    if not uid:
        return {"status": "invalid_or_expired"}

    store = get_local_store()
    token = mint_device_token(store, uid)
    _update_code_row(email_lc, {"used": True})

    logger.info(
        "restore_code claimed email=%s uid=%s family_id=%s",
        email_lc, uid, row.get("family_id") or user.get("family_id", ""),
    )
    return {
        "status": "claimed",
        "token": token,
        "uid": uid,
        "family_id": row.get("family_id") or user.get("family_id", ""),
    }
