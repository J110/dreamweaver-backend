from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.config import get_settings


APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"


class AppleIdentityUnavailable(RuntimeError):
    pass


class AppleIdentityInvalid(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def start_session(db_client, purpose: str) -> dict:
    if not get_settings().apple_client_ids:
        raise AppleIdentityUnavailable("apple_client_ids_missing")
    session_id = str(uuid.uuid4())
    nonce = secrets.token_urlsafe(32)
    now = _now()
    db_client.collection("apple_auth_sessions").document(session_id).set({
        "id": session_id,
        "purpose": purpose,
        "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
        "consumed_at": None,
    })
    return {"session_id": session_id, "nonce": nonce}


def verify_identity_token(db_client, session_id: str, identity_token: str) -> dict:
    settings = get_settings()
    if not settings.apple_client_ids:
        raise AppleIdentityUnavailable("apple_client_ids_missing")
    session_ref = db_client.collection("apple_auth_sessions").document(session_id)
    snapshot = session_ref.get()
    if not snapshot.exists:
        raise AppleIdentityInvalid("invalid_session")
    session = snapshot.to_dict() or {}
    if session.get("consumed_at"):
        raise AppleIdentityInvalid("session_consumed")
    try:
        if datetime.fromisoformat(session["expires_at"]) <= _now():
            raise AppleIdentityInvalid("session_expired")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, AppleIdentityInvalid):
            raise
        raise AppleIdentityInvalid("invalid_session") from exc
    try:
        import jwt
        signing_key = jwt.PyJWKClient(APPLE_JWKS_URL).get_signing_key_from_jwt(identity_token)
        claims = jwt.decode(
            identity_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.apple_client_ids,
            issuer=APPLE_ISSUER,
        )
    except Exception as exc:
        raise AppleIdentityInvalid("invalid_identity_token") from exc
    nonce_claim = str(claims.get("nonce") or "")
    expected_hash = session.get("nonce_hash")
    if hashlib.sha256(nonce_claim.encode()).hexdigest() != expected_hash and nonce_claim != expected_hash:
        raise AppleIdentityInvalid("invalid_nonce")
    if not claims.get("sub"):
        raise AppleIdentityInvalid("missing_subject")
    session_ref.update({"consumed_at": _now().isoformat()})
    return {**claims, "_purpose": session.get("purpose")}
