# Social Media Clips — Pipeline Guidelines

Reference for `scripts/generate_clips.py` and pipeline step `clips`.

## Overview

Generates 60-second vertical (1080x1920, 9:16) video clips from story covers + narration audio for YouTube Shorts, Instagram Reels, and TikTok.

## Pipeline Execution Order

```
... → COVERS → SYNC → CLIPS → PUBLISH → DEPLOY
```

**CRITICAL**: Clips runs AFTER sync. The sync step copies audio/covers from the backend to `dreamweaver-web/public/`. Clips reads files from the frontend's `public/` directory, so they must exist there first.

## Daily Output Target

**6 clips per run**: 3 from today's new content + 3 from back-catalog (oldest unclipped first).

| Slot | Source | Voice Selection |
|------|--------|-----------------|
| 1 | New story (today) | Daily coin-flip: female_1 or asmr |
| 2 | New poem (today) | Daily coin-flip: asmr or female_1 |
| 3 | New lullaby (today) | First available variant |
| 4 | Back-catalog story | Same as slot 1 |
| 5 | Back-catalog poem | Same as slot 2 |
| 6 | Back-catalog lullaby | Same as slot 3 |

Hard cap: `MAX_CLIPS_PER_RUN = 6` (enforced in code).

## Resource Constraints (e2-small: 2 vCPU, 2 GB RAM)

| Setting | Value | Rationale |
|---------|-------|-----------|
| `FFMPEG_THREADS` | 1 | Prevents CPU starvation of backend Docker container |
| `FFMPEG_NICE` | 10 | Lower priority so API stays responsive |
| `FFMPEG_TIMEOUT` | 300s (5 min) | Ken Burns zoompan + encoding per clip |
| `FFMPEG_COMPOSITE_TIMEOUT` | 420s (7 min) | Composite has drawtext filters, heavier |
| Pipeline-level timeout | 1800s (30 min) | Hard kill for the entire clips step |

### Expected Performance

- Ken Burns step: ~90-150s per clip (zoompan is CPU-heavy)
- Audio trim: ~5s per clip
- Composite: ~60-120s per clip
- **Total per clip**: ~3-5 minutes
- **Total for 6 clips**: ~20-30 minutes

If clips routinely exceed 25 minutes, consider reducing `MAX_CLIPS_PER_RUN` to 4.

## Video Spec

| Property | Value |
|----------|-------|
| Resolution | 1080x1920 (9:16 portrait) |
| Codec | H.264 High profile, level 4.0 |
| Pixel format | yuv420p |
| Codec tag | avc1 (QuickTime compatible) |
| FPS | 30 |
| Duration | 60 seconds |
| Preset | fast (balance of speed vs quality) |
| CRF | 23 (visually good, ~3 MB output) |
| Audio | AAC 192 kbps, 44100 Hz, stereo |
| Container | MP4 with faststart (moov atom at front) |

### Layout (top to bottom)

```
+------------------+
|   80px padding   |
| +--------------+ |
| | 1080x1080    | |
| | Cover image  | |
| | (Ken Burns)  | |
| +--------------+ |
|    Mood tag       |  y=1200, colored
|    Title (1-3 ln) |  y=1280+, cream
|    Character info  |  y=title+40, grey
|    Age · Type      |  y=char+80, grey
|                   |
|  dreamvalley.app  |  y=1780, grey
+------------------+
```

## File Naming

- **Video**: `{short_id}_{voice}_clip.mp4`
- **Metadata**: `{short_id}_{voice}_clip.json`
- `short_id` = first 8 characters of story ID

### Metadata Schema

```json
{
  "storyId": "7fe248e1",
  "fullStoryId": "7fe248e1-f1ad-44a0-9c4e-95924d27fb5e",
  "voice": "asmr",
  "title": "The Sleepy Cloud",
  "mood": "calm",
  "ageGroup": "2-5",
  "contentType": "story",
  "generatedAt": "2026-03-13T03:12:07.622248Z",
  "duration": 60,
  "fileSize": 3392355,
  "filename": "7fe248e1_asmr_clip.mp4",
  "posted": { "youtube": null, "instagram": null, "tiktok": null },
  "captions": { "youtube": "...", "instagram": "...", "tiktok": "..." }
}
```

**IMPORTANT**: `storyId` must match the short ID used in the filename. The download API constructs the file path as `{storyId}_{voice}_clip.mp4`. A mismatch causes 404s and corrupted downloads.

## Failure Handling

- Clips step is **non-fatal**: pipeline continues even if all clips fail.
- Individual clip failures (timeout, missing audio/cover) skip that clip and continue to the next.
- ffmpeg timeout kills the process cleanly via `subprocess.TimeoutExpired`.

## Troubleshooting

### Clips not generated for new content
- **Cause**: Clips ran before sync (fixed March 2026 — clips now runs after sync).
- **Verify**: Check that audio exists in `dreamweaver-web/public/audio/pre-gen/` and covers in `dreamweaver-web/public/covers/` before clips step runs.

### ffmpeg hangs / high CPU
- Each ffmpeg call has a timeout (300-420s). If hit, the process is killed and the clip is skipped.
- `FFMPEG_THREADS=1` prevents CPU saturation.
- `nice 10` keeps the backend API responsive during clip generation.

### Downloaded clips won't play
- **Cause**: `storyId` in metadata didn't match filename. Dashboard fetched using full ID, got 404, saved error JSON as `.mp4`.
- **Fix**: `storyId` in metadata now uses the short 8-char ID matching the filename.

### Fewer than 6 clips
- New content clips: requires today's items to have audio variants AND covers in the frontend directory.
- Back-catalog clips: skips stories that already have a clip in today's assigned voice. Once all stories are clipped, back-catalog returns 0.

## Commands

```bash
# Daily (called by pipeline)
python3 scripts/generate_clips.py

# Single story
python3 scripts/generate_clips.py --story-id gen-910ff4401b32

# Dry run (preview plan)
python3 scripts/generate_clips.py --dry-run

# Batch all unclipped
python3 scripts/generate_clips.py --batch --limit 10

# Force regenerate
python3 scripts/generate_clips.py --force
```
