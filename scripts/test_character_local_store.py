import fcntl
import os
import stat
import threading

import pytest

from app.api.v1.characters import _characters_for_user
from app.services.characters.repository import CharacterRepository
from app.services.local_store import LocalStore, _atomic_write_json
from scripts.character_test_helpers import create_request, paid_create_request


def legacy_local_store():
    store = object.__new__(LocalStore)
    store.collections = {"interactions": {}}
    store._lock = threading.Lock()
    store._persist = lambda *args: None
    return store


def test_legacy_local_store_uses_immediate_transactions():
    store = legacy_local_store()
    document = store.collection("interactions").document("save-1")

    store.run_transaction(lambda transaction: transaction.set(document, {"type": "save"}))

    assert document.get().to_dict() == {"id": "save-1", "type": "save"}


@pytest.mark.parametrize("operation", ["collection", "transaction"])
@pytest.mark.parametrize("marker", [
    "_transaction_depth",
    "_data_dir",
    "_lock_path",
    "_journal_path",
    "_persistent_collections",
    "_seed_dir",
    "_seed_content_path",
    "_last_seed_mtime",
])
def test_partial_persistent_local_store_state_fails_closed(marker, operation):
    store = legacy_local_store()
    setattr(store, marker, object())
    callback_calls = []

    with pytest.raises(RuntimeError, match="partially initialized"):
        if operation == "collection":
            store.collection("interactions")
        else:
            store.run_transaction(lambda transaction: callback_calls.append(transaction))

    assert callback_calls == []


def test_complete_persistent_local_store_uses_locked_journal_path(tmp_path, monkeypatch):
    store = LocalStore(data_dir=tmp_path)
    store.collection("users").document("u1").set({"uid": "u1", "credits_remaining": 3})
    store._journal_path.write_text('{"collections":{"users":[{"uid":"u1","credits_remaining":2}]}}')
    lock_operations = []

    monkeypatch.setattr(
        "app.services.local_store.fcntl.flock",
        lambda _, operation: lock_operations.append(operation),
    )

    credits = store.run_transaction(
        lambda _: store.collection("users").document("u1").get().to_dict()["credits_remaining"]
    )

    assert credits == 2
    assert not store._journal_path.exists()
    assert lock_operations == [fcntl.LOCK_EX, fcntl.LOCK_UN]


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


def test_stale_api_credit_update_preserves_worker_completion(tmp_path):
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
    api_store.collection("character_slot_counters").document("u1").set({
        "occupied_slots": [1, 2, 3], "reserved_slots": [], "slot_reservations": {}, "revision": 0,
    })
    stale_user = api_store.collection("users").document("u1")
    job = api_repository.accept_generation("u1", paid_create_request("local-store-credit-race"))
    claimed = worker_repository.claim_next_job("worker", lease_seconds=300)

    worker_repository.complete_generation(
        claimed.id, {"name": "Lumi"}, "https://images.example.test/lumi.webp", claimed.lease_token
    )
    stale_user.update({"topup_credits_remaining": 4})

    user = LocalStore(data_dir=tmp_path).collection("users").document("u1").get().to_dict()
    assert user["credits_remaining"] == 1
    assert user["credits_reserved"] == 0
    assert user["topup_credits_remaining"] == 4
    assert LocalStore(data_dir=tmp_path).collection("character_generation_jobs").document(job.id).get().to_dict()["status"] == "completed"


def test_character_list_refreshes_completed_portrait_from_another_local_store(tmp_path):
    api_store = LocalStore(data_dir=tmp_path)
    worker_store = LocalStore(data_dir=tmp_path)
    api_repository = CharacterRepository(api_store)
    worker_repository = CharacterRepository(worker_store)
    api_store.collection("users").document("u1").set({
        "uid": "u1", "credits_remaining": 3, "topup_credits_remaining": 0,
        "credits_reserved": 0, "credits_frozen": False,
    })
    job = api_repository.accept_generation("u1", create_request("local-store-list-refresh"))
    claimed = worker_repository.claim_next_job("worker", lease_seconds=300)

    worker_repository.complete_generation(
        claimed.id, {"name": "Lumi"}, "https://images.example.test/lumi.webp", claimed.lease_token
    )

    assert [character["id"] for character in _characters_for_user(api_store, "u1")] == [job.character_id]


def test_atomic_json_replace_fsyncs_file_before_parent_directory(tmp_path, monkeypatch):
    fsync_targets = []
    original_fsync = os.fsync

    def track_fsync(file_descriptor):
        mode = os.fstat(file_descriptor).st_mode
        fsync_targets.append("directory" if stat.S_ISDIR(mode) else "file")
        original_fsync(file_descriptor)

    monkeypatch.setattr("app.services.local_store.os.fsync", track_fsync)

    _atomic_write_json(tmp_path / "users.json", [{"uid": "u1"}])

    assert fsync_targets == ["file", "directory"]


def test_transaction_fsyncs_journal_and_snapshot_directories(tmp_path, monkeypatch):
    store = LocalStore(data_dir=tmp_path)
    store.collection("users").document("u1").set({"uid": "u1", "credits_remaining": 3})
    directory_syncs = []
    original_fsync = os.fsync

    def track_fsync(file_descriptor):
        if stat.S_ISDIR(os.fstat(file_descriptor).st_mode):
            directory_syncs.append(file_descriptor)
        original_fsync(file_descriptor)

    monkeypatch.setattr("app.services.local_store.os.fsync", track_fsync)
    store.run_transaction(lambda _: store.collection("users").document("u1").update({"credits_remaining": 2}))

    assert len(directory_syncs) == 2
