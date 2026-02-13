"""Audio and voice endpoints using edge-tts (Microsoft Neural Voices)."""

import hashlib
import logging
from pathlib import Path
from typing import Optional

import edge_tts
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.tts.voice_service import VoiceService, VOICES, TONE_PRESETS

logger = logging.getLogger(__name__)
router = APIRouter()

settings = get_settings()

# TTS cache directory
TTS_CACHE_DIR = Path(settings.tts_cache_dir)
TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Task status store (in-memory; use Redis in production)
_task_store: dict[str, dict] = {}

PREVIEW_TEXT = (
    "Once upon a time, in a land of dreams and starlight, "
    "a gentle breeze whispered through the magical forest."
)

# ── Edge-tts voice map (per language) ────────────────────────────────
EDGE_VOICE_MAP = {
    "en": {
        "luna":    "en-US-AnaNeural",      # Soft, child-friendly female voice
        "atlas":   "en-US-GuyNeural",      # Warm male voice
        "aria":    "en-US-JennyNeural",    # Clear, gentle female voice
        "cosmo":   "en-US-BrandonNeural",  # Warm male voice
        "whisper": "en-US-EmmaNeural",     # Soft, whispery female voice
        "melody":  "en-US-SaraNeural",     # Musical, gentle female voice
    },
    "hi": {
        "luna":    "hi-IN-SwaraNeural",    # Soft, warm Hindi female voice
        "atlas":   "hi-IN-MadhurNeural",   # Calm Hindi male voice
        "aria":    "hi-IN-SwaraNeural",    # Same gentle female
        "cosmo":   "hi-IN-MadhurNeural",   # Same calm male
        "whisper": "hi-IN-SwaraNeural",    # Gentle female
        "melody":  "hi-IN-SwaraNeural",    # Musical female
    },
}
DEFAULT_VOICE = {"en": "en-US-AnaNeural", "hi": "hi-IN-SwaraNeural"}

EDGE_STYLE_MAP = {
    "calm":      {"rate": "-25%", "pitch": "-2Hz", "volume": "-5%"},
    "relaxing":  {"rate": "-30%", "pitch": "-3Hz", "volume": "-8%"},
    "dramatic":  {"rate": "-10%", "pitch": "-1Hz", "volume": "+0%"},
    "energetic": {"rate": "-5%",  "pitch": "+1Hz", "volume": "+0%"},
    "neutral":   {"rate": "-15%", "pitch": "-1Hz", "volume": "+0%"},
}


# ── Request / Response Models ─────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    voice_id: str = Field("luna")
    content_type: str = Field("story")
    tone: str = Field("calm")
    speed: Optional[float] = Field(None, ge=0.5, le=2.0)


class AudioResponse(BaseModel):
    success: bool
    data: dict
    message: str


# ── Helper ────────────────────────────────────────────────────────────

async def _edge_tts_synthesize(
    text: str, voice_id: str, tone: str, output_path: Path,
    lang: str = "en",
):
    """Synthesize audio using edge-tts."""
    lang_voices = EDGE_VOICE_MAP.get(lang, EDGE_VOICE_MAP["en"])
    voice_name = lang_voices.get(voice_id, DEFAULT_VOICE.get(lang, "en-US-AnaNeural"))
    style = EDGE_STYLE_MAP.get(tone, EDGE_STYLE_MAP["calm"])

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice_name,
        rate=style["rate"],
        pitch=style["pitch"],
        volume=style["volume"],
    )
    await communicate.save(str(output_path))


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/engine")
async def get_engine_info():
    """Report which TTS engine is active."""
    return {"engine": "edge-tts", "gpu": False}


@router.get("/voices", response_model=AudioResponse)
async def list_available_voices(
    lang: str = Query("en", description="Language: 'en' or 'hi'"),
):
    """Get available TTS voices."""
    voices = VoiceService.get_voices_as_dicts()
    return AudioResponse(
        success=True,
        data={"voices": voices, "total": len(voices)},
        message="Available voices retrieved successfully",
    )


@router.get("/tones", response_model=AudioResponse)
async def list_available_tones():
    """Get available narration tone presets."""
    tones = VoiceService.get_tone_presets_for_api()
    return AudioResponse(
        success=True,
        data={"tones": tones, "total": len(tones)},
        message="Available tones retrieved successfully",
    )


