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
