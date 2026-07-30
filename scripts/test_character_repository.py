import threading

import pytest

from app.schemas.character_schema import CharacterInput, GenerationRequest
from app.services.characters.repository import CharacterRepositoryError
from scripts.character_test_helpers import (
    create_request,
    deterministic_portrait_url,
    deterministic_profile,
    edit_request,
    fake_repo,
    local_store_repo,
    paid_create_request,
    seed_user,
)


def test_quote_uses_lowest_free_slot_and_slot_price(fake_repo):
    fake_repo.seed_character("u1", slot_number=2)
    assert fake_repo.quote_generation("u1", mode="create").model_dump() == {
        "slot_number": 1,
        "credit_cost": 0,
        "credits_before": 3,
        "credits_after": 3,
        "quote_version": fake_repo.quote_version("u1"),
    }


def test_slot_four_costs_two_credits(fake_repo):
    for slot in (1, 2, 3):
        fake_repo.seed_character("u1", slot_number=slot)
    assert fake_repo.quote_generation("u1", mode="create").credit_cost == 2


def test_edit_always_costs_two_credits(fake_repo):
    character = fake_repo.seed_character("u1", slot_number=1)
    assert fake_repo.quote_generation(
        "u1", mode="edit", target_character_id=character["id"]
    ).credit_cost == 2


def test_accept_is_idempotent_and_reserves_once(fake_repo):
    request = create_request(idempotency_key="character-generation-same")
    first = fake_repo.accept_generation("u1", request)
    second = fake_repo.accept_generation("u1", request)
    assert first["id"] == second["id"]
    assert fake_repo.user("u1")["credits_reserved"] == first["reserved_credit_amount"]


def test_failed_edit_preserves_character_and_releases_credit(fake_repo):
    original = fake_repo.seed_character("u1", slot_number=1, version=3)
    job = fake_repo.accept_generation(
        "u1",
        edit_request(original, idempotency_key="character-generation-edit"),
        target_character_id=original["id"],
    )
    fake_repo.fail_generation(job["id"], "portrait_failed")
    assert fake_repo.character(original["id"])["version"] == 3
    assert fake_repo.user("u1")["credits_reserved"] == 0


def test_complete_debits_reservation_and_occupies_reserved_slot(
    fake_repo, deterministic_profile, deterministic_portrait_url
):
    for slot in (1, 2, 3):
        fake_repo.seed_character("u1", slot_number=slot)
    job = fake_repo.accept_generation("u1", paid_create_request())

    character = fake_repo.complete_generation(
        job["id"], deterministic_profile, deterministic_portrait_url
    )

    assert character.slot_number == 4
    assert fake_repo.user("u1")["credits_remaining"] == 1
    assert fake_repo.user("u1")["credits_reserved"] == 0


def test_delete_frees_slot_and_creates_media_cleanup_marker(fake_repo):
    character = fake_repo.seed_character("u1", slot_number=2)

    fake_repo.delete_character("u1", character["id"])

    assert fake_repo.character(character["id"]) is None
    assert fake_repo.quote_generation("u1", mode="create").slot_number == 1
    assert fake_repo.cleanup_marker(character["id"])["character_id"] == character["id"]


def test_accept_rejects_stale_quote(fake_repo):
    fake_repo.accept_generation("u1", create_request("character-generation-first"))

    with pytest.raises(CharacterRepositoryError, match="stale_quote"):
        fake_repo.accept_generation("u1", create_request("character-generation-stale"))


def test_schema_curates_character_input_values():
    request = GenerationRequest(
        inputs=CharacterInput(character_type="dragon", traits=["brave"]),
        quote_version="0",
        idempotency_key="character-generation-schema",
    )

    assert request.inputs.character_type == "dragon"


def test_transaction_reads_document_snapshots_not_firestore_get_generator(fake_repo):
    assert fake_repo.quote_generation("u1", mode="create").slot_number == 1


def test_failed_edit_cannot_release_another_jobs_reused_slot(fake_repo):
    original = fake_repo.seed_character("u1", slot_number=1)
    edit_job = fake_repo.accept_generation(
        "u1",
        edit_request(original, idempotency_key="character-generation-owned-edit"),
        target_character_id=original["id"],
    )
    fake_repo.delete_character("u1", original["id"])
    create_job = fake_repo.accept_generation(
        "u1",
        create_request(
            "character-generation-reused-slot",
            quote_version=fake_repo.quote_version("u1"),
        ),
    )

    fake_repo.fail_generation(edit_job["id"], "portrait_failed")

    assert 1 in fake_repo.counter("u1")["reserved_slots"]
    assert fake_repo.counter("u1")["slot_reservations"]["1"] == create_job["id"]


