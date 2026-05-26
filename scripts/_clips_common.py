"""Shared plumbing for generate_clips.py (EN) and generate_clips_hi.py (HI).

Language-agnostic helpers: FFmpeg orchestration, SVG->PNG, Ken Burns motion,
audio trim, video compositing, daily-plan selection, metadata writes.

Per-language configuration is injected via ``LangConfig``: mood labels,
type labels, caption templates, voice captions, output directory, content
filter predicate, and a hook into voice resolution that knows the language.

Per dreamweaver-backend/CLAUDE.md: parallel scripts pattern, not ``--lang``
flags. This module is the shared substrate, not a unifying layer; it knows
nothing about Hindi vs English, only about what the caller hands it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ── Voice service (lang-aware resolve) ────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
try:
    from app.services.tts.voice_service import (  # type: ignore
        get_clip_voice,
        resolve_voice_id,
    )
    HAS_VOICE_SELECTION = True
except ImportError:
    HAS_VOICE_SELECTION = False


# ── Constants ────────────────────────────────────────────────────────────
CLIP_DURATION = 60
FPS = 30
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
COVER_SIZE = 1080
BG_COLOR = "0D0B2E"
TITLE_COLOR = "F5E6D3"
BRAND_COLOR = "888888"

FFMPEG_TIMEOUT = 300
FFMPEG_COMPOSITE_TIMEOUT = 420
MAX_CLIPS_PER_RUN = 6
FFMPEG_THREADS = 1
FFMPEG_NICE = 10

CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
WEB_DIR = BASE_DIR.parent / "dreamweaver-web"
COVERS_DIR = WEB_DIR / "public" / "covers"
AUDIO_DIR = WEB_DIR / "public" / "audio" / "pre-gen"

logger = logging.getLogger("clips")


# ── Language configuration ───────────────────────────────────────────────

@dataclass
class LangConfig:
    """Per-language knobs the shared pipeline needs."""

    lang: str
    output_dir: Path
    mood_display: Dict[str, Dict[str, str]]
    type_labels: Dict[str, str]
    voice_labels: Dict[str, str]
    voice_tags: Dict[str, str]
    caption_builder: Callable[..., Dict[str, str]]
    brand_text: str = "dreamvalley.app"
    ages_prefix: str = "Ages"
    fallback_voice_assignment: Dict[str, str] = field(default_factory=dict)

    def voice_suffix(self) -> str:
        return "_hi" if self.lang == "hi" else ""

    def filter_content(self, story: Dict[str, Any]) -> bool:
        """Default: include the story iff its lang matches.

        For English, treat items missing ``lang`` as English so legacy
        content remains eligible. For Hindi, ``lang`` must be explicit.
        """
        story_lang = story.get("lang") or story.get("language") or "en"
        return story_lang == self.lang


# ── Voice assignment ─────────────────────────────────────────────────────

def get_daily_voice_assignment(config: LangConfig) -> Dict[str, str]:
    """Deterministic daily coin flip — same date+lang ⇒ same assignment.

    The hash is salted with the language so EN and HI alternate
    independently and one doesn't drag the other along on flip days.
    Returned voice IDs include any language-specific suffix.
    """
    today = date.today().isoformat()
    seed = f"{today}|{config.lang}"
    flip = int(hashlib.md5(seed.encode()).hexdigest(), 16) % 2
    suffix = config.voice_suffix()
    if flip == 0:
        return {
            "story": f"female_1{suffix}",
            "poem": f"asmr{suffix}",
            "lullaby": f"default{suffix}" if suffix else "default",
        }
    return {
        "story": f"asmr{suffix}",
        "poem": f"female_1{suffix}",
        "lullaby": f"default{suffix}" if suffix else "default",
    }


def get_voice_for_story(
    story: Dict[str, Any],
    voice_assignment: Dict[str, str],
    config: LangConfig,
) -> Tuple[Optional[str], Optional[str]]:
    """Choose a voice variant for ``story`` honouring the language config.

    Mood-based selection when available; legacy assignment otherwise.
    Hindi resolves via ``VOICE_ID_MAP_HI`` (``_hi``-suffixed file IDs)
    so the matcher hits Hindi audio_variants.
    """
    content_type = story.get("type", "story").lower()
    variants = story.get("audio_variants", [])
    if not variants:
        return None, None

    if content_type == "song":
        v = variants[0]
        return v["voice"], v["url"]

    if HAS_VOICE_SELECTION:
        clip_voice_descriptive = get_clip_voice(story)
        clip_voice_id = resolve_voice_id(clip_voice_descriptive, lang=config.lang)
        for v in variants:
            if v["voice"] == clip_voice_id:
                return v["voice"], v["url"]
        v = variants[0]
        return v["voice"], v["url"]

    if content_type == "poem":
        assigned = voice_assignment.get("poem", f"female_1{config.voice_suffix()}")
    else:
        assigned = voice_assignment.get("story", f"female_1{config.voice_suffix()}")

    for v in variants:
        if v["voice"] == assigned:
            return v["voice"], v["url"]

    v = variants[0]
    return v["voice"], v["url"]


# ── SVG to PNG ───────────────────────────────────────────────────────────

def svg_to_png(svg_path: Path, png_path: Path, size: int = COVER_SIZE) -> bool:
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=size,
            output_height=size,
        )
        return True
    except Exception as e:
        logger.warning("  cairosvg failed: %s — trying rsvg-convert fallback", e)
        try:
            subprocess.run(
                ["rsvg-convert", "-w", str(size), "-h", str(size),
                 "-o", str(png_path), str(svg_path)],
                check=True, capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("  Both cairosvg and rsvg-convert failed for %s", svg_path)
            return False


# ── FFmpeg primitives ────────────────────────────────────────────────────

def _run_ffmpeg(cmd: List[str], label: str, timeout: int = FFMPEG_TIMEOUT) -> bool:
    if "-threads" not in cmd:
        cmd = cmd[:1] + ["-threads", str(FFMPEG_THREADS)] + cmd[1:]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout,
            preexec_fn=lambda: os.nice(FFMPEG_NICE),
        )
        if result.returncode != 0:
            logger.error("  %s failed: %s", label, result.stderr[-500:])
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("  %s TIMEOUT after %ds — killing", label, timeout)
        return False


def create_ken_burns_video(png_path: Path, video_path: Path,
                           duration: int = CLIP_DURATION) -> bool:
    total_frames = duration * FPS
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(png_path),
        "-vf", (
            f"zoompan=z='min(1.05,1+0.05*on/{total_frames})':"
            f"d=1:"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"s={COVER_SIZE}x{COVER_SIZE}:"
            f"fps={FPS}"
        ),
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        str(video_path),
    ]
    return _run_ffmpeg(cmd, "Ken Burns")


def trim_audio(input_path: Path, output_path: Path,
               duration: int = CLIP_DURATION) -> bool:
    fade_out_start = max(0, duration - 3)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-t", str(duration),
        "-af", f"afade=t=in:st=0:d=1,afade=t=out:st={fade_out_start}:d=3",
        "-ar", "44100",
        "-ac", "2",
        str(output_path),
    ]
    return _run_ffmpeg(cmd, "Audio trim", timeout=120)


# ── Title / text helpers ─────────────────────────────────────────────────

def wrap_title(title: str, max_chars: int = 24) -> List[str]:
    words = title.split()
    lines: List[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if len(test) <= max_chars:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3]


def escape_ffmpeg_text(text: str) -> str:
    return text.replace("'", "'\\''")


# ── Composite ────────────────────────────────────────────────────────────

def composite_video(
    cover_video: Path,
    audio_path: Path,
    title: str,
    mood: str,
    output_path: Path,
    config: LangConfig,
    character_info: Optional[Dict[str, Any]] = None,
    age_group: Optional[str] = None,
    content_type: Optional[str] = None,
    subtype: Optional[str] = None,
) -> bool:
    """Stitch cover + audio + overlays into a 9:16 60s MP4."""
    mood_info = config.mood_display.get(mood, config.mood_display.get("calm", {
        "label": "", "color": TITLE_COLOR,
    }))
    mood_text = mood_info.get("label", "")
    mood_color = mood_info.get("color", TITLE_COLOR)

    title_lines = wrap_title(title)

    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    font = next((f for f in font_paths if os.path.exists(f)), "")
    font_arg = f":fontfile={font}" if font else ""

    filters: List[str] = []
    filters.append(f"[0:v]scale={COVER_SIZE}:{COVER_SIZE}[cover]")
    filters.append(
        f"color=c=0x{BG_COLOR}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:"
        f"d={CLIP_DURATION}:r={FPS}[bg]"
    )
    filters.append("[bg][cover]overlay=0:80[comp]")

    escaped_mood = escape_ffmpeg_text(mood_text)
    filters.append(
        f"[comp]drawtext="
        f"text='{escaped_mood}'"
        f"{font_arg}:"
        f"fontsize=36:"
        f"fontcolor=0x{mood_color}:"
        f"x=(w-text_w)/2:y=1200"
        f"[t0]"
    )

    prev = "t0"
    y_start = 1280
    for i, line in enumerate(title_lines):
        tag = f"t{i + 1}"
        escaped = escape_ffmpeg_text(line)
        filters.append(
            f"[{prev}]drawtext="
            f"text='{escaped}'"
            f"{font_arg}:"
            f"fontsize=52:"
            f"fontcolor=0x{TITLE_COLOR}:"
            f"x=(w-text_w)/2:y={y_start + i * 65}"
            f"[{tag}]"
        )
        prev = tag

    tag_idx = len(title_lines) + 1
    title_bottom = y_start + len(title_lines) * 65 + 20

    if character_info:
        char_name = character_info.get("name", "")
        char_identity = character_info.get("identity", "")
        if char_name and char_identity:
            short_identity = char_identity
            if len(short_identity) > 40:
                short_identity = short_identity[:40].rsplit(" ", 1)[0]
            char_text = f"{char_name} — {short_identity}"
        elif char_name:
            char_text = char_name
        else:
            char_text = ""

        if char_text:
            char_tag = f"t{tag_idx}"
            escaped_char = escape_ffmpeg_text(char_text)
            filters.append(
                f"[{prev}]drawtext="
                f"text='{escaped_char}'"
                f"{font_arg}:"
                f"fontsize=32:"
                f"fontcolor=0xC0B8A8:"
                f"x=(w-text_w)/2:y={title_bottom + 40}"
                f"[{char_tag}]"
            )
            prev = char_tag
            tag_idx += 1

    info_parts: List[str] = []
    if age_group:
        info_parts.append(f"{config.ages_prefix} {age_group}")
    type_key = subtype if (subtype and subtype in config.type_labels) else content_type
    if type_key and type_key in config.type_labels:
        info_parts.append(config.type_labels[type_key])
    if info_parts:
        info_text = " · ".join(info_parts)
        info_text_escaped = escape_ffmpeg_text(info_text)
        info_tag = f"t{tag_idx}"
        char_line_offset = 80 if character_info else 40
        filters.append(
            f"[{prev}]drawtext="
            f"text='{info_text_escaped}'"
            f"{font_arg}:"
            f"fontsize=28:"
            f"fontcolor=0x{BRAND_COLOR}:"
            f"x=(w-text_w)/2:y={title_bottom + char_line_offset + 40}"
            f"[{info_tag}]"
        )
        prev = info_tag
        tag_idx += 1

    brand_tag = f"t{tag_idx}"
    escaped_brand = escape_ffmpeg_text(config.brand_text)
    filters.append(
        f"[{prev}]drawtext="
        f"text='{escaped_brand}'"
        f"{font_arg}:"
        f"fontsize=28:"
        f"fontcolor=0x{BRAND_COLOR}:"
        f"x=(w-text_w)/2:y=1780"
        f"[{brand_tag}]"
    )

    filters.append(
        f"[{brand_tag}]fade=t=in:st=0:d=1,fade=t=out:st={CLIP_DURATION - 3}:d=3[final_v]"
    )

    filter_chain = ";\n".join(filters)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(cover_video),
        "-i", str(audio_path),
        "-filter_complex", filter_chain,
        "-map", "[final_v]",
        "-map", "1:a",
        "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.0",
        "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-tag:v", "avc1",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(CLIP_DURATION),
        "-movflags", "+faststart",
        "-shortest",
        str(output_path),
    ]

    return _run_ffmpeg(cmd, "Composite", timeout=FFMPEG_COMPOSITE_TIMEOUT)


# ── Metadata ─────────────────────────────────────────────────────────────

def derive_age_group(story: Dict[str, Any]) -> str:
    age_group = story.get("age_group", "")
    if age_group:
        return age_group
    age = story.get("target_age", 4)
    if age <= 1:
        return "0-1"
    if age <= 5:
        return "2-5"
    if age <= 8:
        return "6-8"
    return "9-12"


def write_clip_metadata(story: Dict[str, Any], voice: str, clip_path: Path,
                        config: LangConfig) -> str:
    age_group = derive_age_group(story)
    short_id = story["id"][:8]
    meta = {
        "storyId": short_id,
        "fullStoryId": story["id"],
        "voice": voice,
        "lang": config.lang,
        "title": story.get("title", "Untitled"),
        "mood": story.get("mood", "calm"),
        "ageGroup": age_group,
        "contentType": story.get("type", "story"),
        "subtype": story.get("subtype"),
        "generatedAt": datetime.utcnow().isoformat() + "Z",
        "duration": CLIP_DURATION,
        "fileSize": clip_path.stat().st_size if clip_path.exists() else 0,
        "filename": clip_path.name,
        "posted": {"youtube": None, "instagram": None, "tiktok": None},
        "captions": config.caption_builder(
            title=story.get("title", "Untitled"),
            mood=story.get("mood", "calm"),
            age_group=age_group,
            story_id=story["id"],
            voice=voice,
            content_type=story.get("type", "story"),
            subtype=story.get("subtype"),
            config=config,
        ),
    }
    meta_path = str(clip_path).replace(".mp4", ".json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta_path


# ── Single clip ──────────────────────────────────────────────────────────

def generate_clip(story: Dict[str, Any], voice: str, audio_url: str,
                  output_dir: Path, config: LangConfig,
                  force: bool = False) -> Optional[str]:
    story_id = story["id"]
    short_id = story_id[:8]
    title = story.get("title", "Untitled")

    output_filename = f"{short_id}_{voice}_clip.mp4"
    final_clip = output_dir / output_filename

    if final_clip.exists() and not force:
        logger.info("  %s already exists, skipping", output_filename)
        return None

    logger.info("  Generating: %s (%s voice)", title, voice)

    cover_path = story.get("cover", "")
    if cover_path.startswith("/covers/"):
        svg_path = COVERS_DIR / cover_path.removeprefix("/covers/")
    elif cover_path.startswith("/"):
        svg_path = WEB_DIR / "public" / cover_path.removeprefix("/")
    else:
        svg_path = COVERS_DIR / f"{story_id}.svg"

    if not svg_path.exists():
        logger.warning("    Cover not found: %s", svg_path)
        return None

    audio_filename = audio_url.split("/")[-1] if audio_url else f"{short_id}_{voice}.mp3"
    audio_path = AUDIO_DIR / audio_filename
    if not audio_path.exists():
        logger.warning("    Audio not found: %s", audio_path)
        return None

    with tempfile.TemporaryDirectory(prefix="clip_") as work_dir:
        work = Path(work_dir)

        png_path = work / "cover.png"
        logger.info("    Step 1: SVG → PNG")
        if not svg_to_png(svg_path, png_path):
            return None

        cover_video = work / "cover.mp4"
        logger.info("    Step 2: Ken Burns video (%ds)", CLIP_DURATION)
        if not create_ken_burns_video(png_path, cover_video):
            return None

        trimmed_audio = work / "narration_60s.wav"
        logger.info("    Step 3: Trim audio to %ds", CLIP_DURATION)
        if not trim_audio(audio_path, trimmed_audio):
            return None

        logger.info("    Step 4: Compositing final video")
        if not composite_video(
            cover_video, trimmed_audio, title,
            story.get("mood", "calm"), final_clip,
            config=config,
            character_info=story.get("character"),
            age_group=story.get("age_group", story.get("ageGroup", "")),
            content_type=story.get("type", story.get("contentType", "")),
            subtype=story.get("subtype"),
        ):
            return None

    write_clip_metadata(story, voice, final_clip, config)
    file_size = final_clip.stat().st_size
    logger.info("    ✓ %s (%.1f MB)", output_filename, file_size / 1024 / 1024)

    return str(final_clip)


# ── Back-catalog ─────────────────────────────────────────────────────────

def pick_unclipped(stories: List[Dict[str, Any]], voice: str,
                   output_dir: Path) -> Optional[Dict[str, Any]]:
    for story in stories:
        short_id = story["id"][:8]
        clip_path = output_dir / f"{short_id}_{voice}_clip.mp4"
        if not clip_path.exists():
            variants = story.get("audio_variants", [])
            has_voice = any(v["voice"] == voice for v in variants)
            if has_voice or voice.startswith("default"):
                return story
    return None


# ── Daily plan ───────────────────────────────────────────────────────────

def generate_daily_clips(stories: List[Dict[str, Any]], output_dir: Path,
                         config: LangConfig, force: bool = False,
                         dry_run: bool = False) -> List[str]:
    voices = get_daily_voice_assignment(config)
    logger.info("Voice assignment (%s): story=%s, poem=%s, lullaby=%s",
                config.lang, voices["story"], voices["poem"], voices["lullaby"])

    today = date.today().isoformat()

    all_stories = [s for s in stories if s.get("type", "story") in ("story", "long_story")]
    all_poems = [s for s in stories if s.get("type") == "poem"]
    all_lullabies = [s for s in stories if s.get("type") == "song"]

    def is_today(s: Dict[str, Any]) -> bool:
        added = s.get("addedAt") or s.get("created_at") or ""
        return added[:10] == today

    new_stories = [s for s in all_stories if is_today(s)]
    new_poems = [s for s in all_poems if is_today(s)]
    new_lullabies = [s for s in all_lullabies if is_today(s)]

    clips_plan: List[Tuple[str, Dict[str, Any], str, str]] = []

    if new_stories:
        story = new_stories[0]
        voice, url = get_voice_for_story(story, voices, config)
        if voice:
            clips_plan.append(("NEW story", story, voice, url))

    if new_poems:
        poem = new_poems[0]
        voice, url = get_voice_for_story(poem, voices, config)
        if voice:
            clips_plan.append(("NEW poem", poem, voice, url))

    if new_lullabies:
        lullaby = new_lullabies[0]
        voice, url = get_voice_for_story(lullaby, voices, config)
        if voice:
            clips_plan.append(("NEW lullaby", lullaby, voice, url))

    old_story = pick_unclipped(all_stories, voices["story"], output_dir)
    if old_story:
        voice, url = get_voice_for_story(old_story, voices, config)
        if voice:
            clips_plan.append(("CATALOG story", old_story, voice, url))

    old_poem = pick_unclipped(all_poems, voices["poem"], output_dir)
    if old_poem:
        voice, url = get_voice_for_story(old_poem, voices, config)
        if voice:
            clips_plan.append(("CATALOG poem", old_poem, voice, url))

    old_lullaby = pick_unclipped(all_lullabies, voices["lullaby"], output_dir)
    if old_lullaby:
        voice, url = get_voice_for_story(old_lullaby, voices, config)
        if voice:
            clips_plan.append(("CATALOG lullaby", old_lullaby, voice, url))

    if len(clips_plan) > MAX_CLIPS_PER_RUN:
        logger.warning("  Capping from %d to %d clips", len(clips_plan), MAX_CLIPS_PER_RUN)
        clips_plan = clips_plan[:MAX_CLIPS_PER_RUN]

    logger.info("\n=== Clip Generation Plan (%s) ===", config.lang)
    logger.info("Total clips: %d", len(clips_plan))
    for label, story, voice, url in clips_plan:
        logger.info("  [%s] %s / %s", label, story.get("title", "?")[:40], voice)

    if dry_run:
        logger.info("\nDry run complete.")
        return []

    generated: List[str] = []
    for label, story, voice, url in clips_plan:
        logger.info("\n[%s] %s", label, story.get("title", "?"))
        result = generate_clip(story, voice, url, output_dir, config, force=force)
        if result:
            generated.append(result)

    logger.info("\n=== Summary ===")
    logger.info("Generated: %d / %d clips", len(generated), len(clips_plan))
    return generated


# ── Top-level orchestration ─────────────────────────────────────────────

def load_content() -> List[Dict[str, Any]]:
    if not CONTENT_PATH.exists():
        logger.error("Content not found: %s", CONTENT_PATH)
        sys.exit(1)
    with open(CONTENT_PATH) as f:
        return json.load(f)


def filter_stories(stories: List[Dict[str, Any]], config: LangConfig) -> List[Dict[str, Any]]:
    return [
        s for s in stories
        if isinstance(s, dict)
        and s.get("audio_variants")
        and config.filter_content(s)
    ]


def run_main(config: LangConfig, argv: Optional[List[str]] = None) -> None:
    """Single entry point used by both generate_clips.py and generate_clips_hi.py."""
    import argparse

    parser = argparse.ArgumentParser(description=f"Generate {config.lang} social-media clips")
    parser.add_argument("--story-id", help="Generate clip for a specific story ID")
    parser.add_argument("--force", action="store_true", help="Overwrite existing clips")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without generating")
    parser.add_argument("--batch", action="store_true", help="Generate clips for all unclipped stories")
    parser.add_argument("--limit", type=int, help="Max clips to generate in batch mode")
    parser.add_argument("--output-dir", default=str(config.output_dir), help="Output directory")
    parser.add_argument("--no-email", action="store_true", help="Don't send email notification")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stories = filter_stories(load_content(), config)
    logger.info("Loaded %d %s stories with audio from %s",
                len(stories), config.lang, CONTENT_PATH.name)

    generated_clips: List[str] = []
    start_time = time.time()

    if args.story_id:
        story = next((s for s in stories if s["id"] == args.story_id), None)
        if not story:
            logger.error("Story not found: %s", args.story_id)
            sys.exit(1)

        voices = get_daily_voice_assignment(config)
        voice, url = get_voice_for_story(story, voices, config)
        if not voice:
            logger.error("No audio variant available for %s", args.story_id)
            sys.exit(1)

        logger.info("Single clip: %s / %s", story.get("title", "?"), voice)
        if args.dry_run:
            logger.info("Dry run — would generate %s_%s_clip.mp4", story["id"][:8], voice)
            return

        result = generate_clip(story, voice, url, output_dir, config, force=args.force)
        if result:
            logger.info("Done: %s", result)
            generated_clips.append(result)
        else:
            logger.error("Clip generation failed")
            sys.exit(1)

    elif args.batch:
        voices = get_daily_voice_assignment(config)
        plan: List[Tuple[Dict[str, Any], str, str]] = []
        for story in stories:
            voice, url = get_voice_for_story(story, voices, config)
            if voice:
                short_id = story["id"][:8]
                clip_path = output_dir / f"{short_id}_{voice}_clip.mp4"
                if not clip_path.exists() or args.force:
                    plan.append((story, voice, url))

        if args.limit:
            plan = plan[:args.limit]

        logger.info("\n=== Batch Plan: %d clips ===", len(plan))
        for story, voice, url in plan:
            logger.info("  %s / %s", story.get("title", "?")[:40], voice)

        if args.dry_run:
            logger.info("\nDry run complete.")
            return

        generated = 0
        errors = 0
        for story, voice, url in plan:
            logger.info("\n[%d/%d] %s", generated + errors + 1, len(plan), story.get("title", "?"))
            result = generate_clip(story, voice, url, output_dir, config, force=args.force)
            if result:
                generated += 1
                generated_clips.append(result)
            else:
                errors += 1

        logger.info("\n=== Summary: %d generated, %d errors ===", generated, errors)

    else:
        results = generate_daily_clips(stories, output_dir, config,
                                       force=args.force, dry_run=args.dry_run)
        generated_clips = results or []

    if generated_clips and not args.dry_run and not args.no_email:
        elapsed = time.time() - start_time
        try:
            clips_info: List[Dict[str, Any]] = []
            for clip_path in generated_clips:
                meta_path = str(clip_path).replace(".mp4", ".json")
                if os.path.exists(meta_path):
                    with open(meta_path) as f:
                        clips_info.append(json.load(f))

            if clips_info:
                sys.path.insert(0, str(Path(__file__).parent))
                from pipeline_notify import send_clips_notification  # type: ignore
                send_clips_notification(clips_info, elapsed)
        except Exception as e:
            logger.warning("Email notification failed: %s", e)
