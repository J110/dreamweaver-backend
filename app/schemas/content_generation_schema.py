from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


CONTENT_MOODS = ("calm", "adventurous", "funny", "magical", "curious", "gentle")


class ContentGenerationRequest(BaseModel):
    content_type: Literal["STORY", "POEM", "SONG"]
    mood: Literal[*CONTENT_MOODS] | None = None
    character_id: str | None = Field(default=None, max_length=100)
    voice_id: str | None = Field(default=None, max_length=100)
    custom_prompt: str = Field(default="", max_length=500)
    idempotency_key: str = Field(min_length=16, max_length=100)


class ContentGenerationStatus(str, Enum):
    accepted = "accepted"
    generating = "generating"
    completed = "completed"
    failed = "failed"


class ContentGenerationErrorCode(str, Enum):
    insufficient_credits = "insufficient_credits"
    credits_frozen = "credits_frozen"
    generation_in_progress = "generation_in_progress"
    unsafe_input = "unsafe_input"
    writing_failed = "writing_failed"
    narration_failed = "narration_failed"
    cover_failed = "cover_failed"
    saving_failed = "saving_failed"
    generation_failed = "generation_failed"


class ContentGenerationJob(BaseModel):
    id: str
    uid: str
    status: ContentGenerationStatus
    stage: str = "queued"
    idempotency_key: str
    reserved_credit_amount: int = 1
    content_id: str | None = None
    error_code: ContentGenerationErrorCode | None = None
    created_at: str
    updated_at: str
    inputs: dict
    profile_snapshot: dict
    character_snapshot: dict | None = None
    lease_worker_id: str | None = None
    lease_token: str | None = None
    lease_expires_at: str | None = None

