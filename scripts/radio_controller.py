#!/usr/bin/env python3
"""
Dream Valley Radio — 24/7 live stream controller.

Loads content from the PRODUCTION API (only what's live), verifies audio
exists on disk, composites cover art with branding, and streams via RTMP
to YouTube Live.

Usage:
    python3 scripts/radio_controller.py                    # Start streaming
    python3 scripts/radio_controller.py --dry-run          # Test without streaming
    python3 scripts/radio_controller.py --test-minutes 10  # Stream for N minutes then stop
    python3 scripts/radio_controller.py --list-content      # Show all playable content
"""

import json
import os
import random
import signal
import re
import subprocess
import sys
import time
import argparse
import logging
import urllib.request
from collections import Counter
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = "https://api.dreamvalley.app/api/v1"
WEB_PUBLIC = "/opt/dreamweaver-web/public"

STATE_FILE = "radio/radio_state.json"
LOG_DIR = "radio/logs"

STREAM_WIDTH = 1280
STREAM_HEIGHT = 720
COVER_OUTPUT = "/tmp/radio_current_frame.png"
TRANSITION_OUTPUT = "/tmp/radio_transition.png"
BATCH_DIR = "/tmp/radio_batch"
BATCH_SIZE = 6  # tracks per ffmpeg session (RTMP stays open within batch)
TRANSITION_DURATION = 2.0  # seconds of silence + placeholder between tracks
SILENCE_AUDIO = "/tmp/radio_batch/silence.mp3"

YOUTUBE_RTMP = "rtmp://a.rtmp.youtube.com/live2"

# Brand colors
BG_COLOR = (15, 15, 35)
TEXT_COLOR = (255, 248, 230)
ACCENT_COLOR = (255, 200, 100)
SUBTITLE_COLOR = (180, 180, 200)
FOOTER_COLOR = (120, 120, 150)
LIVE_COLOR = (220, 50, 50)

CONTENT_WEIGHTS = {
    "story":       4,
    "long_story":  2,
    "song":        3,
    "silly_song":  3,
    "funny_short": 3,
    "poem":        2,
    "lullaby":     3,
}

