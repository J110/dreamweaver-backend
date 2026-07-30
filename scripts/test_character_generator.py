from io import BytesIO

import pytest
from PIL import Image

from app.schemas.character_schema import CharacterInput
from app.services.characters.generator import (
    CharacterGenerationError,
    CharacterGenerator,
    CharacterImageClient,
)


PROFILE_JSON = """{
    "name": "Lumi",
    "type": "fox",
    "gender": "not_specified",
    "traits": ["kind", "dreamy"],
    "profile_summary": "A gentle moon fox who collects fallen stars.",
    "portrait_prompt": "A moon fox under soft moonlight."
}"""


def portrait_png():
    image = Image.new("RGB", (16, 16), color="indigo")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


PORTRAIT_PNG = portrait_png()


class FakeTextClient:
    def __init__(self, profile_response):
        self.profile_response = profile_response

    def generate_text(self, prompt, **kwargs):
        if "MODERATION" in prompt:
            if '"allowed": false' in self.profile_response:
                return self.profile_response
            return '{"allowed": true, "reason": "safe"}'
        return self.profile_response


class FakeImageClient:
    def __init__(self, image):
        self.image = image
        self.calls = 0
        self.prompt = None

    def generate(self, prompt):
        self.calls += 1
        self.prompt = prompt
        return self.image


def test_generator_resolves_surprise_fields_and_returns_webp(tmp_path):
    generator = CharacterGenerator(
        text_client=FakeTextClient(PROFILE_JSON),
        image_client=FakeImageClient(PORTRAIT_PNG),
    )
    profile = generator.generate_profile(
        CharacterInput(
            surprise_name=True,
            surprise_type=True,
            surprise_gender=True,
            traits=["kind", "dreamy"],
        )
    )
    portrait = generator.generate_portrait(profile)
    assert profile.name == "Lumi"
    assert profile.character_type == "fox"
    assert portrait[:4] == b"RIFF"


def test_unsafe_input_fails_closed_before_image_call():
    image = FakeImageClient(PORTRAIT_PNG)
    generator = CharacterGenerator(
        text_client=FakeTextClient('{"allowed": false, "reason": "unsafe"}'),
        image_client=image,
    )
    with pytest.raises(CharacterGenerationError, match="unsafe_input"):
        generator.generate_profile(CharacterInput(name="unsafe example"))
    assert image.calls == 0


def test_invalid_profile_schema_never_generates_portrait():
    image = FakeImageClient(PORTRAIT_PNG)
    generator = CharacterGenerator(
        text_client=FakeTextClient('{"name": ""}'),
        image_client=image,
    )
    with pytest.raises(CharacterGenerationError, match="invalid_profile"):
        generator.generate_profile(CharacterInput(surprise_name=True))
    assert image.calls == 0


def test_portrait_prompt_includes_the_fixed_child_safe_suffix():
    image = FakeImageClient(PORTRAIT_PNG)
    generator = CharacterGenerator(
        text_client=FakeTextClient(PROFILE_JSON),
        image_client=image,
    )
    profile = generator.generate_profile(CharacterInput(surprise_name=True))

    generator.generate_portrait(profile)

    assert "warm storybook illustration" in image.prompt
    assert "soft Dream Valley lighting" in image.prompt
    assert "no photorealism" in image.prompt
    assert "no watermark" in image.prompt


def test_all_image_providers_failing_returns_safe_error(monkeypatch):
    client = CharacterImageClient()
    monkeypatch.setattr(client, "_generate_fluxapi", lambda prompt: None)
    monkeypatch.setattr(client, "_generate_pollinations", lambda prompt: None)
    monkeypatch.setattr(client, "_generate_replicate", lambda prompt: None)

    with pytest.raises(CharacterGenerationError, match="portrait_failed"):
        client.generate("safe prompt")
