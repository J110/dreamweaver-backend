# Pipeline Cover Failure Repair Design

## Goal

Restore the three broken covers published on 2026-08-02 and prevent English and Hindi pipeline notifications from reporting failed covers as successful.

## Production repair

Capture a deploy-guard snapshot before any mutation. Generate covers for the two Hindi records from their existing per-content JSON with `generate_cover_experimental.py`, writing SVG assets to `/opt/cover-store` and updating their per-content `cover` fields. For the English lullaby, retain the generated placeholder and change its per-content `cover` field to the existing `/covers/lullabies/{id}_cover.svg` asset. Reload the backend, verify every affected URL returns HTTP 200, then run deploy-guard verification.

No content text, audio, IDs, titles, descriptions, or creation timestamps will change.

## English pipeline correction

The lullaby integration will choose its final cover only after the FLUX command returns. A successful FLUX render uses `/covers/{id}.svg`; a failed render uses the placeholder path `/covers/lullabies/{id}_cover.svg`. The selected path is written to both the in-memory snapshot entry and the per-content source-of-truth record.

The pipeline state will record the lullaby ID in the generated or failed cover collection so the final notification includes the result.

## Hindi pipeline correction

Each successful generator result will retain the returned entry's `cover` value. `_build_state` will classify a cover as failed when it is empty or `/covers/default.svg`; only non-default cover paths will be classified as generated. A cover failure will add a visible warning while preserving the content-generation success because valid audio content remains publishable.

## Error handling

Cover generation failures remain non-fatal for content publication. The fallback asset must resolve before an English lullaby is published, and Hindi default-cover publication must be explicitly reflected as a partial pipeline result. Production repair stops before reload if either generated SVG is absent or any target record still has the wrong cover path.

## Tests

Add regression tests proving that an English lullaby cover timeout selects and persists the subtype placeholder path and is counted as a failed cover. Add Hindi state tests proving default or empty covers are failed while custom covers are generated. Run the focused tests first, then the relevant pipeline regression tests, followed by live URL and deploy-guard verification.
