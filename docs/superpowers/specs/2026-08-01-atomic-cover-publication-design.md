# Atomic Cover Publication Design

## Goal

Prevent generated content from becoming visible without a valid cover and ensure deployments cannot remove existing cover assets.

## Root Cause

Hindi silly-song and poem generators currently continue after `_flux_cover()` returns `None`. They write a content record containing `/covers/default.svg` plus a `cover_file` name for a file that was never created. The JSON backup then preserves the incomplete record without a matching cover asset.

Deploy Guard detects the broken URL only after publication. Its recovery path recognizes only some flat cover-store naming conventions, does not restore poem covers from the persistent subtype directories, and invokes a nested `gcloud compute ssh` command that cannot authenticate from the production VM. Content generated after the pre-deploy snapshot is also absent from the before/after comparison until the new-item URL check runs.

## Design

### Fail-closed generation

Silly-song and poem generation must treat a missing cover as a failed generation. The generator must not write the per-content JSON, aggregate JSON, or any other discoverable content record unless cover bytes were generated and saved successfully.

Audio files produced before the cover failure may remain as unreferenced artifacts for operational diagnosis. They must not make the item visible because no content record will be published.

### Durable cover storage

Every successfully generated cover must be written to the persistent `/opt/cover-store` location used by nginx before the content record is published. The subtype URL and root alias referenced by the record must both resolve to files in that persistent store.

The application repository's `public` directory remains a compatibility duplicate, not the source of truth. Web builds and `.next` swaps therefore cannot remove production covers.

### Atomic publication gate

Immediately before writing a content record, the generator validates that every required production media path exists and is non-empty. If validation fails, it raises an error and leaves the content unpublished.

The content record's `cover` and `cover_file` fields must point only to validated files. `/covers/default.svg` is not valid for newly generated silly songs or poems.

### Backup and recovery

Deploy Guard must resolve recovery sources using the same persistent directory layout as the generators:

- Silly-song covers: `/opt/cover-store/silly-songs/<cover_file>`
- Poem covers: `/opt/cover-store/poems/<cover_file>`
- Root aliases: `/opt/cover-store/<content-id>.webp`

Recovery executed on the production VM copies locally from these stores and does not invoke nested `gcloud`. JSON backup remains additive, but a content record is not considered safely backed up unless its required media exists.

### Deploy verification

Deploy Guard checks every item added after the pre-deploy snapshot, including content created while deployment is running. A newly added item with a missing cover or audio URL hard-fails verification and is not merged into the golden baseline.

Historical alternate audio candidates remain outside this cover fix. The guard must evaluate canonical user-facing media separately from obsolete alternative URLs so unrelated warnings do not hide a new cover failure.

## Error Handling

- Cover provider failure: abort the item before publication and emit the item type, age group, and generation stage.
- Cover save failure: abort before publication and retain the original exception.
- Missing production path after save: abort before publication.
- Missing cover detected during deployment: restore locally from the subtype store; fail deployment if no stored file exists.
- New incomplete content discovered during verification: fail verification and do not update the golden baseline with that item.

## Tests

- A silly song is not published when cover generation returns `None`.
- A poem is not published when cover generation returns `None`.
- Successful generation validates persistent subtype and root-alias cover files before publication.
- Deploy Guard finds silly-song and poem covers in persistent subtype stores.
- Deploy Guard recovery runs locally on production and does not require nested `gcloud` authentication.
- Newly added content with a missing cover blocks verification and is excluded from golden-baseline updates.

## Success Criteria

- No newly generated silly song or poem is visible with a missing or default cover.
- Existing covers survive web deployments because their source of truth is outside the repository build output.
- Deploy Guard can restore both silly-song and poem covers from local persistent backups.
- Deploy Guard exits non-zero before approving any deployment that introduces a missing canonical cover.
