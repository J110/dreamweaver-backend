# Transactional Deploy Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make production deployments fail closed unless every publishable item is present, playable, and uses a custom cover, with automatic recovery and rollback for every non-radio defect.

**Architecture:** Split manifest building, auditing, recovery, and transaction state into focused modules while preserving `deploy_guard.py` as the compatible CLI. A production transaction performs clean preflight, snapshot, deploy, postflight recovery, rollback on unresolved defects, and final verification. The YouTube radio broadcast issue is recorded separately and is the only exemption.

**Tech Stack:** Python 3.11, dataclasses, pathlib, httpx, pytest, FastAPI admin reload, existing content generators and persistent stores.

## Global Constraints

- Every complete, publishable per-content record must appear in the admin-bypass live catalog.
- Every live item must have playable audio and a custom reachable cover.
- Generic placeholder paths, filenames, metadata markers, and hashes are blockers.
- Resolved defects do not appear as warnings in the final verdict.
- No recovery adapter may change content IDs, story text, titles, descriptions, or creation timestamps.
- The YouTube radio broadcast outage is the sole non-blocking exemption.
- Production transactions require a rollback hook and a verified clean preflight snapshot.
- Preserve existing uncommitted changes in `scripts/deploy_guard.py`; integrate rather than overwrite them.

---

### Task 1: Defect models and placeholder registry

**Files:**
- Create: `scripts/deploy_guard_models.py`
- Create: `data/deploy_placeholder_hashes.json`
- Create: `scripts/test_deploy_guard_transactional.py`

**Interfaces:**
- Produces: `ReasonCode`, `Defect`, `AuditResult`, `RecoveryResult`, `FinalVerdict`, and `is_blocking(defect)`.
- Consumes: no earlier task interfaces.

- [ ] **Step 1: Write failing model and exemption tests**

```python
def test_only_radio_broadcast_is_non_blocking():
    radio = Defect(ReasonCode.RADIO_BROADCAST_OFFLINE, "radio", {})
    missing = Defect(ReasonCode.MISSING_AUDIO, "story-1", {})
    assert is_blocking(radio) is False
    assert is_blocking(missing) is True


def test_audit_result_exposes_only_current_blockers():
    result = AuditResult(defects=[
        Defect(ReasonCode.MISSING_AUDIO, "story-1", {}),
        Defect(ReasonCode.RADIO_BROADCAST_OFFLINE, "radio", {}),
    ])
    assert [d.item_id for d in result.blockers] == ["story-1"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q scripts/test_deploy_guard_transactional.py -k 'radio or audit_result'`

Expected: import failure because `deploy_guard_models.py` does not exist.

- [ ] **Step 3: Implement the typed models**

```python
class ReasonCode(str, Enum):
    INVALID_SOURCE_RECORD = "INVALID_SOURCE_RECORD"
    MISSING_LIVE_ITEM = "MISSING_LIVE_ITEM"
    MISSING_AUDIO = "MISSING_AUDIO"
    MISSING_CUSTOM_COVER = "MISSING_CUSTOM_COVER"
    PLACEHOLDER_COVER = "PLACEHOLDER_COVER"
    WRONG_METADATA_PATH = "WRONG_METADATA_PATH"
    MISROUTED_ASSET = "MISROUTED_ASSET"
    MISSING_SOURCE_RECORD = "MISSING_SOURCE_RECORD"
    PLAYLIST_SLOT_MISSING = "PLAYLIST_SLOT_MISSING"
    STALE_LIVE_STATE = "STALE_LIVE_STATE"
    UNREACHABLE_ORIGIN = "UNREACHABLE_ORIGIN"
    RADIO_BROADCAST_OFFLINE = "RADIO_BROADCAST_OFFLINE"


@dataclass(frozen=True)
class Defect:
    reason: ReasonCode
    item_id: str
    details: dict[str, Any]


@dataclass
class AuditResult:
    defects: list[Defect] = field(default_factory=list)

    @property
    def blockers(self) -> list[Defect]:
        return [d for d in self.defects if is_blocking(d)]


def is_blocking(defect: Defect) -> bool:
    return defect.reason is not ReasonCode.RADIO_BROADCAST_OFFLINE
```

