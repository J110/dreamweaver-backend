# Silly Song Duration and Publication Recovery Design

## Goal

Generate silly songs toward a preferred duration of 60–90 seconds, accept safe outputs from 50–100 seconds, prevent incomplete drafts from appearing in public catalogs, and persist accepted assets before publication.

## Duration Contract

The generation prompt and retry guidance will state that the desired output duration is 60–90 seconds. Runtime validation will use separate acceptance constants and accept audio from 50–100 seconds inclusive.

An output between 50–59.9 or 90.1–100 seconds is publishable without regeneration. An output below 50 or above 100 seconds is rejected and may use the existing bounded retry.

## Publication Contract

A silly song is publicly eligible only when its source JSON contains both `audio_file` and `cover_file`. Incomplete JSON remains preserved on disk for diagnosis or later recovery but is excluded from:

- the generic content collection built by `LocalStore`;
- the `/api/v1/silly-songs` list endpoint.

The single-item endpoint may continue to expose an incomplete item by exact ID for administrative diagnosis; public browsing and playlists must not include it.

## Backup Contract

After audio passes the 50–100-second acceptance gate, the generator copies it immediately to `/opt/audio-store/silly-songs/`. After cover generation succeeds, the generator copies it immediately to `/opt/cover-store/silly-songs/`.

Catalog insertion occurs only after both backup copies succeed. A backup failure marks the item as failed and prevents publication, preserving the backend working copy and source JSON for recovery.

## Deploy Guard Compatibility

For a generic content item with `subtype == "silly_song"`, deploy guard derives:

- audio from `audio_variants`, then legacy `audio_file`;
- cover from `cover`, then legacy `cover_file`.

This removes false positives for legacy records while retaining real completeness checks. Incomplete drafts excluded by the publication contract do not count as live missing assets.

## Existing Production Records

The 37 legacy cover warnings are schema false positives: their `cover_file` values and persistent cover assets exist. Five audio warnings and four cover warnings belong to incomplete generation drafts whose original jobs failed before accepted assets were persisted.

Regenerated recovery outputs are archived and their original JSON restored. No regenerated asset will be used to clear these warnings; the incomplete drafts will remain preserved but unpublished.

## Testing

Tests will prove:

- generation guidance demands 60–90 seconds;
- runtime acceptance includes 50 and 100 seconds and rejects values outside that range;
- complete silly songs remain public while incomplete records are excluded;
- deploy guard recognizes legacy `cover_file`;
- accepted audio and covers are copied to their persistent stores before catalog insertion;
- backup failure blocks publication.

## Rollout

Deploy the code, hot-reload the backend, and run deploy guard against a fresh pre-deploy snapshot. Success requires zero incomplete silly songs in public catalogs, all referenced assets reachable, and no false missing-cover warnings from legacy schema.
