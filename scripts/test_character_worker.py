from pathlib import Path

import pytest

from app.schemas.character_schema import CharacterInput
from app.services.characters.generator import GeneratedProfile
from app.services.characters.generator import CharacterGenerationError
from app.services.characters.worker import CharacterWorker
from scripts.character_test_helpers import fake_repo, paid_create_request
from scripts.run_character_worker import run_loop


GENERATED_PROFILE = GeneratedProfile(
    name="Lumi",
    character_type="fox",
    gender="not_specified",
    traits=["kind"],
    profile_summary="A gentle moon fox.",
    portrait_prompt="A moon fox under soft moonlight.",
)
PORTRAIT_WEBP = b"RIFFportrait-webp"


class FakeGenerator:
    def generate_profile(self, inputs: CharacterInput) -> GeneratedProfile:
        return GENERATED_PROFILE

    def generate_portrait(self, profile: GeneratedProfile) -> bytes:
        return PORTRAIT_WEBP


class FailingGenerator:
    def generate_profile(self, inputs: CharacterInput) -> GeneratedProfile:
        raise RuntimeError("generation unavailable")


def paid_job(fake_repo, key: str):
    for slot in range(1, 4):
        fake_repo.seed_character("u1", slot_number=slot)
    return fake_repo.accept_generation(
        "u1", paid_create_request(key, quote_version=fake_repo.quote_version("u1"))
    )


def test_worker_completes_job_saves_media_and_debits_once(tmp_path, fake_repo):
    job = paid_job(fake_repo, "character-worker-job-1")
    worker = CharacterWorker(fake_repo, FakeGenerator(), tmp_path, "test-worker")

    assert worker.run_once() is True
    completed = fake_repo.job(job["id"])
    character = fake_repo.character(completed["character_id"])
    assert completed["status"] == "completed"
    assert (tmp_path / character["portrait_filename"]).exists()
    assert fake_repo.user("u1")["credits_remaining"] == 1
    assert worker.run_once() is False
    assert fake_repo.user("u1")["credits_remaining"] == 1


def test_worker_failure_removes_partial_media_and_releases_reservation(tmp_path, fake_repo):
    job = paid_job(fake_repo, "character-worker-job-2")
    worker = CharacterWorker(fake_repo, FailingGenerator(), tmp_path, "test-worker")

    assert worker.run_once() is True
    assert fake_repo.job(job["id"])["status"] == "failed"
    assert list(tmp_path.iterdir()) == []
    assert fake_repo.user("u1")["credits_reserved"] == 0


def test_expired_lease_is_reclaimed(tmp_path, fake_repo):
    fake_repo.seed_expired_generating_job("job-3")

    assert CharacterWorker(fake_repo, FakeGenerator(), tmp_path, "new").run_once() is True
    assert fake_repo.job("job-3")["status"] == "completed"


def test_worker_removes_media_for_claimed_cleanup(tmp_path, fake_repo):
    portrait = tmp_path / "c1-v1.webp"
    portrait.write_bytes(b"portrait")
    fake_repo.seed_media_cleanup("cleanup-1", portrait.name)
    worker = CharacterWorker(fake_repo, FakeGenerator(), tmp_path, "worker")

    assert worker.run_cleanup_once() is True
    assert not portrait.exists()
    assert fake_repo.media_cleanup("cleanup-1")["status"] == "completed"


def test_runner_isolates_transient_cleanup_and_generation_failures():
    class StoppingEvent:
        def __init__(self):
            self.set = False
            self.waits = []

        def is_set(self):
            return self.set

        def wait(self, seconds):
            self.waits.append(seconds)
            self.set = True

    class FailingWorker:
        def run_cleanup_once(self):
            raise RuntimeError("temporary cleanup failure")

        def run_once(self):
            raise RuntimeError("temporary generation failure")

    stopping = StoppingEvent()

    assert run_loop(FailingWorker(), stopping) == 0
    assert stopping.waits == [2]


def test_atomic_media_write_never_replaces_an_existing_portrait(tmp_path, fake_repo):
    worker = CharacterWorker(fake_repo, FakeGenerator(), tmp_path, "worker")
    portrait = tmp_path / "character-v1-active.webp"
    portrait.write_bytes(b"active")

    with pytest.raises(CharacterGenerationError, match="portrait_failed"):
        worker._write_portrait_atomically(portrait.name, PORTRAIT_WEBP)

    assert portrait.read_bytes() == b"active"
