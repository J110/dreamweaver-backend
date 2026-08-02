# Transactional Deploy Guard Design

## Goal

Every deployment must finish with zero user-facing content defects. Missing content, missing audio, missing covers, generic placeholders, broken playlist slots, stale API data, and incomplete tier/language surfaces are deployment blockers. The known YouTube radio broadcast outage is the only exemption.

## Success contract

Deploy Guard succeeds only when all of the following are true:

- Every complete, publishable per-content record appears in the admin-bypass live catalog.
- Every live content record has playable audio and a custom, reachable cover.
- No live cover uses a known placeholder path, filename, content hash, or placeholder metadata marker.
- Every referenced audio and cover URL returns HTTP 200 or 206 from the user-facing origin.
- English and Hindi free and premium bedtime and nap playlists contain the required slots, and every returned item is playable with a custom cover.
- Live content IDs and required metadata match the pre-deploy snapshot and the publishable-content manifest, except for intentional additions.
- All source invariants and frontend runtime checks pass.

The final report must contain only unresolved current failures. It must not classify defects as pre-existing, informational, tolerated, or outside the deployment. Radio health is reported separately and does not affect the content verdict.

## Publishable-content manifest

The golden baseline is replaced as the authority for catalog membership by a manifest rebuilt from per-content source-of-truth JSON. A record is publishable only when it is not explicitly marked draft, incomplete, quarantined, or deleted and it satisfies its content-type completeness schema.

The manifest records each publishable ID, language, content type, required tier surfaces, canonical audio candidates, canonical cover path, custom-cover fingerprint, and source record path. Golden data remains a recovery source and historical integrity record, but stale golden IDs that are not publishable are not reported as missing app content.

## Transaction flow

### Preflight

Before deployment, Deploy Guard builds the publishable manifest, audits every user-facing surface, and runs the recovery cascade until the audit reaches zero defects. A transactional snapshot is captured only after preflight is clean. The snapshot includes per-content JSON, derived catalogs, URL and hash manifests, persistent-store asset locations, live content counts, current backend and frontend release identifiers, and the configured rollback hook.

Deployment cannot begin if preflight remains unhealthy, the snapshot is incomplete, or no production rollback hook is configured.

### Postflight

After deployment, Deploy Guard rebuilds the manifest and repeats the complete live audit. It groups failures by stable reason code, runs the matching recovery adapter, reloads affected services, and audits again. Recovery continues for bounded rounds while each round makes measurable progress.

Success requires a final zero-defect audit. Recovery logs remain available for diagnostics but resolved defects do not appear as warnings in the final verdict.

### Rollback

If bounded recovery cannot reach zero defects, Deploy Guard invokes the mandatory deployment rollback hook, restores the transactional content and asset snapshot, reloads the backend, and runs the same complete audit. A successful rollback returns a failed-deployment verdict with the app confirmed healthy. If rollback verification also fails, Deploy Guard emits a critical incident verdict containing only the remaining current defects and exits nonzero.

## Recovery cascade

Each defect is assigned one reason code and handled by a deterministic adapter:

1. `STALE_LIVE_STATE`: reload the backend and clear relevant playlist caches.
2. `WRONG_METADATA_PATH`: normalize audio, cover, and variant URLs to canonical serving paths and persist them through per-content helpers.
3. `MISROUTED_ASSET`: locate the matching file by ID, filename, and hash across persistent stores, web/backend public trees, seed output, JSON store, and the snapshot; copy it to the canonical persistent path.
4. `MISSING_SOURCE_RECORD`: restore per-content JSON from the transactional snapshot, JSON store, golden history, or the last known-good repository revision.
5. `MISSING_CUSTOM_COVER` or `PLACEHOLDER_COVER`: restore the last known custom cover by hash; otherwise regenerate from the existing record's `cover_context` without changing content metadata or timestamps.
6. `MISSING_AUDIO`: restore matching audio from persistent, public, seed, snapshot, or repository stores; otherwise re-render from the existing text and voice/provider metadata while preserving the content ID.
7. `MISSING_LIVE_ITEM` or `PLAYLIST_SLOT_MISSING`: restore the source record and assets, rebuild derived catalogs, reload, and re-evaluate the affected tier/language surface.
8. `UNREACHABLE_ORIGIN`: retry bounded network checks; if the origin remains unavailable, invoke rollback because health cannot be proven.

An adapter may not substitute a generic placeholder, silently drop or quarantine published content, change IDs, regenerate story text, or alter creation timestamps.

## Placeholder detection

Placeholder detection uses both metadata and asset content. The blocked set includes `/covers/default.svg`, known placeholder filenames and directories, generator placeholder markers, and hashes of every approved generic placeholder asset. A small file is not automatically a placeholder, and a custom asset is accepted only when its path resolves and its hash is absent from the blocked set.

The placeholder fingerprint registry is versioned in the repository and validated during preflight. New placeholder assets must be added to the registry before use in generators.

## Architecture

`deploy_guard.py` remains the command-line entry point and orchestrates focused modules:

- `deploy_guard_manifest.py` builds publishable and live manifests.
- `deploy_guard_audit.py` compares manifests and validates user-facing surfaces.
- `deploy_guard_recovery.py` classifies defects and runs recovery adapters.
- `deploy_guard_transaction.py` captures/restores snapshots and invokes the configured rollback hook.
- `deploy_guard_models.py` defines defect reason codes, audit results, recovery results, and final verdicts.

The existing `snapshot`, `verify`, `audit`, `recover`, and `invariants` commands remain compatible. Production deployment uses a new `transaction` command or equivalent wrapper that enforces preflight, deployment, postflight, recovery, and rollback as one operation.

## Observability

Each run writes a machine-readable report containing the deployment identifier, snapshot identifier, audit counts, defects by reason code, recovery attempts, recovered IDs, rollback status, and final zero-defect result. Human output is concise: resolved defects are summarized as recovered; only unresolved current defects appear under blockers.

## Testing

Tests cover manifest publishability, full ID-set comparison, placeholder path and hash detection, reason classification, each recovery adapter, bounded-progress recovery, rollback invocation, rollback verification, radio exemption, and the rule that no non-radio defect can be downgraded or ignored. Integration tests use temporary per-content and asset stores plus a local HTTP server to exercise missing files, wrong paths, stale reloads, placeholders, regeneration success/failure, and rollback. A production dry-run audit must show zero user-facing content defects before enabling transactional mode.