def test_cross_user_edit_and_delete_are_forbidden(fake_repo):
    character = fake_repo.seed_character("u1", slot_number=1)
    seed_user(fake_repo, uid="u2")

    with pytest.raises(CharacterRepositoryError, match="forbidden"):
        fake_repo.accept_generation(
            "u2",
            edit_request(character, idempotency_key="character-generation-other-user"),
            target_character_id=character["id"],
        )
    with pytest.raises(CharacterRepositoryError, match="forbidden"):
        fake_repo.delete_character("u2", character["id"])


def test_accept_rejects_frozen_insufficient_and_full_slots(fake_repo):
    fake_repo.db.collection("users").document("u1").update({"credits_frozen": True})
    with pytest.raises(CharacterRepositoryError, match="credits_frozen"):
        fake_repo.accept_generation("u1", create_request("character-generation-frozen"))

    fake_repo.db.collection("users").document("u1").update({
        "credits_frozen": False,
        "credits_remaining": 1,
    })
    for slot in (1, 2, 3):
        fake_repo.seed_character("u1", slot_number=slot)
    with pytest.raises(CharacterRepositoryError, match="insufficient_credits"):
        fake_repo.accept_generation("u1", paid_create_request("character-generation-insufficient"))

    fake_repo.db.collection("users").document("u1").update({"credits_remaining": 3})
    for slot in range(4, 31):
        fake_repo.seed_character("u1", slot_number=slot)
    with pytest.raises(CharacterRepositoryError, match="no_slots"):
        fake_repo.quote_generation("u1", mode="create")


def test_completion_and_failure_replays_do_not_change_credit_twice(
    fake_repo, deterministic_profile, deterministic_portrait_url
):
    for slot in (1, 2, 3):
        fake_repo.seed_character("u1", slot_number=slot)
    completed_job = fake_repo.accept_generation("u1", paid_create_request())
    completed = fake_repo.complete_generation(
        completed_job["id"], deterministic_profile, deterministic_portrait_url
    )
    replayed = fake_repo.complete_generation(
        completed_job["id"], deterministic_profile, deterministic_portrait_url
    )
    assert replayed.id == completed.id
    assert fake_repo.user("u1")["credits_remaining"] == 1

    fake_repo.db.collection("users").document("u1").update({
        "topup_credits_remaining": 2,
    })

    failed_job = fake_repo.accept_generation(
        "u1",
        paid_create_request(
            "character-generation-failure-replay",
            quote_version=fake_repo.quote_version("u1"),
        ),
    )
    fake_repo.fail_generation(failed_job["id"], "portrait_failed")
    fake_repo.fail_generation(failed_job["id"], "portrait_failed")
    assert fake_repo.user("u1")["credits_reserved"] == 0


def test_parallel_acceptance_reserves_only_one_slot_for_a_stale_quote(fake_repo):
    barrier = threading.Barrier(3)
    accepted = []
    errors = []

    def accept(idempotency_key):
        barrier.wait()
        try:
            accepted.append(fake_repo.accept_generation("u1", create_request(idempotency_key)))
        except CharacterRepositoryError as exc:
            errors.append(str(exc))

    first = threading.Thread(target=accept, args=("character-generation-thread-one",))
    second = threading.Thread(target=accept, args=("character-generation-thread-two",))
    first.start()
    second.start()
    barrier.wait()
    first.join(timeout=2)
    second.join(timeout=2)

    assert len(accepted) == 1
    assert errors == ["stale_quote"]
    assert fake_repo.counter("u1")["reserved_slots"] == [1]


def test_local_store_transaction_rolls_back_partial_acceptance(local_store_repo):
    local_store_repo.db.fail_next_write("character_slot_counters", "u1")

    with pytest.raises(RuntimeError, match="transaction_write_failed"):
        local_store_repo.accept_generation("u1", create_request("character-generation-rollback"))

    assert local_store_repo.db.collection("users").document("u1").get().to_dict()["credits_reserved"] == 0
    assert local_store_repo.db.collection("character_slot_counters").document("u1").get().exists is False
    assert local_store_repo.db.collection("character_generation_jobs").document(
        local_store_repo._job_ref("u1", "character-generation-rollback").id
    ).get().exists is False


def test_local_store_parallel_acceptance_cannot_claim_the_same_slot(local_store_repo):
    local_store_repo.db.synchronize_reads_at("character_slot_counters", "u1")
    start = threading.Barrier(3)
    accepted = []
    errors = []

    def accept(idempotency_key):
        start.wait()
        try:
            accepted.append(local_store_repo.accept_generation(
                "u1", create_request(idempotency_key)
            ))
        except CharacterRepositoryError as exc:
            errors.append(str(exc))

    first = threading.Thread(target=accept, args=("character-generation-local-one",))
    second = threading.Thread(target=accept, args=("character-generation-local-two",))
    first.start()
    second.start()
    start.wait()
    first.join(timeout=2)
    second.join(timeout=2)

    assert len(accepted) == 1
    assert errors == ["stale_quote"]