Add serializable recovery and verdict dataclasses with `to_dict()` methods and no severity downgrade field.

- [ ] **Step 4: Add the initial placeholder registry**

```json
{
  "paths": ["/covers/default.svg"],
  "filename_patterns": ["default.svg", "placeholder.svg", "placeholder.webp"],
  "sha256": []
}
```

- [ ] **Step 5: Run tests and verify GREEN**

Run: `pytest -q scripts/test_deploy_guard_transactional.py -k 'radio or audit_result'`

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/deploy_guard_models.py data/deploy_placeholder_hashes.json scripts/test_deploy_guard_transactional.py
git commit -m "feat: define strict deploy guard defects"
```

---

### Task 2: Publishable-content manifest

**Files:**
- Create: `scripts/deploy_guard_manifest.py`
- Modify: `scripts/test_deploy_guard_transactional.py`

**Interfaces:**
- Consumes: `ReasonCode`, `Defect`.
- Produces: `ManifestItem`, `ManifestResult`, `is_publishable(record)`, `build_publishable_manifest(data_dir)`.

- [ ] **Step 1: Write failing publishability and membership tests**

```python
def test_manifest_excludes_only_explicit_non_publishable_records(tmp_path):
    write_record(tmp_path, "stories", {"id": "live", "type": "story", "title": "Live", "text": "Text"})
    write_record(tmp_path, "stories", {"id": "draft", "type": "story", "title": "Draft", "status": "draft"})
    result = build_publishable_manifest(tmp_path)
    assert set(result.items) == {"live"}


def test_manifest_flags_incomplete_unmarked_record(tmp_path):
    write_record(tmp_path, "stories", {"id": "broken", "type": "story"})
    result = build_publishable_manifest(tmp_path)
    assert result.defects[0].reason is ReasonCode.INVALID_SOURCE_RECORD
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q scripts/test_deploy_guard_transactional.py -k manifest`

Expected: import failure because manifest functions do not exist.

- [ ] **Step 3: Implement manifest construction**

```python
NON_PUBLISHABLE = {"draft", "incomplete", "quarantined", "deleted"}
REQUIRED_FIELDS = {
    "story": {"id", "type", "title", "text"},
    "long_story": {"id", "type", "title", "text"},
    "poem": {"id", "type", "title", "text"},
    "song": {"id", "type", "title"},
}


def is_publishable(record: dict) -> bool:
    state = str(record.get("status") or record.get("publication_status") or "").lower()
    return not record.get("is_draft") and state not in NON_PUBLISHABLE
```

Scan only the canonical per-content directories from `_per_content_io`, preserve each source path, compute canonical audio candidates through `audio_resolver`, and retain cover path, language, type, subtype, tiers, and timestamps. Return invalid-source defects instead of silently skipping malformed unmarked records.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest -q scripts/test_deploy_guard_transactional.py -k manifest`

Expected: manifest tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy_guard_manifest.py scripts/test_deploy_guard_transactional.py
git commit -m "feat: build publishable content manifest"
```

---

### Task 3: Strict user-facing audit

**Files:**
- Create: `scripts/deploy_guard_audit.py`
- Modify: `scripts/test_deploy_guard_transactional.py`

**Interfaces:**
- Consumes: `ManifestResult`, live API records, placeholder registry, HTTP client.
- Produces: `audit_catalog(manifest, live_items, client, frontend_origin) -> AuditResult` and `audit_playlists(...) -> AuditResult`.

- [ ] **Step 1: Write failing catalog, URL, and placeholder tests**

```python
def test_audit_flags_missing_publishable_id():
    result = audit_catalog(manifest_with("story-1"), [], FakeHttp({}), "https://app")
    assert result.blockers[0].reason is ReasonCode.MISSING_LIVE_ITEM


