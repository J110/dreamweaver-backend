from types import SimpleNamespace

import pytest

from app.schemas.content_generation_schema import ContentGenerationRequest
from app.services.content_generation.repository import (
    ContentGenerationRepository,
    ContentGenerationRepositoryError,
)
from app.services.content_generation.worker import ContentGenerationWorker
from app.services.local_store import LocalStore


def request(key="content-generation-request"):
    return ContentGenerationRequest(
        content_type="STORY",
        mood="calm",
        character_id=None,
        voice_id="female_1",
        custom_prompt="A moonlit train",
        idempotency_key=key,
    )


@pytest.fixture
def store(tmp_path):
    db = LocalStore(data_dir=tmp_path)
    db.collection("users").document("u1").set({
        "uid": "u1",
        "child_age": 7,
        "preferred_lang": "en",
        "subscription_tier": "free",
        "credits_remaining": 3,
        "topup_credits_remaining": 0,
        "credits_reserved": 0,
        "credits_frozen": False,
    })
    return db


def test_accept_is_idempotent_and_blocks_a_second_active_job(store):
    repo = ContentGenerationRepository(store)
    first = repo.accept_generation("u1", request())
    repeated = repo.accept_generation("u1", request())
    assert repeated.id == first.id
    assert store.collection("users").document("u1").get().to_dict()["credits_reserved"] == 1
    with pytest.raises(ContentGenerationRepositoryError, match="generation_in_progress"):
        repo.accept_generation("u1", request("different-content-request"))


def test_failure_releases_reserved_credit(store):
    repo = ContentGenerationRepository(store)
    accepted = repo.accept_generation("u1", request())
    claimed = repo.claim_next_job("worker", 300)
    failed = repo.fail_generation(accepted.id, "writing_failed", claimed.lease_token)
    assert failed.status.value == "failed"
    user = store.collection("users").document("u1").get().to_dict()
    assert user["credits_remaining"] == 3
    assert user["credits_reserved"] == 0


def test_completion_debits_once_and_auto_saves_private_content(store):
    repo = ContentGenerationRepository(store)
    accepted = repo.accept_generation("u1", request())
    claimed = repo.claim_next_job("worker", 300)
    record = repo.complete_generation(accepted.id, {
        "type": "story",
        "title": "Moon Train",
        "description": "A gentle trip",
        "text": "A safe bedtime story " * 20,
        "audio_url": "https://example.test/audio.mp3",
        "cover": "https://example.test/cover.png",
    }, claimed.lease_token)
    repeated = repo.complete_generation(accepted.id, record, claimed.lease_token)
    assert repeated["owner_uid"] == "u1"
    assert repeated["visibility"] == "private"
    assert store.collection("users").document("u1").get().to_dict()["credits_remaining"] == 2
    save_id = f"u1_{accepted.content_id}_save"
    assert store.collection("interactions").document(save_id).get().exists


class FakeGenerator:
    def generate_text(self, _job):
        return SimpleNamespace(
            title="Moon Train",
            description="A gentle trip",
            text="A safe bedtime story " * 20,
            theme="calm",
        )

    def synthesize(self, *_args):
        return b"mp3"

    def generate_cover(self, *_args):
        return b"png"


def test_worker_completes_all_durable_stages(store, tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://api.example.test")
    repo = ContentGenerationRepository(store)
    accepted = repo.accept_generation("u1", request())
    worker = ContentGenerationWorker(repo, FakeGenerator(), tmp_path / "media", "worker")
    assert worker.run_once() is True
    job = repo.generation_job(accepted.id)
    assert job.status.value == "completed"
    content = store.collection("generated_content").document(accepted.content_id).get().to_dict()
    assert content["audio_file"].endswith(".mp3")
    assert (tmp_path / "media" / content["audio_file"]).exists()
