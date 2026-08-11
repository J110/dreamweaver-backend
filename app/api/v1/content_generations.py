from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_current_user, get_db_client
from app.schemas.content_generation_schema import ContentGenerationRequest
from app.services.content_generation.repository import (
    ContentGenerationRepository,
    ContentGenerationRepositoryError,
)
from app.utils.credits import refresh_credit_period


router = APIRouter()


def _raise_repository_error(error):
    status_code, code = {
        "not_found": (404, "not_found"),
        "insufficient_credits": (402, "insufficient_credits"),
        "credits_frozen": (422, "credits_frozen"),
        "generation_in_progress": (409, "generation_in_progress"),
    }.get(str(error), (422, "generation_failed"))
    raise HTTPException(status_code=status_code, detail={"code": code})


@router.post("", status_code=202)
async def create_generation(
    request: ContentGenerationRequest,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    uid = current_user["uid"]
    try:
        refresh_credit_period(db_client, uid, current_user)
        job = ContentGenerationRepository(db_client).accept_generation(uid, request)
    except ContentGenerationRepositoryError as error:
        _raise_repository_error(error)
    return {"success": True, "data": job.model_dump(mode="json")}


@router.get("/current")
async def current_generation(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    job = ContentGenerationRepository(db_client).current_generation(current_user["uid"])
    return {"success": True, "data": job.model_dump(mode="json") if job else None}


@router.get("/{job_id}")
async def get_generation(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    try:
        job = ContentGenerationRepository(db_client).generation_job(job_id)
    except ContentGenerationRepositoryError:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    if job.uid != current_user["uid"]:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return {"success": True, "data": job.model_dump(mode="json")}