def test_audit_rejects_placeholder_by_path_and_hash(tmp_path):
    registry = PlaceholderRegistry(paths={"/covers/default.svg"}, sha256={sha256(b"generic")})
    live = live_item("story-1", cover="/covers/custom.svg", audio_url="/audio/story.mp3")
    http = FakeHttp({"/covers/custom.svg": (200, b"generic"), "/audio/story.mp3": (200, b"audio")})
    result = audit_catalog(manifest_with("story-1"), [live], http, "https://app", registry)
    assert result.blockers[0].reason is ReasonCode.PLACEHOLDER_COVER


def test_audit_checks_every_audio_candidate():
    live = live_item("story-1", audio_variants=[{"url": "/audio/broken.mp3"}])
    result = audit_catalog(manifest_with("story-1"), [live], FakeHttp({"/audio/broken.mp3": 404}), "https://app")
    assert any(d.reason is ReasonCode.MISSING_AUDIO for d in result.blockers)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q scripts/test_deploy_guard_transactional.py -k audit_`

Expected: audit imports fail.

- [ ] **Step 3: Implement strict catalog auditing**

Compare exact manifest and live ID sets, inspect all audio candidates, require one canonical custom cover, HEAD every user-facing URL, and GET cover bytes only when hash verification is needed. Classify missing files at alternate known paths as `MISROUTED_ASSET`, conflicting explicit URLs as `WRONG_METADATA_PATH`, and origin failures as `UNREACHABLE_ORIGIN`.

- [ ] **Step 4: Implement playlist auditing**

Audit EN/HI free and premium bedtime and nap responses. Require expected slot counts, unique IDs, playable audio, custom covers, and membership in the publishable manifest. Emit `PLAYLIST_SLOT_MISSING` for absent or invalid slots.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `pytest -q scripts/test_deploy_guard_transactional.py -k 'audit_ or playlist'`

Expected: strict audit tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/deploy_guard_audit.py scripts/test_deploy_guard_transactional.py
git commit -m "feat: audit every user-facing content surface"
```

---

### Task 4: Reason-aware recovery cascade

**Files:**
- Create: `scripts/deploy_guard_recovery.py`
- Modify: `scripts/test_deploy_guard_transactional.py`

**Interfaces:**
- Consumes: `Defect`, `ManifestItem`, snapshot paths, store roots, reload callback.
- Produces: `RecoveryContext`, `RecoveryEngine.recover(defects) -> list[RecoveryResult]`.

- [ ] **Step 1: Write failing deterministic recovery tests**

```python
def test_recovery_copies_misrouted_asset_to_canonical_store(tmp_path):
    ctx = recovery_context(tmp_path)
    source = ctx.seed_root / "poems_hi" / "poem.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    defect = Defect(ReasonCode.MISROUTED_ASSET, "poem", {"filename": "poem.mp3", "canonical": "poems/poem.mp3"})
    result = RecoveryEngine(ctx).recover([defect])[0]
    assert result.recovered is True
    assert (ctx.audio_store / "poems" / "poem.mp3").read_bytes() == b"audio"


def test_placeholder_recovery_regenerates_without_changing_record_fields(tmp_path):
    ctx = recovery_context(tmp_path, cover_generator=fake_cover_generator)
    before = write_publishable_record(ctx, cover="/covers/default.svg")
    result = RecoveryEngine(ctx).recover([placeholder_defect(before)])[0]
    after = read_record(before.source_path)
    assert result.recovered is True
    assert after["id"] == before.id
    assert after["created_at"] == before.created_at
    assert after["cover"] != "/covers/default.svg"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q scripts/test_deploy_guard_transactional.py -k recovery`

Expected: recovery imports fail.

- [ ] **Step 3: Implement ordered source lookup and atomic restore**

Search transactional snapshot, persistent stores, canonical public trees, seed output, JSON store, golden history, and last known-good git revision. Match assets by expected filename, item ID, and recorded SHA-256. Copy through a temporary sibling file and `Path.replace()`.

- [ ] **Step 4: Implement metadata, reload, cover, and audio adapters**

