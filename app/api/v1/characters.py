from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from app.dependencies import get_current_user, get_db_client
from app.schemas.character_schema import GenerationRequest
from app.services.characters.repository import CharacterRepository, CharacterRepositoryError


router = APIRouter()


class QuoteRequest(BaseModel):
    mode: Literal["create", "edit"]
    target_character_id: str | None = None

    @model_validator(mode="after")
    def validate_target_character_id(self):
        if self.mode == "create" and self.target_character_id is not None:
            raise ValueError("create quotes cannot target a character")
        if self.mode == "edit" and self.target_character_id is None:
            raise ValueError("edit quotes require a target character")
        return self


def _repository(db_client):
    return CharacterRepository(db_client)


def _raise_repository_error(error: CharacterRepositoryError):
    status_code, code = {
        "not_found": (404, "not_found"),
        "forbidden": (404, "not_found"),
        "stale_quote": (409, "stale_quote"),
        "no_slots": (409, "no_slots"),
        "insufficient_credits": (402, "insufficient_credits"),
        "credits_frozen": (422, "credits_frozen"),
    }.get(str(error), (422, "generation_failed"))
    raise HTTPException(status_code=status_code, detail={"code": code})


def _document_data(db_client, collection_name: str, document_id: str):
    snapshot = db_client.collection(collection_name).document(document_id).get()
    if not snapshot.exists:
        return None
    return snapshot.to_dict()


def _characters_for_user(db_client, uid: str) -> list[dict]:
    collection = db_client.collection("characters")
    if not callable(getattr(collection, "where", None)):
        characters = getattr(db_client, "collections", {}).get("characters", {}).values()
        return sorted(
            [dict(character) for character in characters if character.get("uid") == uid],
            key=lambda character: character.get("slot_number", 0),
        )
    snapshots = collection.where("uid", "==", uid).get()
    return sorted(
        [snapshot.to_dict() for snapshot in snapshots],
        key=lambda character: character.get("slot_number", 0),
    )


def _owned_document(db_client, collection_name: str, document_id: str, uid: str) -> dict:
    data = _document_data(db_client, collection_name, document_id)
    if not data or data.get("uid") != uid:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return data


@router.get("")
async def list_characters(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    return {"success": True, "data": _characters_for_user(db_client, current_user["uid"])}


@router.get("/generations/{job_id}")
async def get_generation(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    return {
        "success": True,
        "data": _owned_document(
            db_client, "character_generation_jobs", job_id, current_user["uid"]
        ),
    }


@router.post("/quote")
async def quote_character(
    request: QuoteRequest,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    try:
        quote = _repository(db_client).quote_generation(
            current_user["uid"], request.mode, request.target_character_id
        )
    except CharacterRepositoryError as error:
        _raise_repository_error(error)
    return {"success": True, "data": quote.model_dump()}


@router.post("/generations", status_code=202)
async def create_generation(
    request: GenerationRequest,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    try:
        job = _repository(db_client).accept_generation(current_user["uid"], request)
    except CharacterRepositoryError as error:
        _raise_repository_error(error)
    return {"success": True, "data": job.model_dump(mode="json")}


@router.post("/{character_id}/generations", status_code=202)
async def edit_generation(
    character_id: str,
    request: GenerationRequest,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    try:
        job = _repository(db_client).accept_generation(
            current_user["uid"], request, target_character_id=character_id
        )
    except CharacterRepositoryError as error:
        _raise_repository_error(error)
    return {"success": True, "data": job.model_dump(mode="json")}


@router.get("/{character_id}")
async def get_character(
    character_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    return {
        "success": True,
        "data": _owned_document(db_client, "characters", character_id, current_user["uid"]),
    }


@router.delete("/{character_id}")
async def delete_character(
    character_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    try:
        _repository(db_client).delete_character(current_user["uid"], character_id)
    except CharacterRepositoryError as error:
        _raise_repository_error(error)
    return {"success": True, "data": {"id": character_id}}
