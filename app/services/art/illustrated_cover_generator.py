import base64
import io
import logging
import os
from urllib.parse import quote

import httpx
from PIL import Image


logger = logging.getLogger(__name__)


class IllustratedCoverGenerator:
    def _prompt(self, title, description, story_text, theme, content_type):
        excerpt = " ".join(story_text.split())[:900]
        return (
            f"Square cover illustration for an original children's {content_type}. "
            f"Story title for context only: {title}. Story summary: {description}. "
            f"Theme: {theme}. Story excerpt: {excerpt}. "
            "Dreamy premium children's picture-book art, one clear story-specific focal scene, "
            "warm expressive lighting, rich amber and deep violet palette, gentle magical atmosphere, "
            "child-safe, polished editorial composition, no typography, no letters, no words, no logo, "
            "no watermark, no border."
        )

    def _pollinations(self, prompt):
        api_key = os.getenv("POLLINATIONS_API_KEY", "")
        if not api_key:
            return None
        encoded = quote(prompt[:600].rsplit(" ", 1)[0], safe="")
        response = httpx.get(
            f"https://gen.pollinations.ai/image/{encoded}",
            params={"width": 600, "height": 600, "model": "flux", "nologo": "true"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.content

    def _together(self, prompt):
        api_key = os.getenv("TOGETHER_API_KEY", "")
        if not api_key:
            return None
        response = httpx.post(
            "https://api.together.xyz/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "black-forest-labs/FLUX.1-schnell",
                "prompt": prompt[:1500],
                "width": 512,
                "height": 512,
                "steps": 4,
                "n": 1,
                "response_format": "b64_json",
            },
            timeout=120,
        )
        response.raise_for_status()
        return base64.b64decode(response.json()["data"][0]["b64_json"])

    def _as_png(self, image_bytes):
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image = image.resize((600, 600), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    def generate(self, title, description, story_text, theme, content_type):
        prompt = self._prompt(title, description, story_text, theme, content_type)
        for provider in (self._pollinations, self._together):
            try:
                image_bytes = provider(prompt)
                if image_bytes and len(image_bytes) > 1000:
                    return self._as_png(image_bytes)
            except Exception:
                logger.exception("Illustrated cover provider failed: %s", provider.__name__)
        raise RuntimeError("all illustrated cover providers failed")
