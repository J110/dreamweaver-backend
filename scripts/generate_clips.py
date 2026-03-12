#!/usr/bin/env python3
"""
generate_clips.py — Generate 60-second vertical social media clips for YouTube Shorts / Reels / TikTok.

Each clip is 1080×1920 (9:16) containing:
  - Animated SVG cover rendered as static PNG with Ken Burns zoom effect
  - 60 seconds of narration audio (trimmed from pre-generated audio)
  - Text overlays: mood tag, title, branding

Usage:
    python3 scripts/generate_clips.py                          # Daily 6 clips (3 new + 3 back-catalog)
    python3 scripts/generate_clips.py --story-id <id>          # Single story clip
    python3 scripts/generate_clips.py --force                   # Overwrite existing clips
    python3 scripts/generate_clips.py --dry-run                 # Preview plan only
    python3 scripts/generate_clips.py --batch                   # All unclipped stories
    python3 scripts/generate_clips.py --limit 5                 # Limit batch size
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
CLIPS_DIR = BASE_DIR / "clips"
WEB_DIR = BASE_DIR.parent / "dreamweaver-web"
COVERS_DIR = WEB_DIR / "public" / "covers"
AUDIO_DIR = WEB_DIR / "public" / "audio" / "pre-gen"

# ── Load .env ────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("clips")

# ── Constants ────────────────────────────────────────────────────────────
CLIP_DURATION = 60
FPS = 30
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
COVER_SIZE = 1080
BG_COLOR = "0D0B2E"  # hex without #
TITLE_COLOR = "F5E6D3"
BRAND_COLOR = "888888"

MOOD_DISPLAY = {
    "wired":   {"label": "Silly",      "emoji": "😄", "color": "FFB946"},
    "curious": {"label": "Adventure",  "emoji": "🔮", "color": "7B68EE"},
    "calm":    {"label": "Gentle",     "emoji": "🌙", "color": "6BB5C9"},
    "sad":     {"label": "Comfort",    "emoji": "💛", "color": "E8A87C"},
    "anxious": {"label": "Brave",      "emoji": "🛡️",  "color": "85C88A"},
    "angry":   {"label": "Let It Out", "emoji": "🌊", "color": "C9896D"},
}

# Voice label for captions
VOICE_LABELS = {
    "female_1": "calm voice",
    "asmr": "ASMR whisper voice",
    "default": "",
}

VOICE_TAGS = {
    "female_1": "#calmvoice",
    "asmr": "#asmr #asmrforkids",
    "default": "#lullaby",
}


# ── Voice Assignment ─────────────────────────────────────────────────────

def get_daily_voice_assignment():
    """Deterministic daily coin flip — same date = same assignment."""
    today = date.today().isoformat()
    flip = int(hashlib.md5(today.encode()).hexdigest(), 16) % 2
    if flip == 0:
        return {"story": "female_1", "poem": "asmr", "lullaby": "default"}
    else:
        return {"story": "asmr", "poem": "female_1", "lullaby": "default"}


def get_voice_for_story(story, voice_assignment):
    """Get the voice variant to use for a given story based on today's assignment."""
    content_type = story.get("type", "story").lower()
    if content_type == "song":
        assigned = voice_assignment.get("lullaby", "default")
    elif content_type == "poem":
        assigned = voice_assignment.get("poem", "female_1")
    else:
        assigned = voice_assignment.get("story", "female_1")

    # For "default" (lullabies), pick the first available variant
    variants = story.get("audio_variants", [])
    if not variants:
        return None, None

    if assigned == "default":
        v = variants[0]
        return v["voice"], v["url"]

    # Try to find the assigned voice
    for v in variants:
        if v["voice"] == assigned:
            return v["voice"], v["url"]

    # Fallback: use first available
    v = variants[0]
    return v["voice"], v["url"]


# ── SVG to PNG ───────────────────────────────────────────────────────────

def svg_to_png(svg_path, png_path, size=COVER_SIZE):
    """Convert SVG to PNG using cairosvg."""
    try:
        import cairosvg
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=size,
            output_height=size,
        )
        return True
    except Exception as e:
        logger.warning("  cairosvg failed: %s — trying rsvg-convert fallback", e)
        # Fallback: rsvg-convert
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


# ── Ken Burns Video ──────────────────────────────────────────────────────

def create_ken_burns_video(png_path, video_path, duration=CLIP_DURATION):
    """Create a slow-zoom (Ken Burns) video from a static image via FFmpeg."""
    # Slow zoom from 1.0x to 1.05x over the duration, centered
    # d=1 means each frame uses one input frame (since we loop the image)
    # on = output frame number
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
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("  Ken Burns FFmpeg failed: %s", result.stderr[-500:])
        return False
    return True


