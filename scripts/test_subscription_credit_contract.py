from app.api.v1.subscriptions import SUBSCRIPTION_TIERS
from app.utils.credits import FREE_MONTHLY_CREDITS, PREMIUM_MONTHLY_CREDITS


def tier(tier_id):
    return next(item for item in SUBSCRIPTION_TIERS if item["id"] == tier_id)


def test_tier_metadata_matches_monthly_allocations():
    assert tier("free")["credits_per_period"] == FREE_MONTHLY_CREDITS == 3
    assert tier("free")["lifetime_free_credits"] is None
    assert tier("premium")["credits_per_period"] == PREMIUM_MONTHLY_CREDITS == 30


def test_credit_total_contract_counts_monthly_and_topups():
    from app.utils.credits import available_credit_total

    assert available_credit_total({
        "credits_remaining": 3,
        "topup_credits_remaining": 10,
    }) == 13


def test_authenticated_new_user_receives_credit_schema_backfill(monkeypatch):
    import asyncio
    from app import dependencies

    class UserDocument:
        exists = True

        def __init__(self, user_data):
            self.user_data = user_data

        def get(self):
            return self

        def to_dict(self):
            return self.user_data

        def update(self, fields):
            self.user_data.update(fields)

    class UsersCollection:
        def __init__(self, user_data):
            self.user_data = user_data

        def document(self, uid):
            assert uid == "new-user"
            return UserDocument(self.user_data)

    class FakeDb:
        def __init__(self, user_data):
            self.user_data = user_data

        def collection(self, name):
            assert name == "users"
            return UsersCollection(self.user_data)

    user_data = {
        "uid": "new-user",
        "email": "new@example.com",
        "family_id": "family-1",
    }
    monkeypatch.setattr(dependencies, "_check_local_mode", lambda: True)
    monkeypatch.setattr(dependencies, "local_verify_token", lambda token: user_data)
    monkeypatch.setattr(dependencies, "get_db_client", lambda: FakeDb(user_data))
    monkeypatch.setattr(
        dependencies,
        "_ensure_family_id",
        lambda db, uid, data: data["family_id"],
    )
    monkeypatch.setattr(dependencies, "_ensure_subscription_fields", lambda *args: None)
    monkeypatch.setattr(dependencies, "_ensure_email_field", lambda *args: None)
    monkeypatch.setattr(dependencies, "_ensure_username_lowercase", lambda *args: None)
    monkeypatch.setattr(dependencies, "_ensure_onboarding_complete", lambda *args: None)

    asyncio.run(dependencies.get_current_user(authorization="Bearer token"))

    assert user_data["credits_remaining"] == FREE_MONTHLY_CREDITS
    assert user_data["topup_credits_remaining"] == 0
    assert user_data["credits_period_start"] is None
    assert user_data["credits_period_end"] is None
