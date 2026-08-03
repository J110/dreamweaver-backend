# Daily Content Recovery Design

## Goal

Restore the missing 2026-08-03 Hindi funny short and the custom cover for English silly song `why_does_broccoli_stare_2_5`, then close the pipeline and deploy-guard gaps that allowed both defects to remain published.

## Production repair

Every production mutation is wrapped by `deploy_guard.py snapshot` and `deploy_guard.py verify`. The Hindi repair runs only the `funny_short` Hindi pipeline type, preserving every existing item. The English repair regenerates a custom cover from the existing silly-song record, persists canonical `cover_file` and `cover` fields, reloads the backend, and confirms the user-facing URL is reachable.

The repair may not change existing content IDs, text, audio, titles, creation timestamps, or unrelated records.

## Hindi funny-short reliability

The standalone Hindi funny-short generator retains its bounded five-attempt budget. After a candidate fails validation, the next request receives the exact validator failures and the rejected candidate so it can correct length, required standalone laughter, and missing `text_deva` fields instead of producing another uninformed sample.

The existing narrow Devanagari repair remains available for Devanagari-only failures. Mixed failures use the validator-feedback retry path. If all five attempts still fail, the generator exits nonzero and the Hindi pipeline reports a partial run without publishing an incomplete record.

## Deploy-guard contract

Deploy guard protects the complete pre-deploy baseline. Snapshot state records each existing content ID plus its canonical audio and cover metadata. Post-deploy verification compares the same IDs and required asset paths, restores missing source records or assets from transactional and persistent stores, reloads affected services, and verifies the live state again.

Recovery may recreate an asset from the existing record when no stored copy remains, but it may not generate replacement content, change an ID, or silently accept a placeholder. New content is checked separately for completeness; a missing audio or cover URL is a blocker rather than an omitted check.

The English pipeline must invoke the full verification and recovery path. The lightweight in-process diff is not sufficient because it neither checks live URLs nor performs recovery.

## Canonical cover handling

Silly-song state prefers the persisted `cover` URL and falls back to a path reconstructed from `cover_file`. Snapshot entries explicitly track `has_cover`. Losing either cover metadata or a previously reachable cover is a degradation.

New-item and full-live audits report absent cover URLs as failures. A referenced but missing cover enters the existing recovery chain; successful recovery is accepted only after a fresh HTTP reachability check.

## Testing

Regression tests cover mixed-error Hindi candidate repair, exhaustion after bounded retries, canonical silly-song cover extraction, existing-cover degradation detection, absent new-item cover rejection, and invocation of full guard verification by the English pipeline. Production verification confirms the new Hindi funny short, the repaired English custom cover, preserved baseline IDs, and a clean deploy-guard verdict.
