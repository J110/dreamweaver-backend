# Hindi Daily Cover Repair

## Scope

Repair the five failed custom covers from the 2026-08-01 Hindi pipeline run without regenerating content, audio, IDs, or metadata.

## Production flow

1. Run `deploy_guard.py snapshot` before changing production assets.
2. Regenerate covers only for the five affected IDs, using each record's existing `cover_context` and the established production cover generator.
3. Confirm each JSON record references a non-default cover and each referenced cover file exists.
4. Reload the production content store through the admin reload endpoint.
5. Run `deploy_guard.py verify`; the known YouTube radio issue is the only accepted pre-existing exception.

## Home-page success criteria

The 2026-08-01 Hindi short story, long story, and lullaby must have real covers and complete audio metadata in the authenticated API response. Because Hindi Home sorts complete, unlistened content by `created_at` descending within each content row, those three items must appear first in Kahaniyan, Lambi Kahaniyan, and Loriyaan respectively.

The poem and silly song remain outside Hindi Home, and the funny short remains on Before Bed.

## Failure handling

Stop before reload if any cover generation fails, any output file is missing, or any JSON record still points to `/covers/default.svg`. Do not rerun content generation and do not alter unrelated production records.
