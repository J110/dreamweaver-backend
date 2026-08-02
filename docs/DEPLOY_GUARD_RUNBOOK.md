# Deploy Guard Runbook

All production changes must run through one Deploy Guard transaction. Direct `git pull`, rebuild, restart, asset copy, content reload, and frontend deployment commands are not release procedures.

## Read-only preflight

```bash
cd /opt/dreamweaver-backend
python3 scripts/deploy_guard.py preflight --dry-run
```

The command must report `Content: HEALTHY`. `Radio broadcast: OFFLINE` is the only non-blocking result.

## Guarded deployment

Deploy and rollback hooks must be absolute paths to executable regular files. Each hook receives `DEPLOY_GUARD_SNAPSHOT_ID`, `DEPLOY_GUARD_SNAPSHOT_ROOT`, and the captured release identifiers.

```bash
cd /opt/dreamweaver-backend
python3 scripts/deploy_guard.py transaction \
  --deploy-script /opt/deploy-hooks/deploy-release \
  --rollback-script /opt/deploy-hooks/rollback-release
```

The transaction auto-recovers preflight defects, snapshots content and persistent asset stores, runs the deployment hook, audits every EN/HI catalog and free/premium bedtime and nap surface, and retries reason-aware recovery. Any remaining blocker invokes the rollback hook, restores the snapshot, reloads content, and audits again.

## Recovery reasons

- Missing or misrouted audio is copied atomically from the snapshot or persistent stores.
- Missing custom covers are restored or regenerated; registered placeholders are always regenerated.
- Missing live items, stale state, playlist gaps, and transient origin failures trigger reload and re-audit.
- Wrong metadata is repaired from canonical paths; missing source records are restored from the snapshot or removed by reload.
- Every unresolved defect blocks. The YouTube radio broadcast outage is the only exemption.

## Snapshot retention

Snapshots live under `/opt/deploy-guard-snapshots` by default. Keep the latest successful snapshot and every snapshot referenced by an active release; remove older snapshots only after a later transaction finishes with `Content: HEALTHY`.

## Final verification

```bash
cd /opt/dreamweaver-backend
python3 scripts/deploy_guard.py verify
```

Success requires zero missing publishable IDs, audio files, custom covers, placeholder covers, broken URLs, and playlist slots. The verdict prints current unresolved defects only.
