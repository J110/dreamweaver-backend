import json
import os
from io import BytesIO
from typing import Literal
from urllib.parse import quote

import httpx
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings
from app.schemas.character_schema import (
    CHARACTER_GENDERS,
    CHARACTER_TRAITS,
    CHARACTER_TYPES,
    CharacterInput,
)
from app.services.ai.groq_service import GroqService


PORTRAIT_SUFFIX = (
    "warm storybook illustration, soft Dream Valley lighting, full character "
    "visibility, age-appropriate clothing and anatomy, no photorealism, no "
    "words, no logo, no watermark."
)


class CharacterGenerationError(RuntimeError):
    pass


class GeneratedProfile(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    character_type: Literal[*CHARACTER_TYPES]
    gender: Literal[*CHARACTER_GENDERS]
    traits: list[Literal[*CHARACTER_TRAITS]] = Field(min_length=1, max_length=5)
    profile_summary: str = Field(min_length=1, max_length=300)
    portrait_prompt: str = Field(min_length=1, max_length=800)


class _ModerationResult(BaseModel):
    allowed: bool
    reason: str


class _ProfileResponse(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    type: Literal[*CHARACTER_TYPES]
    gender: Literal[*CHARACTER_GENDERS]
    traits: list[Literal[*CHARACTER_TRAITS]] = Field(min_length=1, max_length=5)
    profile_summary: str = Field(min_length=1, max_length=300)
    portrait_prompt: str = Field(min_length=1, max_length=800)


def normalize_portrait_webp(image: bytes, width: int = 768, height: int = 960) -> bytes:
    try:
        with Image.open(BytesIO(image)) as source:
            portrait = ImageOps.fit(source.convert("RGB"), (width, height), Image.LANCZOS)
            output = BytesIO()
            portrait.save(output, format="WEBP", method=6)
            return output.getvalue()
    except Exception as error:
        raise CharacterGenerationError("portrait_failed") from error


class CharacterImageClient:
    def generate(self, prompt: str) -> bytes:
        for provider in (
            self._generate_fluxapi,
            self._generate_pollinations,
            self._generate_replicate,
        ):
            image = provider(prompt)
            if image:
                return normalize_portrait_webp(image, width=768, height=960)
        raise CharacterGenerationError("portrait_failed")

    def _generate_fluxapi(self, prompt: str) -> bytes | None:
        api_key = os.getenv("FLUXAPI_KEY", "")
        if not api_key:
            return None
        try:
            response = httpx.post(
                "https://api.fluxapi.ai/api/v1/generate",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"prompt": prompt, "width": 768, "height": 960},
                timeout=60,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError:
            return None

    def _generate_pollinations(self, prompt: str) -> bytes | None:
        try:
            response = httpx.get(
                "https://image.pollinations.ai/prompt/"
                f"{quote(prompt)}?width=768&height=960&nologo=true",
                timeout=60,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError:
            return None

    def _generate_replicate(self, prompt: str) -> bytes | None:
        api_key = os.getenv("REPLICATE_API_TOKEN", "")
        model_version = os.getenv("REPLICATE_MODEL_VERSION", "")
        if not api_key or not model_version:
            return None
        try:
            response = httpx.post(
                "https://api.replicate.com/v1/predictions",
                headers={"Authorization": f"Token {api_key}"},
                json={"version": model_version, "input": {"prompt": prompt}},
                timeout=60,
            )
            response.raise_for_status()
            output = response.json().get("output")
            image_url = output[0] if isinstance(output, list) else output
            if not image_url:
                return None
            image_response = httpx.get(image_url, timeout=60)
            image_response.raise_for_status()
            return image_response.content
        except (httpx.HTTPError, TypeError, ValueError):
            return None


class CharacterGenerator:
    def __init__(self, text_client=None, image_client=None):
        settings = get_settings()
        self.text_client = text_client or GroqService(settings.groq_api_key)
        self.image_client = image_client or CharacterImageClient()

    def generate_profile(self, inputs: CharacterInput) -> GeneratedProfile:
        moderation = self._moderate(inputs)
        if not moderation.allowed:
            raise CharacterGenerationError("unsafe_input")
        try:
            response = _ProfileResponse.model_validate(
                self._parse_json(self.text_client.generate_text(self._profile_prompt(inputs)))
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise CharacterGenerationError("invalid_profile") from error
        return GeneratedProfile(
            name=inputs.name if inputs.name and not inputs.surprise_name else response.name,
            character_type=(
                inputs.character_type
                if inputs.character_type and not inputs.surprise_type
                else response.type
            ),
            gender=(
                inputs.gender if inputs.gender and not inputs.surprise_gender else response.gender
            ),
            traits=inputs.traits or response.traits,
            profile_summary=response.profile_summary,
            portrait_prompt=response.portrait_prompt,
        )

    def generate_portrait(self, profile: GeneratedProfile) -> bytes:
        image = self.image_client.generate(f"{profile.portrait_prompt} {PORTRAIT_SUFFIX}")
        return normalize_portrait_webp(image, width=768, height=960)

    def _moderate(self, inputs: CharacterInput) -> _ModerationResult:
        try:
            result = _ModerationResult.model_validate(
                self._parse_json(self.text_client.generate_text(self._moderation_prompt(inputs)))
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise CharacterGenerationError("unsafe_input") from error
        return result

    @staticmethod
    def _parse_json(response: str) -> dict:
        content = response.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(content)

    @staticmethod
    def _moderation_prompt(inputs: CharacterInput) -> str:
        return (
            "MODERATION: Assess this child character request. Return only JSON "
            '{"allowed": true, "reason": "safe"} or '
            '{"allowed": false, "reason": "unsafe"}. Request: '
            f"{inputs.model_dump(mode='json')}"
        )

    @staticmethod
    def _profile_prompt(inputs: CharacterInput) -> str:
        return (
            "Create a child-safe Dream Valley character profile. Return only JSON with "
            "name, type, gender, traits, profile_summary, and portrait_prompt. "
            "Use only curated type, gender, and trait values. Request: "
            f"{inputs.model_dump(mode='json')}"
        )
