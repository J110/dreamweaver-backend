from concurrent.futures import ThreadPoolExecutor, TimeoutError

import fal_client
import httpx


MOOD_STYLE = {
    "calm": ("soft piano and brushed percussion", 92, "warm, settling, and gently rhythmic"),
    "gentle": ("kalimba and soft shaker", 96, "tender, light, and reassuring"),
    "magical": ("music box and shimmering bells", 102, "dreamy, wondrous, and playful"),
    "curious": ("acoustic guitar and finger snaps", 104, "spacious, wondering, and bright"),
    "adventurous": ("ukulele and soft bongos", 110, "lively, buoyant, and child-safe"),
    "funny": ("xylophone and light claps", 112, "bouncy, silly, and clear"),
}


def generate_minimax_audio(text: str, mood: str | None, content_type: str) -> bytes:
    instruments, tempo, energy = MOOD_STYLE.get(mood or "calm", MOOD_STYLE["calm"])
    kind = "musical poem with spoken-word lead vocal" if content_type == "POEM" else "bedtime song"
    prompt = (
        f"Children's {kind}, {instruments}, {tempo} BPM, {energy}, "
        "clear warm vocal, every word easy to understand"
    )
    lyrics = text.strip()
    if len(lyrics) > 500:
        raise ValueError("MiniMax lyrics must not exceed 500 characters")
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(
        fal_client.subscribe,
        "fal-ai/minimax-music/v2",
        arguments={
            "prompt": prompt,
            "lyrics_prompt": lyrics,
            "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
        },
        start_timeout=60,
        client_timeout=120,
    )
    try:
        result = future.result(timeout=420)
    except TimeoutError as error:
        future.cancel()
        raise RuntimeError("MiniMax generation timed out") from error
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    audio = result.get("audio") or result.get("data", {}).get("audio")
    if not audio or not audio.get("url"):
        raise RuntimeError("MiniMax returned no audio URL")
    response = httpx.get(audio["url"], timeout=120, follow_redirects=True)
    response.raise_for_status()
    if len(response.content) < 1000:
        raise RuntimeError("MiniMax returned invalid audio")
    return response.content