FLOW_PATTERN = [
    "silly_song",
    "story",
    "poem",
    "story",
    "song",
    "funny_short",
    "story",
    "lullaby",
    "long_story",
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"radio_{datetime.now().strftime('%Y%m%d')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("radio")


# ---------------------------------------------------------------------------
# API Content Loading
# ---------------------------------------------------------------------------

def api_fetch(endpoint):
    """Fetch JSON from an API endpoint."""
    url = f"{API_BASE}/{endpoint}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read())
    # Unwrap standard response envelope
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


def resolve_disk_path(url_path):
    """Convert a URL path like /audio/pre-gen/x.mp3 to absolute disk path.
    Returns the path only if the file exists on disk."""
    if not url_path:
        return None
    fp = os.path.join(WEB_PUBLIC, url_path.lstrip("/"))
    return fp if os.path.exists(fp) else None


def load_main_content(logger):
    """Load stories, songs, and long_stories from the paginated content API."""
    tracks = []
    page = 1
    while True:
        try:
            data = api_fetch(f"content?lang=en&page={page}")
        except Exception as e:
            logger.warning(f"Content API page {page} failed: {e}")
            break

        items = data.get("items", []) if isinstance(data, dict) else []
        if not items:
            break

        for item in items:
            content_type = item.get("type", "story")
            audio_variants = item.get("audio_variants", [])
            if not isinstance(audio_variants, list) or not audio_variants:
                continue

            # Find first audio variant that exists on disk
            audio_path = None
            for av in audio_variants:
                audio_path = resolve_disk_path(av.get("url"))
                if audio_path:
                    break
            if not audio_path:
                continue

            cover_path = resolve_disk_path(item.get("cover"))

            tracks.append({
                "id": item.get("id", ""),
                "title": item.get("title", "Untitled"),
                "content_type": content_type,
                "age_group": f"{item.get('age_min', '?')}-{item.get('age_max', '?')}",
                "audio_path": audio_path,
                "cover_path": cover_path,
                "duration_seconds": item.get("duration_seconds", 0),
            })

        total_pages = data.get("pages", 1)
        if page >= total_pages:
            break
        page += 1

    return tracks


def load_funny_shorts(logger):
    """Load funny shorts from the API."""
    tracks = []
    try:
        data = api_fetch("funny-shorts")
    except Exception as e:
        logger.warning(f"Funny shorts API failed: {e}")
        return tracks

    items = data.get("items", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return tracks

    for item in items:
        audio_url = item.get("audio_url", "")
        audio_path = resolve_disk_path(audio_url)
        if not audio_path:
            continue

        cover_path = resolve_disk_path(item.get("cover"))

        tracks.append({
            "id": item.get("id", ""),
            "title": item.get("title", "Untitled"),
            "content_type": "funny_short",
            "age_group": item.get("age_group", "all"),
            "audio_path": audio_path,
            "cover_path": cover_path,
            "duration_seconds": _parse_duration(
                item.get("duration_seconds") or
                item.get("episode_duration_seconds") or 0),
        })

    return tracks


def load_silly_songs(logger):
    """Load silly songs from the API."""
    tracks = []
    try:
        data = api_fetch("silly-songs")
    except Exception as e:
        logger.warning(f"Silly songs API failed: {e}")
        return tracks

    items = data.get("items", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return tracks

    for item in items:
        audio_file = item.get("audio_file", "")
        audio_path = resolve_disk_path(f"/audio/silly-songs/{audio_file}") if audio_file else None
        if not audio_path:
            continue

        cover_file = item.get("cover") or item.get("cover_file", "")
        cover_path = None
        if cover_file:
            if cover_file.startswith("/"):
                cover_path = resolve_disk_path(cover_file)
            else:
                cover_path = resolve_disk_path(f"/covers/silly-songs/{cover_file}")

        tracks.append({
            "id": item.get("id", ""),
            "title": item.get("title", "Untitled"),
            "content_type": "silly_song",
            "age_group": item.get("age_group", "all"),
            "audio_path": audio_path,
            "cover_path": cover_path,
            "duration_seconds": _parse_duration(item.get("duration_seconds", 0)),
        })

    return tracks


def load_poems(logger):
    """Load poems from the API."""
    tracks = []
    try:
        data = api_fetch("poems")
    except Exception as e:
        logger.warning(f"Poems API failed: {e}")
        return tracks

    items = data.get("items", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return tracks

    for item in items:
        audio_file = item.get("audio_file", "")
        audio_path = resolve_disk_path(f"/audio/poems/{audio_file}") if audio_file else None
        if not audio_path:
            continue

        cover_file = item.get("cover_file", "")
        cover_path = resolve_disk_path(f"/covers/poems/{cover_file}") if cover_file else None

        tracks.append({
            "id": item.get("id", ""),
            "title": item.get("title", "Untitled"),
            "content_type": "poem",
            "age_group": item.get("age_group", "all"),
            "audio_path": audio_path,
            "cover_path": cover_path,
            "duration_seconds": _parse_duration(item.get("duration_seconds", 0)),
        })

    return tracks


def load_lullabies(logger):
    """Load lullabies from the API."""
    tracks = []
    try:
        data = api_fetch("lullabies")
    except Exception as e:
        logger.warning(f"Lullabies API failed: {e}")
        return tracks

    items = data.get("items", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return tracks

    for item in items:
        audio_file = item.get("audio_file", "")
        audio_path = resolve_disk_path(f"/audio/lullabies/{audio_file}") if audio_file else None
        if not audio_path:
            continue

        cover_file = item.get("cover_file", "")
        item_id = item.get("id", "")
        cover_path = None
        if cover_file:
            cover_path = resolve_disk_path(f"/covers/{cover_file}")
        if not cover_path and item_id:
            cover_path = resolve_disk_path(f"/covers/{item_id}.svg")

        tracks.append({
            "id": item_id,
            "title": item.get("title", "Untitled"),
            "content_type": "lullaby",
            "age_group": item.get("age_group", "all"),
            "audio_path": audio_path,
            "cover_path": cover_path,
            "duration_seconds": _parse_duration(item.get("duration_seconds", 0)),
        })

    return tracks


def _parse_duration(val):
    """Parse duration which may be string or number."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0


def load_all_content(logger):
    """Load all playable content from all API endpoints, verified against disk."""
    all_tracks = []
    all_tracks.extend(load_main_content(logger))
    all_tracks.extend(load_funny_shorts(logger))
    all_tracks.extend(load_silly_songs(logger))
    all_tracks.extend(load_poems(logger))
    all_tracks.extend(load_lullabies(logger))
    return all_tracks


# ---------------------------------------------------------------------------
# Playlist Scheduler
# ---------------------------------------------------------------------------

class RadioScheduler:
    def __init__(self, logger):
        self.log = logger
        self.content = load_all_content(logger)
        self.play_history = []
        self.type_history = []
        self.played_set = set()
        self.flow_index = 0
        self.load_state()

        type_counts = Counter(t["content_type"] for t in self.content)
        self.log.info(f"Loaded {len(self.content)} playable tracks:")
        for ct, count in type_counts.most_common():
            self.log.info(f"  {ct}: {count}")

    def next_track(self):
        suggested_type = FLOW_PATTERN[self.flow_index % len(FLOW_PATTERN)]
        self.flow_index += 1

        unplayed = [t for t in self.content if t["id"] not in self.played_set]
        if not unplayed:
            self.log.info("All tracks played — resetting cycle")
            self.played_set.clear()
            unplayed = list(self.content)

        # Try suggested type
        candidates = [t for t in unplayed if t["content_type"] == suggested_type]

        if not candidates:
            recent_types = self.type_history[-3:]
            candidates = [t for t in unplayed
                          if t["content_type"] not in recent_types]

        if not candidates:
            candidates = unplayed

        weighted = []
        for track in candidates:
            w = CONTENT_WEIGHTS.get(track["content_type"], 1)
            weighted.extend([track] * w)

        return random.choice(weighted)

    def mark_played(self, track):
        self.play_history.append(track["id"])
        self.type_history.append(track["content_type"])
        self.played_set.add(track["id"])
        if len(self.play_history) > 500:
            self.play_history = self.play_history[-500:]
        if len(self.type_history) > 50:
            self.type_history = self.type_history[-50:]
        self.save_state()

    def refresh_content(self):
        """Re-fetch from API to pick up new content."""
        current = load_all_content(self.log)
        current_ids = {t["id"] for t in current}
        old_ids = {t["id"] for t in self.content}
        new_ids = current_ids - old_ids
        removed_ids = old_ids - current_ids

        if new_ids:
            new_tracks = [t for t in current if t["id"] in new_ids]
            self.content.extend(new_tracks)
            self.log.info(f"New content: {len(new_tracks)} tracks added")
            for t in new_tracks:
                self.log.info(f"  + {t['content_type']}: {t['title']}")

        if removed_ids:
            self.content = [t for t in self.content if t["id"] not in removed_ids]
            self.played_set -= removed_ids
            self.log.info(f"Removed {len(removed_ids)} tracks no longer live")

    def save_state(self):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        state = {
            "play_history": self.play_history[-500:],
            "type_history": self.type_history[-50:],
            "played_set": list(self.played_set),
            "flow_index": self.flow_index,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def load_state(self):
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            self.play_history = state.get("play_history", [])
            self.type_history = state.get("type_history", [])
            self.played_set = set(state.get("played_set", []))
            self.flow_index = state.get("flow_index", 0)
            self.log.info(f"Restored state: {len(self.played_set)} played, "
                          f"flow index {self.flow_index}")
        except (json.JSONDecodeError, IOError) as e:
            self.log.warning(f"Could not load state: {e}")


# ---------------------------------------------------------------------------
# Cover Compositor
# ---------------------------------------------------------------------------

def find_font(name):
    """Find a font file, with fallbacks."""
    search_paths = [
        f"radio/fonts/{name}",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in search_paths:
        if os.path.exists(path):
            return path
    return None


def extract_embedded_webp(svg_path):
    """Extract base64 webp from FLUX combined.svg. Returns PIL Image or None."""
    try:
        import base64, io
        from PIL import Image
        with open(svg_path, "r") as f:
            txt = f.read(200000)
        m = re.search(r"data:image/webp;base64,([A-Za-z0-9+/=]+)", txt)
        if not m:
            return None
        img_bytes = base64.b64decode(m.group(1))
        return Image.open(io.BytesIO(img_bytes))
    except Exception:
        return None


def convert_svg_to_image(svg_path):
    """Convert SVG to PIL Image."""
    from PIL import Image
    import io

    # FLUX combined.svg: extract embedded webp directly (rsvg 2.52 cannot render webp data URIs)
    flux_img = extract_embedded_webp(svg_path)
    if flux_img is not None:
        return flux_img

    png_tmp = "/tmp/radio_cover_tmp.png"

    # rsvg-convert (common on Ubuntu)
    try:
        subprocess.run(
            ["rsvg-convert", "-w", "500", "-h", "500", "-o", png_tmp, svg_path],
            check=True, capture_output=True, timeout=10,
        )
        return Image.open(png_tmp)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # cairosvg
    try:
        import cairosvg
        png_data = cairosvg.svg2png(url=svg_path, output_width=500, output_height=500)
        return Image.open(io.BytesIO(png_data))
    except ImportError:
        pass

    # inkscape
    try:
        subprocess.run(
            ["inkscape", "--export-type=png", f"--export-filename={png_tmp}",
             "-w", "500", "-h", "500", svg_path],
            check=True, capture_output=True, timeout=30,
        )
        return Image.open(png_tmp)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return None


def create_radio_frame(track, cover_path, logger, output_path=None):
    """Create a branded 1920x1080 frame for the current track."""
    from PIL import Image, ImageDraw, ImageFont

    frame = Image.new("RGB", (STREAM_WIDTH, STREAM_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(frame)

    # Load cover art
    cover_img = None
    if cover_path and os.path.exists(cover_path):
        try:
            if cover_path.endswith(".svg"):
                cover_img = convert_svg_to_image(cover_path)
            else:
                cover_img = Image.open(cover_path)
        except Exception as e:
            logger.warning(f"Could not load cover {cover_path}: {e}")

    if cover_img is None:
        # Fallback gradient
        cover_img = Image.new("RGB", (500, 500), BG_COLOR)
        cdraw = ImageDraw.Draw(cover_img)
        for y in range(500):
            r = int(15 + (240 * y / 500))
            g = int(15 + (180 * y / 500))
            b = int(35 + (65 * y / 500))
            cdraw.line([(0, y), (500, y)], fill=(r, g, b))

    cover_img = cover_img.convert("RGB")
    cover_img = cover_img.resize((500, 500), Image.LANCZOS)

    cover_x = 160
    cover_y = (STREAM_HEIGHT - 500) // 2 - 30
    frame.paste(cover_img, (cover_x, cover_y))

    draw.rectangle(
        [cover_x - 3, cover_y - 3, cover_x + 503, cover_y + 503],
        outline=ACCENT_COLOR, width=2,
    )

    # Fonts
    font_path = find_font("Outfit-SemiBold.ttf")
    font_path_reg = find_font("Outfit-Regular.ttf")
    font_path_med = find_font("Outfit-Medium.ttf")

    if font_path:
        title_font = ImageFont.truetype(font_path, 48)
        type_font = ImageFont.truetype(font_path_reg or font_path, 28)
        brand_font = ImageFont.truetype(font_path_med or font_path, 24)
        age_font = ImageFont.truetype(font_path_reg or font_path, 24)
    else:
        title_font = ImageFont.load_default()
        type_font = title_font
        brand_font = title_font
        age_font = title_font

    text_x = cover_x + 560

    # Title with word-wrap
    title = track.get("title", "Dream Valley")
    if len(title) > 22:
        words = title.split()
        line1 = ""
        line2 = ""
        for w in words:
            if len(line1 + " " + w) < 22:
                line1 = (line1 + " " + w).strip()
            else:
                line2 = (line2 + " " + w).strip()
        draw.text((text_x, cover_y + 80), line1, fill=TEXT_COLOR, font=title_font)
        if line2:
            draw.text((text_x, cover_y + 140), line2, fill=TEXT_COLOR, font=title_font)
        type_y = cover_y + 200 if line2 else cover_y + 150
    else:
        draw.text((text_x, cover_y + 100), title, fill=TEXT_COLOR, font=title_font)
        type_y = cover_y + 170

    type_labels = {
        "story":       "Short Story",
        "long_story":  "Long Story",
        "song":        "Lullaby Song",
        "silly_song":  "Silly Song",
        "funny_short": "Funny Short",
        "poem":        "Poem",
        "lullaby":     "Lullaby",
    }
    type_label = type_labels.get(track.get("content_type"), "Dream Valley")
    draw.text((text_x, type_y), f"{type_label}", fill=ACCENT_COLOR, font=type_font)

    age = track.get("age_group", "")
    if age and age != "?-?":
        draw.text((text_x, type_y + 45), f"Ages {age}",
                  fill=SUBTITLE_COLOR, font=age_font)

    footer_text = "Download Dream Valley Stories now"
    ft_bbox = draw.textbbox((0, 0), footer_text, font=brand_font)
    ft_w = ft_bbox[2] - ft_bbox[0]
    ft_h = ft_bbox[3] - ft_bbox[1]
    # Vertically center text with the App Store badge (54h) at y=STREAM_HEIGHT-68
    text_center_y = STREAM_HEIGHT - 68 + 27
    draw.text(
        (160, text_center_y - ft_h // 2 - 4),
        footer_text,
        fill=FOOTER_COLOR, font=brand_font,
    )
    BADGE_X = 160 + ft_w + 24

    draw.ellipse(
        [STREAM_WIDTH - 130, 35, STREAM_WIDTH - 110, 55],
        fill=LIVE_COLOR,
    )
    draw.text((STREAM_WIDTH - 100, 33), "LIVE", fill=LIVE_COLOR, font=brand_font)

    # App store badges (vertically centered on App Store badge)
    try:
        asb = Image.open("/opt/dreamweaver-backend/radio/assets/app-store-badge.png").convert("RGBA")
        psb = Image.open("/opt/dreamweaver-backend/radio/assets/play-store-badge.png").convert("RGBA")
        asb_y = STREAM_HEIGHT - 68
        asb_center_y = asb_y + asb.height // 2
        psb_y = asb_center_y - psb.height // 2
        frame.paste(asb, (BADGE_X, asb_y), asb)
        frame.paste(psb, (BADGE_X + asb.width + 12, psb_y), psb)
    except Exception:
        pass

    out = output_path or COVER_OUTPUT
    frame.save(out, "PNG")
    return out


def create_transition_frame():
    """Branded transition frame between tracks."""
    from PIL import Image, ImageDraw, ImageFont

    frame = Image.new("RGB", (STREAM_WIDTH, STREAM_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(frame)

    font_path = find_font("Outfit-Medium.ttf")
    if font_path:
        font = ImageFont.truetype(font_path, 42)
        small_font = ImageFont.truetype(font_path, 24)
    else:
        font = ImageFont.load_default()
        small_font = font

    text = "Dream Valley Radio"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((STREAM_WIDTH - tw) // 2, STREAM_HEIGHT // 2 - 30),
              text, fill=ACCENT_COLOR, font=font)

    sub = "dreamvalley.app"
    bbox2 = draw.textbbox((0, 0), sub, font=small_font)
    sw = bbox2[2] - bbox2[0]
    draw.text(((STREAM_WIDTH - sw) // 2, STREAM_HEIGHT // 2 + 30),
              sub, fill=FOOTER_COLOR, font=small_font)

    frame.save(TRANSITION_OUTPUT, "PNG")


# ---------------------------------------------------------------------------
# FFmpeg Streaming
# ---------------------------------------------------------------------------

def build_ffmpeg_command(audio_path, cover_image_path, stream_url):
    return [
        "ffmpeg",
        "-y",
        "-loglevel", "warning",
        # Video: static cover image
        "-thread_queue_size", "1024",
        "-framerate", "5",
        "-loop", "1",
        "-f", "image2",
        "-re",
        "-i", cover_image_path,
        # Audio
        "-i", audio_path,
        # Video encoding — low FPS for static image, save CPU
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "stillimage",
        "-b:v", "1500k",
        "-maxrate", "1500k",
        "-bufsize", "3000k",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-g", "60",
        "-video_size", f"{STREAM_WIDTH}x{STREAM_HEIGHT}",
        # Audio encoding
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        # End when audio finishes
        "-shortest",
        # Output
        "-f", "flv",
        stream_url,
    ]


def build_transition_command(stream_url, duration=2):
    return [
        "ffmpeg",
        "-y",
        "-loglevel", "quiet",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-re",
        "-loop", "1",
        "-f", "image2",
        "-i", TRANSITION_OUTPUT,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "stillimage",
        "-b:v", "1500k",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-video_size", f"{STREAM_WIDTH}x{STREAM_HEIGHT}",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-f", "flv",
        stream_url,
    ]


def probe_duration(audio_path):
    """Return audio duration in seconds via ffprobe, or None."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def build_batch_ffmpeg_command(frames, audio_list, stream_url):
    """Build ffmpeg command using filter_complex concat for per-track cover frames.
    frames: list of (frame_path, duration_seconds) tuples.
    Each image is looped at 5fps for its track duration, then concat'd into
    a continuous video stream. Paired with audio concat demuxer."""
    cmd = ["ffmpeg", "-y", "-loglevel", "warning"]

    # Per-image looped video inputs
    for frame_path, dur in frames:
        cmd += [
            "-thread_queue_size", "512",
            "-re",
            "-loop", "1",
            "-framerate", "5",
            "-t", f"{dur:.3f}",
            "-i", frame_path,
        ]

    # Audio concat input (will be index N = len(frames))
    cmd += [
        "-re",
        "-f", "concat", "-safe", "0", "-i", audio_list,
    ]

    # Concat filter: chain all video inputs into one continuous stream
    n = len(frames)
    concat_inputs = "".join(f"[{i}:v]" for i in range(n))
    filter_str = f"{concat_inputs}concat=n={n}:v=1:a=0[v]"

    cmd += [
        "-filter_complex", filter_str,
        "-map", "[v]",
        "-map", f"{n}:a",
        # Video encoding
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
        "-b:v", "1500k", "-maxrate", "1500k", "-bufsize", "3000k",
        "-pix_fmt", "yuv420p", "-r", "30", "-g", "60",
        "-video_size", f"{STREAM_WIDTH}x{STREAM_HEIGHT}",
        # Audio encoding
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-shortest", "-f", "flv", stream_url,
    ]
    return cmd


def ensure_silence_file():
    """Create a 2-sec silent MP3 once (used as inter-track audio padding)."""
    os.makedirs(BATCH_DIR, exist_ok=True)
    if os.path.exists(SILENCE_AUDIO):
        return
    cmd = [
        "ffmpeg", "-y", "-loglevel", "quiet",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", str(TRANSITION_DURATION),
        "-c:a", "libmp3lame", "-b:a", "128k",
        SILENCE_AUDIO,
    ]
    subprocess.run(cmd, timeout=15, check=False)


def play_batch(tracks, stream_url, logger, dry_run=False):
    """Play a batch of tracks through one ffmpeg process (no inter-track rebuffer).
    Returns the number of tracks successfully streamed."""
    os.makedirs(BATCH_DIR, exist_ok=True)
    ensure_silence_file()

    # Per-track cover frames + duration probe.
    # Frames include transition frames between tracks for visual separation.
    frames = []
    total_duration = 0.0
    for i, track in enumerate(tracks):
        frame_path = f"{BATCH_DIR}/frame_{i}.png"
        create_radio_frame(track, track.get("cover_path"), logger, output_path=frame_path)
        dur = probe_duration(track["audio_path"]) or track.get("duration_seconds")
        if not dur or dur <= 0:
            dur = 60.0
        frames.append((frame_path, dur, track))
        # Insert transition frame between tracks (not after last)
        if i < len(tracks) - 1:
            frames.append((TRANSITION_OUTPUT, TRANSITION_DURATION, None))
        total_duration += dur + (TRANSITION_DURATION if i < len(tracks) - 1 else 0)
        logger.info(f"\u25b6 Queued: {track['title']} "
                    f"({track['content_type']}, {track.get('age_group','?')}) "
                    f"[{dur:.0f}s]")

    # Write concat playlists
    video_list_path = f"{BATCH_DIR}/video.txt"
    audio_list_path = f"{BATCH_DIR}/audio.txt"
    with open(video_list_path, "w") as f:
        f.write("ffconcat version 1.0\n")
        for frame_path, dur, _ in frames:
            f.write(f"file '{frame_path}'\n")
            f.write(f"duration {dur:.3f}\n")
        # Concat demuxer requires last image repeated without duration
        f.write(f"file '{frames[-1][0]}'\n")

    with open(audio_list_path, "w") as f:
        f.write("ffconcat version 1.0\n")
        for _, _, track in frames:
            if track is None:
                # Transition gap - play silence
                f.write(f"file '{SILENCE_AUDIO}'\n")
                continue
            # Escape single quotes per concat demuxer rules
            p = track["audio_path"].replace("'", "'\\''")
            f.write(f"file '{p}'\n")

    if dry_run:
        wait = min(total_duration, 3)
        logger.info(f"  [dry-run] Batch of {len(tracks)} tracks = {total_duration:.0f}s, waiting {wait}s")
        time.sleep(wait)
        return len(tracks)

    # Add generous timeout: total duration + 120s buffer
    timeout_s = int(total_duration + 120)
    frames_for_cmd = [(fp, dur) for fp, dur, _ in frames]
    cmd = build_batch_ffmpeg_command(frames_for_cmd, audio_list_path, stream_url)

    logger.info(f"Streaming batch: {len(tracks)} tracks, {total_duration:.0f}s total")
    try:
        result = subprocess.run(cmd, timeout=timeout_s)
        if result.returncode != 0:
            logger.warning(f"Batch ffmpeg exited with code {result.returncode}")
            return 0
    except subprocess.TimeoutExpired:
        logger.warning(f"Batch exceeded {timeout_s}s timeout")
        return 0
    except Exception as e:
        logger.error(f"Batch playback error: {e}")
        return 0

    return len(tracks)


def play_track(track, stream_url, logger, dry_run=False):
    create_radio_frame(track, track.get("cover_path"), logger)

    logger.info(f"\u25b6 Playing: {track['title']} "
                f"({track['content_type']}, {track.get('age_group', '?')})")

    if dry_run:
        dur = track.get("duration_seconds", 60)
        wait = min(dur, 3)
        logger.info(f"  [dry-run] Would play {dur}s, waiting {wait}s")
        time.sleep(wait)
        return True

    cmd = build_ffmpeg_command(track["audio_path"], COVER_OUTPUT, stream_url)

    try:
        result = subprocess.run(cmd, timeout=900)
        if result.returncode != 0:
            logger.warning(f"FFmpeg exited with code {result.returncode}")
            return False
    except subprocess.TimeoutExpired:
        logger.warning("Track exceeded 15 minute limit, skipping")
        return False
    except Exception as e:
        logger.error(f"Playback error: {e}")
        return False

    return True


def play_transition(stream_url, logger, dry_run=False):
    if dry_run:
        return
    cmd = build_transition_command(stream_url, duration=2)
    try:
        subprocess.run(cmd, timeout=10, capture_output=True)
    except Exception as e:
        logger.warning(f"Transition error (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Dream Valley Radio Controller")
    parser.add_argument("--dry-run", action="store_true",
                        help="Test without streaming (generates covers, logs playlist)")
    parser.add_argument("--test-minutes", type=int, default=0,
                        help="Stream for N minutes then stop (0 = indefinite)")
    parser.add_argument("--list-content", action="store_true",
                        help="List all playable content and exit")
    parser.add_argument("--stream-key", type=str, default=None,
                        help="YouTube stream key (overrides YOUTUBE_STREAM_KEY env)")
    args = parser.parse_args()

    logger = setup_logging(LOG_DIR)
    logger.info("=" * 60)
    logger.info("  Dream Valley Radio starting")
    logger.info("=" * 60)

    if args.list_content:
        tracks = load_all_content(logger)
        type_counts = Counter(t["content_type"] for t in tracks)
        print(f"\nTotal playable tracks: {len(tracks)}\n")
        for ct, count in type_counts.most_common():
            print(f"  {ct}: {count}")
            for t in sorted([x for x in tracks if x["content_type"] == ct],
                            key=lambda x: x["title"]):
                has_cover = "\u2713" if t["cover_path"] else "\u2717"
                print(f"    [{has_cover}] {t['title']} ({t['age_group']})")
        return

    stream_key = args.stream_key or os.environ.get("YOUTUBE_STREAM_KEY", "")
    if not stream_key and not args.dry_run:
        logger.error("No stream key! Set YOUTUBE_STREAM_KEY env or use --stream-key")
        logger.info("Use --dry-run to test without streaming")
        sys.exit(1)

    stream_url = f"{YOUTUBE_RTMP}/{stream_key}" if stream_key else ""

    try:
        create_transition_frame()
        logger.info("Transition frame created")
    except Exception as e:
        logger.warning(f"Could not create transition frame: {e}")

    scheduler = RadioScheduler(logger)
    if not scheduler.content:
        logger.error("No playable content found!")
        sys.exit(1)

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    start_time = time.time()
    time_limit = args.test_minutes * 60 if args.test_minutes > 0 else 0

    play_count = 0
    error_count = 0
    MAX_CONSECUTIVE_ERRORS = 5

    logger.info(f"Mode: {'dry-run' if args.dry_run else 'LIVE'}")
    if time_limit:
        logger.info(f"Will stop after {args.test_minutes} minutes")
    logger.info("Starting playback loop...")

    while running:
        if time_limit and (time.time() - start_time) > time_limit:
            logger.info(f"Time limit ({args.test_minutes}m) reached, stopping")
            break

        # Build a batch of tracks and stream them through one ffmpeg session
        batch = [scheduler.next_track() for _ in range(BATCH_SIZE)]

        played = play_batch(batch, stream_url, logger, dry_run=args.dry_run)

        if played > 0:
            for t in batch[:played]:
                scheduler.mark_played(t)
            play_count += played
            error_count = 0
        else:
            error_count += 1
            if error_count >= MAX_CONSECUTIVE_ERRORS:
                logger.error(f"{MAX_CONSECUTIVE_ERRORS} consecutive errors, "
                             "pausing 30s before retry")
                time.sleep(30)
                error_count = 0

        # Refresh content from API every batch
        scheduler.refresh_content()

        if play_count > 0 and play_count % 25 == 0:
            elapsed = (time.time() - start_time) / 60
            logger.info(f"Stats: {play_count} tracks in {elapsed:.0f}m, "
                        f"{len(scheduler.played_set)}/{len(scheduler.content)} "
                        "unique played")

    logger.info(f"Radio stopped. Played {play_count} tracks total.")


if __name__ == "__main__":
    main()