Use `_per_content_io.update_per_content_fields` for metadata. Invoke `generate_cover_experimental.py --story-json <source>` with `COVER_OUTPUT_DIR` for missing or placeholder covers. Restore audio from all stores before invoking existing ID-preserving render commands such as `generate_audio.py --story-id <id>`; unsupported musical rerenders return unrecovered so transactional rollback restores the clean snapshot.

- [ ] **Step 5: Implement bounded progress rounds**

```python
def recover_until_stable(audit, recover, max_rounds=3):
    previous = None
    for round_number in range(1, max_rounds + 1):
        result = audit()
        signature = {(d.reason.value, d.item_id, json.dumps(d.details, sort_keys=True)) for d in result.blockers}
        if not signature:
            return result
        if signature == previous:
            return result
        recover(result.blockers)
        previous = signature
    return audit()
```

- [ ] **Step 6: Run tests and verify GREEN**

Run: `pytest -q scripts/test_deploy_guard_transactional.py -k 'recovery or stable'`

Expected: recovery tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/deploy_guard_recovery.py scripts/test_deploy_guard_transactional.py
git commit -m "feat: auto-recover deploy guard defects"
```

---

### Task 5: Transaction snapshot and rollback

**Files:**
- Create: `scripts/deploy_guard_transaction.py`
- Modify: `scripts/test_deploy_guard_transactional.py`

**Interfaces:**
- Consumes: clean preflight callback, deploy script path, rollback script path, audit and recovery callbacks.
- Produces: `TransactionConfig`, `TransactionSnapshot`, `run_transaction(config) -> FinalVerdict`.

- [ ] **Step 1: Write failing rollback tests**

```python
def test_transaction_rolls_back_when_recovery_cannot_reach_zero(tmp_path):
    calls = []
    verdict = run_transaction(transaction_config(
        tmp_path,
        preflight=[clean_audit()],
        postflight=[broken_audit(), broken_audit()],
        deploy=lambda: calls.append("deploy"),
        rollback=lambda snapshot: calls.append("rollback"),
        restore=lambda snapshot: calls.append("restore"),
        final_audit=clean_audit,
    ))
    assert calls == ["deploy", "rollback", "restore"]
    assert verdict.deployment_succeeded is False
    assert verdict.app_healthy is True


def test_transaction_refuses_to_start_without_clean_preflight_or_rollback_hook(tmp_path):
    with pytest.raises(TransactionPreconditionError):
        run_transaction(transaction_config(tmp_path, preflight=[broken_audit()], rollback=None))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q scripts/test_deploy_guard_transactional.py -k transaction`

Expected: transaction imports fail.

- [ ] **Step 3: Implement complete snapshots**

Snapshot per-content JSON, derived catalogs, asset manifests and hashes, current release identifiers, API counts, and configured roots into a timestamped directory under `/opt/deploy-guard-snapshots`. Write a manifest last so incomplete snapshots are never eligible for rollback.

- [ ] **Step 4: Implement safe script hooks**

Accept only absolute, executable regular files for deploy and rollback hooks. Run hooks without `shell=True`, pass snapshot and release IDs through environment variables, capture output, and require exit code zero.

- [ ] **Step 5: Implement rollback and verification**

On unresolved postflight blockers, invoke the rollback hook, restore content and assets atomically from the snapshot, reload the backend, and run the full audit. Return `app_healthy=True` only when the rollback audit has no blockers.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `pytest -q scripts/test_deploy_guard_transactional.py -k transaction`

Expected: transaction tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/deploy_guard_transaction.py scripts/test_deploy_guard_transactional.py
git commit -m "feat: add transactional deploy rollback"
```

---

### Task 6: CLI integration and final verdict semantics

**Files:**
- Modify: `scripts/deploy_guard.py`
- Modify: `scripts/test_deploy_guard_regression_contracts.py`
- Modify: `scripts/test_deploy_guard_transactional.py`

**Interfaces:**
- Consumes: manifest, audit, recovery, and transaction modules.
- Produces: strict `preflight`, `verify`, and `transaction` CLI behavior while preserving existing commands.

- [ ] **Step 1: Write failing CLI contract tests**

