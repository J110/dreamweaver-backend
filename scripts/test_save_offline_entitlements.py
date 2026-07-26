import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.subscription import DEFAULT_PLANS, SubscriptionTier
from app.utils import gating


def _load_api_module(name):
    package = sys.modules.setdefault("app.api.v1", types.ModuleType("app.api.v1"))
    package.__path__ = [str(Path(__file__).parents[1] / "app" / "api" / "v1")]
    module_name = f"app.api.v1.{name}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path(package.__path__[0]) / f"{name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


interactions = _load_api_module("interactions")
subscriptions = _load_api_module("subscriptions")


class _Settings:
    paywall_enabled = True
    paywall_native_enabled = True
    paywall_test_family_ids = set()


class _Snapshot:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _Document:
    def __init__(self, store, document_id):
        self._store = store
        self._document_id = document_id

    def get(self):
        return _Snapshot(self._store.get(self._document_id))

    def set(self, data):
        self._store[self._document_id] = dict(data)

    def update(self, data):
        self._store[self._document_id].update(data)

    def delete(self):
        self._store.pop(self._document_id, None)


class _Query:
    def __init__(self, store, filters=()):
        self._store = store
        self._filters = filters

    def where(self, field, operator, value):
        assert operator == "=="
        return _Query(self._store, self._filters + ((field, value),))

    def get(self):
        return [
            _Snapshot(data)
            for data in self._store.values()
            if all(data.get(field) == value for field, value in self._filters)
        ]


class _Collection(_Query):
    def document(self, document_id):
        return _Document(self._store, document_id)


class _FakeDb:
    def __init__(self):
        self._collections = {"content": {}, "interactions": {}}

    def collection(self, name):
        return _Collection(self._collections[name])


@pytest.fixture(autouse=True)
def gate_on(monkeypatch):
    monkeypatch.setattr(gating, "get_settings", lambda: _Settings())
    gating.set_native_app_flag(False)
    yield
    gating.set_native_app_flag(False)


@pytest.fixture
def fake_db():
    return _FakeDb()


@pytest.fixture
def free_user():
    return {"uid": "free-user", "subscription_tier": "free"}


@pytest.fixture
def premium_user():
    return {"uid": "premium-user", "subscription_tier": "premium"}


def seed_content(db, content_id):
    db.collection("content").document(content_id).set({
        "id": content_id,
        "save_count": 0,
        "like_count": 0,
    })


def seed_saves(db, user_id, count, include=None):
    saved_ids = [include] if include else []
    saved_ids.extend(f"seed-{index}" for index in range(count - len(saved_ids)))
    for content_id in saved_ids:
        interaction_id = f"{user_id}_{content_id}_save"
        db.collection("interactions").document(interaction_id).set({
            "id": interaction_id,
            "user_id": user_id,
            "content_id": content_id,
            "type": "save",
        })


def interaction_types(db, user_id, content_id):
    return [
        record["type"]
        for record in db._collections["interactions"].values()
        if record["user_id"] == user_id and record["content_id"] == content_id
    ]


def run_save(content_id, user, db):
    return asyncio.run(interactions.save_content(content_id, user, db))


def test_authoritative_save_caps():
    assert gating.FREE_SAVE_CAP == 5
    assert gating.PREMIUM_SAVE_CAP == 30


def test_offline_requires_effective_premium(monkeypatch):
    monkeypatch.setattr(gating, "is_premium", lambda user: user["tier"] == "premium")
    assert gating.offline_allowed({"tier": "premium"}) is True
    assert gating.offline_allowed({"tier": "free"}) is False


def test_free_sixth_save_creates_no_save_or_like(fake_db, free_user):
    seed_content(fake_db, "story-1")
    seed_saves(fake_db, free_user["uid"], count=5)

    response = run_save("story-1", free_user, fake_db)

    assert response.data == {
        "content_id": "story-1",
        "saved": False,
        "liked": False,
        "cap_reached": True,
        "saved_count": 5,
        "save_cap": 5,
        "offline_allowed": False,
    }
    assert interaction_types(fake_db, free_user["uid"], "story-1") == []


def test_premium_save_30_succeeds_and_31_is_rejected(fake_db, premium_user):
    seed_content(fake_db, "story-30")
    seed_content(fake_db, "story-31")
    seed_saves(fake_db, premium_user["uid"], count=29)

    saved = run_save("story-30", premium_user, fake_db).data
    rejected = run_save("story-31", premium_user, fake_db).data

    assert saved["saved"] is True
    assert saved["saved_count"] == 30
    assert saved["save_cap"] == 30
    assert saved["offline_allowed"] is True
    assert rejected["cap_reached"] is True
    assert rejected["save_cap"] == 30
    assert rejected["offline_allowed"] is True
    assert interaction_types(fake_db, premium_user["uid"], "story-31") == []


def test_resave_at_cap_is_idempotent(fake_db, premium_user):
    seed_content(fake_db, "story-1")
    seed_saves(fake_db, premium_user["uid"], count=30, include="story-1")

    result = run_save("story-1", premium_user, fake_db).data

    assert result["saved"] is True
    assert result["saved_count"] == 30
    assert result["save_cap"] == 30
    assert result["offline_allowed"] is True


def test_saved_library_exposes_offline_entitlement(fake_db, premium_user):
    seed_content(fake_db, "story-1")
    seed_saves(fake_db, premium_user["uid"], count=1, include="story-1")

    result = asyncio.run(interactions.get_user_saves(premium_user, fake_db)).data

    assert result["save_cap"] == 30
    assert result["offline_allowed"] is True


def test_subscription_metadata_uses_authoritative_save_caps():
    assert DEFAULT_PLANS[SubscriptionTier.FREE].max_saves == 5
    assert DEFAULT_PLANS[SubscriptionTier.PREMIUM].max_saves == 30
    tiers = {tier["id"]: tier for tier in subscriptions.SUBSCRIPTION_TIERS}
    assert tiers["free"]["max_saves"] == 5
    assert tiers["premium"]["max_saves"] == 30
