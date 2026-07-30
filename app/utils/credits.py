from calendar import monthrange
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

FREE_MONTHLY_CREDITS = 3
PREMIUM_MONTHLY_CREDITS = 30


class CreditRefreshError(RuntimeError):
    pass


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def calendar_month_period(now: datetime) -> tuple[datetime, datetime]:
    current = _utc(now)
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days = monthrange(start.year, start.month)[1]
    end = start.replace(day=days) + timedelta(days=1)
    return start, end


def available_credit_total(user_data: dict) -> int:
    if user_data.get("credits_frozen"):
        return 0
    monthly = max(0, int(user_data.get("credits_remaining") or 0))
    topups = max(0, int(user_data.get("topup_credits_remaining") or 0))
    reserved = max(0, int(user_data.get("credits_reserved") or 0))
    return max(0, monthly + topups - reserved)


def reserve_credit_fields(user_data: dict, amount: int) -> dict:
    amount = max(0, int(amount))
    if available_credit_total(user_data) < amount:
        raise ValueError("insufficient_credits")
    return {"credits_reserved": max(0, int(user_data.get("credits_reserved") or 0)) + amount}


def release_credit_fields(user_data: dict, amount: int) -> dict:
    reserved = max(0, int(user_data.get("credits_reserved") or 0))
    return {"credits_reserved": max(0, reserved - max(0, int(amount)))}


def debit_reserved_credit_fields(user_data: dict, amount: int) -> dict:
    amount = max(0, int(amount))
    reserved = max(0, int(user_data.get("credits_reserved") or 0))
    if reserved < amount:
        raise ValueError("reserved_credit_missing")
    monthly = max(0, int(user_data.get("credits_remaining") or 0))
    topups = max(0, int(user_data.get("topup_credits_remaining") or 0))
    from_monthly = min(monthly, amount)
    from_topups = amount - from_monthly
    if topups < from_topups:
        raise ValueError("reserved_credit_missing")
    return {
        "credits_remaining": monthly - from_monthly,
        "topup_credits_remaining": topups - from_topups,
        **release_credit_fields(user_data, amount),
    }


def premium_period_credit_fields(
    period_start: str | None,
    period_end: str | None,
) -> dict:
    fields = {
        "credits_remaining": PREMIUM_MONTHLY_CREDITS,
        "credits_frozen": False,
    }
    if period_start:
        fields["credits_period_start"] = period_start
    if period_end:
        fields["credits_period_end"] = period_end
    return fields


def update_user_credit_state(
    db_client,
    uid: str,
    updater: Callable[[dict], dict],
) -> dict:
    user_ref = db_client.collection("users").document(uid)

    def apply_update(transaction=None) -> dict:
        if transaction is None:
            snapshot = user_ref.get()
        else:
            snapshot = user_ref.get(transaction=transaction)
        if not snapshot.exists:
            raise RuntimeError("User credit record not found")

        current = dict(snapshot.to_dict() or {})
        fields = updater(current)
        if fields:
            if transaction is None:
                user_ref.update(fields)
            else:
                transaction.update(user_ref, fields)
            current.update(fields)
        return current

    transaction_factory = getattr(db_client, "transaction", None)
    if callable(transaction_factory):
        from google.cloud import firestore

        transaction = transaction_factory()

        @firestore.transactional
        def apply_firestore_update(active_transaction):
            return apply_update(active_transaction)

        return apply_firestore_update(transaction)

    lock = getattr(db_client, "_lock", None)
    with lock if lock is not None else nullcontext():
        return apply_update()


def refresh_credit_period(
    db_client,
    uid: str,
    user_data: dict,
    now: datetime | None = None,
) -> dict:
    current = _utc(now or datetime.now(timezone.utc))
    start, end = calendar_month_period(current)

    def refresh_fields(latest: dict) -> dict:
        tier = str(latest.get("subscription_tier") or "free").lower()
        if tier == "premium":
            return {}

        period_end = _parse_iso(latest.get("credits_period_end"))
        legacy_free = (
            "lifetime_free_remaining" in latest
            and not latest.get("credits_period_start")
        )
        if period_end and current < period_end and not legacy_free:
            return {}

        return {
            "credits_remaining": FREE_MONTHLY_CREDITS,
            "credits_period_start": start.isoformat(),
            "credits_period_end": end.isoformat(),
            "lifetime_free_remaining": 0,
            "credits_frozen": False,
        }

    try:
        return update_user_credit_state(db_client, uid, refresh_fields)
    except Exception as exc:
        raise CreditRefreshError("Credit refresh failed") from exc