```python
def test_verify_never_labels_blockers_pre_existing_or_informational():
    source = Path("scripts/deploy_guard.py").read_text()
    assert "pre-existing" not in final_verdict_section(source).lower()
    assert "informational" not in final_verdict_section(source).lower()


def test_transaction_command_requires_deploy_and_rollback_hooks():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["transaction"])


def test_radio_issue_is_reported_outside_content_blockers():
    verdict = render_verdict(AuditResult([radio_defect()]))
    assert "Content: HEALTHY" in verdict
    assert "Radio broadcast: OFFLINE" in verdict
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q scripts/test_deploy_guard_regression_contracts.py scripts/test_deploy_guard_transactional.py -k 'verify_never or transaction_command or radio_issue'`

Expected: CLI contracts fail.

- [ ] **Step 3: Integrate strict preflight and verify**

Make `verify` build the publishable manifest, audit all live surfaces, run recovery rounds, and render only the final audit. Keep legacy snapshot and golden comparisons as recovery evidence; do not print stale golden removals as current blockers when those IDs are absent from the publishable manifest.

- [ ] **Step 4: Add the transaction command**

```python
txn = sub.add_parser("transaction", help="Run fail-closed deploy transaction")
txn.add_argument("--deploy-script", required=True)
txn.add_argument("--rollback-script", required=True)
txn.set_defaults(func=cmd_transaction)
```

- [ ] **Step 5: Preserve the radio-only exemption**

Run radio checks after the content verdict. Never add `RADIO_BROADCAST_OFFLINE` to `AuditResult.blockers`; add every other radio/content defect normally unless the reason code is exactly the approved broadcast outage.

- [ ] **Step 6: Run focused and regression tests**

Run: `pytest -q scripts/test_deploy_guard_transactional.py scripts/test_deploy_guard_regression_contracts.py`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/deploy_guard.py scripts/test_deploy_guard_regression_contracts.py scripts/test_deploy_guard_transactional.py
git commit -m "feat: enforce transactional deploy guard"
```

---

### Task 7: Production dry-run and rollout

**Files:**
- Create: `docs/DEPLOY_GUARD_RUNBOOK.md`
- Deploy: `scripts/deploy_guard*.py`
- Deploy: `data/deploy_placeholder_hashes.json`

**Interfaces:**
- Consumes: completed strict guard implementation and production rollback scripts.
- Produces: production zero-defect audit and documented transactional deployment command.

- [ ] **Step 1: Run the full local suite**

Run: `pytest -q scripts/test_deploy_guard_transactional.py scripts/test_deploy_guard_regression_contracts.py`

Expected: all tests pass with no warnings.

- [ ] **Step 2: Capture current production state**

Run: `python3 scripts/deploy_guard.py snapshot` on production.

Expected: snapshot succeeds only after zero content defects.

- [ ] **Step 3: Run strict production preflight without mutation**

Run: `python3 scripts/deploy_guard.py verify --dry-run`.

Expected: zero missing IDs, zero missing audio, zero missing covers, zero placeholders, zero broken playlist slots, and only the known radio broadcast issue reported separately.

- [ ] **Step 4: Deploy the guard modules through the approved release workflow**

Fast-forward the approved branch, install no new dependencies, and run the strict preflight again before enabling the transaction command.

- [ ] **Step 5: Verify automatic recovery with reversible canaries**

In a temporary test store, remove one copied audio asset, replace one copied custom cover with a registered placeholder hash, and remove one copied source record. Run `transaction` against the temporary roots and assert all three recover automatically without affecting production stores.

- [ ] **Step 6: Run final production verification**

Run: `python3 scripts/deploy_guard.py verify`.

Expected: content verdict healthy, all live URL and file counts complete, no placeholder covers, no stale pre-existing warnings, and the YouTube radio broadcast shown only in the separate radio status.

- [ ] **Step 7: Update the runbook and commit**

Document the required `transaction --deploy-script ... --rollback-script ...` invocation, recovery reason codes, snapshot retention, and rollback verification.

```bash
git add docs/DEPLOY_GUARD_RUNBOOK.md
git commit -m "docs: require transactional deploy guard"
```
