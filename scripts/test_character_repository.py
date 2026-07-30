import pytest

from app.schemas.character_schema import CharacterInput, GenerationRequest
from app.services.characters.repository import CharacterRepositoryError
from scripts.character_test_helpers import (
    create_request,
    deterministic_portrait_url,
    deterministic_profile,
    edit_request,
    fake_repo,
    paid_create_request,
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
