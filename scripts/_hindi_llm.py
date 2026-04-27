"""Mistral primary + Groq fallback LLM wrapper for Hindi daily pipeline.

Both providers expose OpenAI-compatible /chat/completions endpoints so the
wrapper switches transparently. Mistral is preferred (we already use it for
English content); Groq fires when Mistral 429s, times out, or errors.

Environment:
    MISTRAL_API_KEY  (required for primary)
    GROQ_API_KEY     (required for fallback)

Usage:
    from _hindi_llm import generate_json

    payload = generate_json(
        system="You are a Hindi children's storyteller...",
        user="Generate a calm short story...",
        max_retries=3,
    )
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass

MISTRAL_KEY = os.getenv("MISTRAL_API_KEY", "")
GROQ_KEY = os.getenv("GROQ_API_KEY", "")

MISTRAL_ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL = "mistral-large-latest"

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
# Llama 3.3 70B is the current Groq workhorse at the time of writing
# (groq.com/docs/models). Generous context window, JSON mode, fast.
GROQ_MODEL = "llama-3.3-70b-versatile"


class LLMError(RuntimeError):
    pass


def _call_provider(
    *, endpoint: str, api_key: str, model: str, messages: list[dict],
    temperature: float, max_tokens: int, want_json: bool, timeout: float,
) -> str:
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if want_json:
        body["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = httpx.post(endpoint, headers=headers, json=body, timeout=timeout)
    if resp.status_code != 200:
        raise LLMError(f"{endpoint} returned {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def generate_text(
    *,
    system: str,
    user: str,
    temperature: float = 0.85,
    max_tokens: int = 1500,
    want_json: bool = True,
    max_retries: int = 3,
    log_prefix: str = "",
) -> str:
    """Try Mistral; fall back to Groq on rate-limit/timeout/error.

    Both providers' rate-limit responses (429) trigger immediate fallback to
    the other rather than waiting it out — cron has limited time.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_err: Exception | None = None

    for attempt in range(max_retries):
        # ── Try Mistral first ──
        if MISTRAL_KEY:
            try:
                if log_prefix:
                    print(f"{log_prefix}  attempt {attempt+1}: Mistral")
                return _call_provider(
                    endpoint=MISTRAL_ENDPOINT,
                    api_key=MISTRAL_KEY,
                    model=MISTRAL_MODEL,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    want_json=want_json,
                    timeout=120,
                )
            except Exception as e:
                last_err = e
                msg = str(e)
                if "429" in msg or "rate" in msg.lower():
                    print(f"{log_prefix}  Mistral rate-limited; trying Groq")
                else:
                    print(f"{log_prefix}  Mistral error: {msg[:120]} — trying Groq")

        # ── Fallback: Groq ──
        if GROQ_KEY:
            try:
                if log_prefix:
                    print(f"{log_prefix}  attempt {attempt+1}: Groq")
                return _call_provider(
                    endpoint=GROQ_ENDPOINT,
                    api_key=GROQ_KEY,
                    model=GROQ_MODEL,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    want_json=want_json,
                    timeout=60,
                )
            except Exception as e:
                last_err = e
                print(f"{log_prefix}  Groq error: {str(e)[:120]}")

        # Backoff before retrying
        if attempt < max_retries - 1:
            wait = 5 * (attempt + 1)
            print(f"{log_prefix}  both providers failed; sleeping {wait}s before retry")
            time.sleep(wait)

    raise LLMError(f"all LLM attempts failed; last={last_err}")


def generate_json(*args, **kwargs) -> dict:
    """generate_text + JSON parse + validate dict response."""
    raw = generate_text(*args, want_json=True, **kwargs)
    # Strip code fences if the model wrapped (some Groq outputs do this)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").lstrip("json").strip()
        if raw.endswith("```"):
            raw = raw[: -3].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"non-JSON response: {e}; got: {raw[:200]}")