# ── Audio Processing ─────────────────────────────────────────────────────

def trim_audio(input_path, output_path, duration=CLIP_DURATION):
    """Trim audio to duration with fade in (1s) and fade out (3s)."""
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
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("  Audio trim failed: %s", result.stderr[-500:])
        return False
    return True


# ── Title Wrapping ───────────────────────────────────────────────────────

def wrap_title(title, max_chars=24):
    """Split title into lines that fit the video width."""
    words = title.split()
    lines = []
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
    return lines[:3]  # max 3 lines


def escape_ffmpeg_text(text):
    """Escape special characters for FFmpeg drawtext filter."""
    # FFmpeg drawtext needs these chars escaped
    for ch in [":", "'", "\\", "[", "]", ";", ","]:
        text = text.replace(ch, f"\\{ch}")
    return text


# ── Video Compositing ────────────────────────────────────────────────────

def composite_video(cover_video, audio_path, title, mood, output_path):
    """Combine cover video + audio + text overlays into final 9:16 clip."""
    mood_info = MOOD_DISPLAY.get(mood, MOOD_DISPLAY["calm"])
    mood_text = f"{mood_info['label']}"
    mood_color = mood_info["color"]

    title_lines = wrap_title(title)
    brand_text = "dreamvalley.app"

    # Find a suitable font
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",  # macOS
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",  # Arch
    ]
    font = next((f for f in font_paths if os.path.exists(f)), "")
    font_arg = f":fontfile={font}" if font else ""

    # Build FFmpeg filter chain
    filters = []

    # Scale cover to 1080x1080
    filters.append(f"[0:v]scale={COVER_SIZE}:{COVER_SIZE}[cover]")

    # Dark background
    filters.append(
        f"color=c=0x{BG_COLOR}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d={CLIP_DURATION}:r={FPS}[bg]"
    )

    # Place cover on background (top, 80px padding)
    filters.append("[bg][cover]overlay=0:80[comp]")

    # Mood tag text
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

    # Title lines
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

    # Branding
    brand_tag = f"t{len(title_lines) + 1}"
    escaped_brand = escape_ffmpeg_text(brand_text)
    filters.append(
        f"[{prev}]drawtext="
        f"text='{escaped_brand}'"
        f"{font_arg}:"
        f"fontsize=28:"
        f"fontcolor=0x{BRAND_COLOR}:"
        f"x=(w-text_w)/2:y=1780"
        f"[{brand_tag}]"
    )

    # Fade in/out
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
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(CLIP_DURATION),
        "-movflags", "+faststart",
        "-shortest",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("  Composite failed: %s", result.stderr[-500:])
        return False
    return True


# ── Captions ─────────────────────────────────────────────────────────────

def generate_captions(title, mood, age_group, story_id, voice):
    """Generate platform-specific captions for the clip."""
    mood_info = MOOD_DISPLAY.get(mood, MOOD_DISPLAY["calm"])
    voice_label = VOICE_LABELS.get(voice, "")
    voice_tag = VOICE_TAGS.get(voice, "")

    youtube = (
        f"{title} {mood_info['emoji']} | Bedtime Story for Kids"
        f"{' (' + voice_label + ')' if voice_label else ''}\n\n"
        f"A {mood_info['label'].lower()} bedtime story for ages {age_group}. "
        f"Listen to the full story free on Dream Valley.\n\n"
        f"\U0001F319 dreamvalley.app\n\n"
        f"#bedtimestory #kidssleep #bedtimeroutine #storytime "
        f"#dreamvalley {voice_tag}"
    )

    instagram = (
        f"{title} {mood_info['emoji']}"
        f"{' · ' + voice_label if voice_label else ''}\n\n"
        f"A {mood_info['label'].lower()} bedtime story for ages {age_group}. "
        f"Full story free on dreamvalley.app \U0001F319\n\n"
        f"#bedtimestories #toddlerbedtime #kidssleep "
        f"#parentinghack #bedtimeroutine {voice_tag}"
    )

    tiktok = (
        f"{title} {mood_info['emoji']}"
        f"{' · ' + voice_label if voice_label else ''}\n\n"
        f"dreamvalley.app \U0001F319\n\n"
        f"#bedtimestory #toddlermom #bedtimeroutine "
        f"#kidssleep {voice_tag}"
    )

    return {"youtube": youtube, "instagram": instagram, "tiktok": tiktok}


# ── Metadata ─────────────────────────────────────────────────────────────

