from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Optional

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
    return monthly + topups


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


def refresh_credit_period(
    db_client,
    uid: str,
    user_data: dict,
    now: datetime | None = None,
) -> dict:
    refreshed = dict(user_data)
    tier = str(refreshed.get("subscription_tier") or "free").lower()
    if tier == "premium":
        return refreshed

    current = _utc(now or datetime.now(timezone.utc))
    start, end = calendar_month_period(current)
    period_end = _parse_iso(refreshed.get("credits_period_end"))
    legacy_free = "lifetime_free_remaining" in refreshed and not refreshed.get("credits_period_start")
    if period_end and current < period_end and not legacy_free:
        return refreshed

    fields = {
        "credits_remaining": FREE_MONTHLY_CREDITS,
        "credits_period_start": start.isoformat(),
        "credits_period_end": end.isoformat(),
        "lifetime_free_remaining": 0,
        "credits_frozen": False,
    }
    try:
        db_client.collection("users").document(uid).update(fields)
    except Exception as exc:
        raise CreditRefreshError(f"credit refresh failed for uid={uid}") from exc
    refreshed.update(fields)
    return refreshed
