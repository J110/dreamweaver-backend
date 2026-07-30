import pytest

from app.services.characters.repository import CharacterRepository
from app.services.local_store import LocalStore
from scripts.character_test_helpers import create_request


def test_local_store_reloads_character_jobs_across_instances(tmp_path):
    api_store = LocalStore(data_dir=tmp_path)
    worker_store = LocalStore(data_dir=tmp_path)
    api_repository = CharacterRepository(api_store)
    worker_repository = CharacterRepository(worker_store)
    api_store.collection("users").document("u1").set({
        "uid": "u1",
        "credits_remaining": 3,
        "topup_credits_remaining": 0,
        "credits_reserved": 0,
        "credits_frozen": False,
    })

    job = api_repository.accept_generation("u1", create_request("character-generation-shared"))
    claimed = worker_repository.claim_next_job("worker", lease_seconds=300)

    assert claimed.id == job.id
    assert api_store.collection("character_generation_jobs").document(job.id).get().to_dict()["status"] == "generating"


def test_local_store_two_instances_accept_claim_renew_and_complete(tmp_path):
    api_store = LocalStore(data_dir=tmp_path)
    worker_store = LocalStore(data_dir=tmp_path)
    api_repository = CharacterRepository(api_store)
    worker_repository = CharacterRepository(worker_store)
    api_store.collection("users").document("u1").set({
        "uid": "u1",
        "credits_remaining": 3,
        "topup_credits_remaining": 0,
        "credits_reserved": 0,
        "credits_frozen": False,
    })

    job = api_repository.accept_generation("u1", create_request("character-generation-full-shared"))
    claimed = worker_repository.claim_next_job("worker", lease_seconds=300)
    renewed = worker_repository.renew_lease(claimed.id, claimed.lease_token, 300)
    worker_repository.complete_generation(
        claimed.id,
        {"name": "Lumi"},
        "https://images.example.test/lumi.webp",
        renewed.lease_token,
    )

    assert api_store.collection("character_generation_jobs").document(job.id).get().to_dict()["status"] == "completed"
    assert api_store.collection("characters").document(job.character_id).get().exists


def test_local_store_recovers_a_journal_after_interrupted_commit(tmp_path, monkeypatch):
    store = LocalStore(data_dir=tmp_path)
    store.collection("users").document("u1").set({"uid": "u1", "credits_remaining": 3})
    original = store._write_transaction_snapshots

    def interrupted(payload):
        original({"users": payload["users"]})
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(store, "_write_transaction_snapshots", interrupted)
    with pytest.raises(RuntimeError, match="simulated crash"):
        store.run_transaction(lambda _: store.collection("users").document("u1").update({"credits_remaining": 2}))

    recovered = LocalStore(data_dir=tmp_path)
    assert recovered.collection("users").document("u1").get().to_dict()["credits_remaining"] == 2


def test_local_store_same_instance_replays_pending_journal_before_transaction(tmp_path):
    store = LocalStore(data_dir=tmp_path)
    store.collection("users").document("u1").set({"uid": "u1", "credits_remaining": 3})
    store._journal_path.write_text('{"collections":{"users":[{"uid":"u1","credits_remaining":2}]}}')
    observed = []

    def continue_transaction(_):
        observed.append(store.collection("users").document("u1").get().to_dict()["credits_remaining"])
        store.collection("users").document("u1").update({"credits_remaining": 1})

    store.run_transaction(continue_transaction)

    assert observed == [2]
    assert store.collection("users").document("u1").get().to_dict()["credits_remaining"] == 1
    assert not store._journal_path.exists()


def test_local_store_replays_pending_journal_before_cached_document_read(tmp_path):
    store = LocalStore(data_dir=tmp_path)
    store.collection("users").document("u1").set({"uid": "u1", "credits_remaining": 3})
    document = store.collection("users").document("u1")
    store._journal_path.write_text('{"collections":{"users":[{"uid":"u1","credits_remaining":2}]}}')

    assert document.get().to_dict()["credits_remaining"] == 2
    assert not store._journal_path.exists()
