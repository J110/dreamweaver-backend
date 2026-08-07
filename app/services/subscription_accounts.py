from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from app.utils.entitlements import compute_tier


class SubscriptionAccountConflict(ValueError):
    pass


def normalize_email(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    return normalized or None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(db_client, field: str, value: str) -> list[dict]:
    return [snapshot.to_dict() or {} for snapshot in db_client.collection("subscription_accounts").where(field, "==", value).get()]


def find_by_apple_subject(db_client, apple_subject: str) -> dict | None:
    rows = _rows(db_client, "apple_subject", apple_subject)
    if len(rows) > 1:
        raise SubscriptionAccountConflict("duplicate_apple_subject")
    return rows[0] if rows else None


def find_by_email(db_client, email: str) -> dict | None:
    normalized = normalize_email(email)
    if not normalized:
        return None
    rows = _rows(db_client, "recovery_email", normalized)
    if len(rows) > 1:
        raise SubscriptionAccountConflict("duplicate_recovery_email")
    return rows[0] if rows else None


def _new_account_id(email: str | None, apple_subject: str) -> str:
    stable = email or apple_subject
    return hashlib.sha256(stable.encode()).hexdigest()


def link_verified_apple_identity(
    db_client,
    uid: str,
    apple_subject: str,
    email: str | None,
) -> dict:
    normalized = normalize_email(email)
    by_subject = find_by_apple_subject(db_client, apple_subject)
    by_email = find_by_email(db_client, normalized) if normalized else None
    if by_subject and by_email and by_subject.get("id") != by_email.get("id"):
        raise SubscriptionAccountConflict("apple_identity_email_conflict")
    account = by_subject or by_email
    now = _now()
    if account is None:
        account_id = _new_account_id(normalized, apple_subject)
        account = {
            "id": account_id,
            "recovery_email": normalized,
            "email_verified_at": now if normalized else None,
            "email_source": "apple" if normalized else None,
            "apple_subject": apple_subject,
            "primary_uid": uid,
            "user_uids": [uid],
            "status": "unknown",
            "tier": "free",
            "created_at": now,
            "updated_at": now,
        }
    else:
        account_id = account["id"]
        user_uids = list(dict.fromkeys([*(account.get("user_uids") or []), uid]))
        account = {
            **account,
            "apple_subject": apple_subject,
            "user_uids": user_uids,
            "updated_at": now,
        }
        if normalized:
            existing = normalize_email(account.get("recovery_email"))
            if existing and existing != normalized:
                raise SubscriptionAccountConflict("recovery_email_conflict")
            account.update({
                "recovery_email": normalized,
                "email_verified_at": account.get("email_verified_at") or now,
                "email_source": account.get("email_source") or "apple",
            })
    db_client.collection("subscription_accounts").document(account_id).set(account)
    user_update = {"subscription_account_id": account_id}
    if normalized:
        user_update.update({
            "recovery_email": normalized,
            "email": normalized,
            "email_verified": True,
        })
    db_client.collection("users").document(uid).update(user_update)
    return account


def primary_user_for_account(db_client, account: dict) -> dict | None:
    candidates = [account.get("primary_uid"), *(account.get("user_uids") or [])]
    fallback = None
    for uid in dict.fromkeys(value for value in candidates if value):
        snapshot = db_client.collection("users").document(uid).get()
        if snapshot.exists:
            user = snapshot.to_dict() or {}
            user.setdefault("uid", uid)
            fallback = fallback or user
            if compute_tier(user) == "premium":
                return user
    return fallback


def sync_subscription_account_from_user(db_client, uid: str) -> dict | None:
    user_snapshot = db_client.collection("users").document(uid).get()
    if not user_snapshot.exists:
        return None
    user = user_snapshot.to_dict() or {}
    account_id = user.get("subscription_account_id")
    if not account_id:
        return None
    account_ref = db_client.collection("subscription_accounts").document(account_id)
    account_snapshot = account_ref.get()
    if not account_snapshot.exists:
        return None
    account = account_snapshot.to_dict() or {}
    tier = compute_tier(user)
    updated = {
        "tier": tier,
        "status": "active" if tier == "premium" else "inactive",
        "user_uids": list(dict.fromkeys([*(account.get("user_uids") or []), uid])),
        "updated_at": _now(),
    }
    account_ref.update(updated)
    return {**account, **updated}