@router.get("/tts/preview/{voice_id}")
async def preview_voice(
    voice_id: str,
    tone: str = Query("calm"),
):
    """Generate a short preview clip for a voice + tone combination."""
    if not VoiceService.validate_voice_id(voice_id):
        raise HTTPException(status_code=400, detail=f"Unknown voice: {voice_id}")

    cache_key = hashlib.md5(f"preview:{voice_id}:{tone}".encode()).hexdigest()
    cache_path = TTS_CACHE_DIR / f"{cache_key}.mp3"

    if cache_path.exists() and cache_path.stat().st_size > 0:
        return FileResponse(
            path=str(cache_path),
            media_type="audio/mpeg",
            headers={"Cache-Control": "public, max-age=604800"},
        )

    await _edge_tts_synthesize(PREVIEW_TEXT, voice_id, tone, cache_path)

    if not cache_path.exists() or cache_path.stat().st_size == 0:
        raise HTTPException(status_code=500, detail="Preview generation failed")

    return FileResponse(
        path=str(cache_path),
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/tts")
async def get_tts_audio(
    text: str = Query(..., max_length=5000),
    lang: str = Query("en"),
    voice: str = Query("female"),
    rate: str = Query("-15%"),
):
    """Synchronous GET endpoint for the web frontend.

    The Next.js player sets ``audio.src`` to this URL directly, so we must
    return the MP3 bytes in the response (no async polling).
    """
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    voice_id = "luna" if voice == "female" else "atlas"

    tone = "calm"
    if rate:
        try:
            pct = int(rate.replace("%", "").replace("+", ""))
            if pct <= -20:
                tone = "relaxing"
            elif pct <= -10:
                tone = "calm"
            elif pct >= 5:
                tone = "energetic"
        except (ValueError, AttributeError):
            pass

    cache_key = hashlib.md5(f"get:{text}:{voice_id}:{tone}:{lang}".encode()).hexdigest()
    cache_path = TTS_CACHE_DIR / f"{cache_key}.mp3"

    if cache_path.exists() and cache_path.stat().st_size > 0:
        return FileResponse(path=str(cache_path), media_type="audio/mpeg")

    await _edge_tts_synthesize(text, voice_id, tone, cache_path, lang=lang)

    if not cache_path.exists() or cache_path.stat().st_size == 0:
        raise HTTPException(status_code=500, detail="TTS generation failed")

    return FileResponse(path=str(cache_path), media_type="audio/mpeg")


@router.post("/tts")
async def generate_tts(request: TTSRequest, background_tasks: BackgroundTasks):
    """Generate speech audio from text (async background task for Flutter)."""
    if not VoiceService.validate_voice_id(request.voice_id):
        raise HTTPException(status_code=400, detail=f"Unknown voice: {request.voice_id}")

    if request.tone not in TONE_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown tone: {request.tone}")

    cache_key = hashlib.md5(
        f"{request.text}:{request.voice_id}:{request.content_type}:"
        f"{request.tone}:{request.speed}".encode()
    ).hexdigest()
    cached_path = TTS_CACHE_DIR / f"{cache_key}.mp3"

    if cached_path.exists() and cached_path.stat().st_size > 0:
        return {
            "task_id": cache_key,
            "status": "completed",
            "audio_url": f"/api/v1/audio/tts/result/{cache_key}",
        }

    task_id = cache_key
    _task_store[task_id] = {"status": "processing"}

    background_tasks.add_task(
        _synthesize_background, task_id, request, cached_path,
    )

    return {"task_id": task_id, "status": "processing", "audio_url": None}


@router.get("/tts/status/{task_id}")
async def get_tts_status(task_id: str):
    """Poll TTS synthesis progress."""
    result_path = TTS_CACHE_DIR / f"{task_id}.mp3"
    if result_path.exists() and result_path.stat().st_size > 0:
        return {
            "task_id": task_id,
            "status": "completed",
            "audio_url": f"/api/v1/audio/tts/result/{task_id}",
        }

    task = _task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if task["status"] == "error":
        return {"task_id": task_id, "status": "error", "detail": task.get("detail", "")}

    return {"task_id": task_id, "status": task["status"], "audio_url": None}


@router.get("/tts/result/{task_id}")
async def get_tts_result(task_id: str):
    """Download the synthesised audio for a completed task."""
    result_path = TTS_CACHE_DIR / f"{task_id}.mp3"
    if not result_path.exists() or result_path.stat().st_size == 0:
        raise HTTPException(status_code=404, detail="Audio not ready or not found")

    return FileResponse(path=str(result_path), media_type="audio/mpeg")


@router.delete("/tts/cache")
async def clear_tts_cache():
    """Clear the TTS audio cache."""
    count = 0
    for f in TTS_CACHE_DIR.glob("*.mp3"):
        try:
            f.unlink()
            count += 1
        except Exception:
            pass
    _task_store.clear()
    return {"success": True, "cleared": count}


# ── Background synthesis ──────────────────────────────────────────────

async def _synthesize_background(
    task_id: str, request: TTSRequest, output_path: Path,
):
    """Run edge-tts synthesis in the background (for POST /tts)."""
    try:
        await _edge_tts_synthesize(
            request.text, request.voice_id, request.tone, output_path,
        )
        _task_store[task_id] = {"status": "completed"}
        logger.info("Background TTS completed: %s", task_id[:8])
    except Exception as e:
        logger.error("Background TTS failed (%s): %s", task_id[:8], e)
        _task_store[task_id] = {"status": "error", "detail": str(e)}
