from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


CHARACTER_TYPES = (
    "human_child", "cat", "dog", "fox", "rabbit", "bear", "bird",
    "dragon", "unicorn", "robot", "mermaid", "fairy", "nature_spirit",
)
CHARACTER_GENDERS = ("girl", "boy", "non_binary", "not_specified")
CHARACTER_TRAITS = (
    "brave", "curious", "kind", "playful", "gentle", "wise", "funny",
    "shy", "creative", "loyal", "adventurous", "calm", "dreamy", "clever",
)


class CharacterInput(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    surprise_name: bool = False
    character_type: Literal[*CHARACTER_TYPES] | None = None
    surprise_type: bool = False
    gender: Literal[*CHARACTER_GENDERS] | None = None
    surprise_gender: bool = False
    traits: list[Literal[*CHARACTER_TRAITS]] = Field(default_factory=list, max_length=5)
    custom_description: str = Field(default="", max_length=300)


class GenerationRequest(BaseModel):
    inputs: CharacterInput
    quote_version: str
    idempotency_key: str = Field(min_length=16, max_length=100)


class GenerationStatus(str, Enum):
    accepted = "accepted"
    completed = "completed"
    failed = "failed"


class GenerationErrorCode(str, Enum):
    stale_quote = "stale_quote"
    no_slots = "no_slots"
    insufficient_credits = "insufficient_credits"
    credits_frozen = "credits_frozen"
    not_found = "not_found"
    forbidden = "forbidden"
    portrait_failed = "portrait_failed"


class CharacterQuote(BaseModel):
    slot_number: int
    credit_cost: int
    credits_before: int
    credits_after: int
    quote_version: str


class CharacterRecord(BaseModel):
    id: str
    uid: str
    slot_number: int
    version: int
    profile: dict
    portrait_url: str


class GenerationJob(BaseModel):
    id: str
    uid: str
    mode: Literal["create", "edit"]
    status: GenerationStatus
    quote_version: str
    idempotency_key: str
    slot_number: int
    reserved_credit_amount: int
    reserved_slot_number: int | None = None
    target_character_id: str | None = None
    character_id: str | None = None
    error_code: GenerationErrorCode | None = None
    inputs: CharacterInput

    def __getitem__(self, key):
        return getattr(self, key)