def write_clip_metadata(story, voice, clip_path):
    """Write metadata JSON alongside the MP4."""
    age_group = story.get("age_group", "")
    if not age_group:
        age = story.get("target_age", 4)
        if age <= 1:
            age_group = "0-1"
        elif age <= 5:
            age_group = "2-5"
        elif age <= 8:
            age_group = "6-8"
        else:
            age_group = "9-12"

    meta = {
        "storyId": story["id"],
        "voice": voice,
        "title": story.get("title", "Untitled"),
        "mood": story.get("mood", "calm"),
        "ageGroup": age_group,
        "contentType": story.get("type", "story"),
        "generatedAt": datetime.utcnow().isoformat() + "Z",
        "duration": CLIP_DURATION,
        "fileSize": os.path.getsize(clip_path) if os.path.exists(clip_path) else 0,
        "filename": os.path.basename(clip_path),
        "posted": {"youtube": None, "instagram": None, "tiktok": None},
        "captions": generate_captions(
            story.get("title", "Untitled"),
            story.get("mood", "calm"),
            age_group,
            story["id"],
            voice,
        ),
    }
    meta_path = str(clip_path).replace(".mp4", ".json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta_path


# ── Single Clip Generation ───────────────────────────────────────────────

def generate_clip(story, voice, audio_url, output_dir, force=False):
    """Generate one 60-second clip for a story with the given voice."""
    story_id = story["id"]
    short_id = story_id[:8]
    title = story.get("title", "Untitled")

    output_filename = f"{short_id}_{voice}_clip.mp4"
    final_clip = output_dir / output_filename

    # Skip if exists
    if final_clip.exists() and not force:
        logger.info("  %s already exists, skipping", output_filename)
        return str(final_clip)

    logger.info("  Generating: %s (%s voice)", title, voice)

    # Resolve file paths
    cover_path = story.get("cover", "")
    if cover_path.startswith("/covers/"):
        svg_path = COVERS_DIR / cover_path.lstrip("/covers/")
    elif cover_path.startswith("/"):
        svg_path = WEB_DIR / "public" / cover_path.lstrip("/")
    else:
        svg_path = COVERS_DIR / f"{story_id}.svg"

    if not svg_path.exists():
        logger.warning("    Cover not found: %s", svg_path)
        return None

    # Audio path
    audio_filename = audio_url.split("/")[-1] if audio_url else f"{short_id}_{voice}.mp3"
    audio_path = AUDIO_DIR / audio_filename
    if not audio_path.exists():
        logger.warning("    Audio not found: %s", audio_path)
        return None

    # Work in temp directory
    with tempfile.TemporaryDirectory(prefix="clip_") as work_dir:
        work = Path(work_dir)

        # Step 1: SVG → PNG
        png_path = work / "cover.png"
        logger.info("    Step 1: SVG → PNG")
        if not svg_to_png(svg_path, png_path):
            return None

        # Step 2: Ken Burns video
        cover_video = work / "cover.mp4"
        logger.info("    Step 2: Ken Burns video (%ds)", CLIP_DURATION)
        if not create_ken_burns_video(png_path, cover_video):
            return None

        # Step 3: Trim audio
        trimmed_audio = work / "narration_60s.wav"
        logger.info("    Step 3: Trim audio to %ds", CLIP_DURATION)
        if not trim_audio(audio_path, trimmed_audio):
            return None

        # Step 4: Composite final video
        logger.info("    Step 4: Compositing final video")
        if not composite_video(
            cover_video, trimmed_audio, title,
            story.get("mood", "calm"), final_clip,
        ):
            return None

    # Write metadata
    meta_path = write_clip_metadata(story, voice, final_clip)
    file_size = final_clip.stat().st_size
    logger.info("    ✓ %s (%.1f MB)", output_filename, file_size / 1024 / 1024)

    return str(final_clip)


# ── Back-Catalog Selection ───────────────────────────────────────────────

def pick_unclipped(stories, voice, output_dir):
    """Pick a story that doesn't have a clip in this voice yet. Oldest first."""
    for story in stories:
        short_id = story["id"][:8]
        clip_path = output_dir / f"{short_id}_{voice}_clip.mp4"
        if not clip_path.exists():
            # Check the story has this voice variant available
            variants = story.get("audio_variants", [])
            has_voice = any(v["voice"] == voice for v in variants)
            if has_voice or voice == "default":
                return story
    return None


# ── Daily Generation ─────────────────────────────────────────────────────

def generate_daily_clips(stories, output_dir, force=False, dry_run=False):
    """Generate 6 clips per day: 3 new + 3 back-catalog."""
    voices = get_daily_voice_assignment()
    logger.info("Voice assignment: story=%s, poem=%s, lullaby=%s",
                voices["story"], voices["poem"], voices["lullaby"])

    today = date.today().isoformat()

    # Separate by type
    all_stories = [s for s in stories if s.get("type", "story") in ("story", "long_story")]
    all_poems = [s for s in stories if s.get("type") == "poem"]
    all_lullabies = [s for s in stories if s.get("type") == "song"]

    # Find today's new content (by addedAt or created_at date)
    def is_today(s):
        added = s.get("addedAt") or s.get("created_at") or ""
        return added[:10] == today

    new_stories = [s for s in all_stories if is_today(s)]
    new_poems = [s for s in all_poems if is_today(s)]
    new_lullabies = [s for s in all_lullabies if is_today(s)]

    clips_plan = []

    # --- 3 NEW CLIPS ---
    if new_stories:
        story = new_stories[0]
        voice, url = get_voice_for_story(story, voices)
        if voice:
            clips_plan.append(("NEW story", story, voice, url))

    if new_poems:
        poem = new_poems[0]
        voice, url = get_voice_for_story(poem, voices)
        if voice:
            clips_plan.append(("NEW poem", poem, voice, url))

    if new_lullabies:
        lullaby = new_lullabies[0]
        voice, url = get_voice_for_story(lullaby, voices)
        if voice:
            clips_plan.append(("NEW lullaby", lullaby, voice, url))

    # --- 3 BACK-CATALOG CLIPS ---
    old_story = pick_unclipped(all_stories, voices["story"], output_dir)
    if old_story:
        voice, url = get_voice_for_story(old_story, voices)
        if voice:
            clips_plan.append(("CATALOG story", old_story, voice, url))

    old_poem = pick_unclipped(all_poems, voices["poem"], output_dir)
    if old_poem:
        voice, url = get_voice_for_story(old_poem, voices)
        if voice:
            clips_plan.append(("CATALOG poem", old_poem, voice, url))

    old_lullaby = pick_unclipped(all_lullabies, voices["lullaby"], output_dir)
    if old_lullaby:
        voice, url = get_voice_for_story(old_lullaby, voices)
        if voice:
            clips_plan.append(("CATALOG lullaby", old_lullaby, voice, url))

    # Show plan
    logger.info("\n=== Clip Generation Plan ===")
    logger.info("Total clips: %d", len(clips_plan))
    for label, story, voice, url in clips_plan:
        logger.info("  [%s] %s / %s", label, story.get("title", "?")[:40], voice)

    if dry_run:
        logger.info("\nDry run complete.")
        return []

    # Generate
    generated = []
    for label, story, voice, url in clips_plan:
        logger.info("\n[%s] %s", label, story.get("title", "?"))
        result = generate_clip(story, voice, url, output_dir, force=force)
        if result:
            generated.append(result)

    logger.info("\n=== Summary ===")
    logger.info("Generated: %d / %d clips", len(generated), len(clips_plan))
    return generated


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate social media clips")
    parser.add_argument("--story-id", help="Generate clip for a specific story ID")
    parser.add_argument("--force", action="store_true", help="Overwrite existing clips")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without generating")
    parser.add_argument("--batch", action="store_true", help="Generate clips for all unclipped stories")
    parser.add_argument("--limit", type=int, help="Max clips to generate in batch mode")
    parser.add_argument("--output-dir", default=str(CLIPS_DIR), help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load content
    if not CONTENT_PATH.exists():
        logger.error("Content not found: %s", CONTENT_PATH)
        sys.exit(1)

    with open(CONTENT_PATH) as f:
        stories = json.load(f)

    # Filter to stories with audio variants
    stories = [s for s in stories if isinstance(s, dict) and s.get("audio_variants")]
    logger.info("Loaded %d stories with audio from %s", len(stories), CONTENT_PATH.name)

    if args.story_id:
        # Single story mode
        story = next((s for s in stories if s["id"] == args.story_id), None)
        if not story:
            logger.error("Story not found: %s", args.story_id)
            sys.exit(1)

        voices = get_daily_voice_assignment()
        voice, url = get_voice_for_story(story, voices)
        if not voice:
            logger.error("No audio variant available for %s", args.story_id)
            sys.exit(1)

        logger.info("Single clip: %s / %s", story.get("title", "?"), voice)
        if args.dry_run:
            logger.info("Dry run — would generate %s_%s_clip.mp4", story["id"][:8], voice)
            return

        result = generate_clip(story, voice, url, output_dir, force=args.force)
        if result:
            logger.info("Done: %s", result)
        else:
            logger.error("Clip generation failed")
            sys.exit(1)

    elif args.batch:
        # Batch: generate for all unclipped stories
        voices = get_daily_voice_assignment()
        plan = []
        for story in stories:
            voice, url = get_voice_for_story(story, voices)
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
            result = generate_clip(story, voice, url, output_dir, force=args.force)
            if result:
                generated += 1
            else:
                errors += 1

        logger.info("\n=== Summary: %d generated, %d errors ===", generated, errors)

    else:
        # Daily mode: 6 clips
        generate_daily_clips(stories, output_dir, force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
