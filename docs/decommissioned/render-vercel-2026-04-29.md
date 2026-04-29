# Render & Vercel decommissioning — 2026-04-29

Snapshot of staging-platform configuration captured immediately before decommissioning. The Dream Valley app is moving to a production-only architecture: GitHub holds code, the GCP VM holds production state, and there is no staging environment going forward.

This document exists for reference if any future work needs to reconstruct what these services were doing or how they were configured.

---

## Service activity at decommission

### Render — likely dormant

The `render.yaml` manifest captured below references **stale env vars** that no longer match production reality:

| `render.yaml` env var | Status |
|---|---|
| `GROQ_API_KEY` | Stale. Production switched to Mistral months ago for content generation. |
| `CHATTERBOX_URL` | Stale. Production now uses ElevenLabs (Modal) for English TTS via `TTS_ENGINE_EN=elevenlabs`. |
| `KOKORO_URL` | Stale. Kokoro was an early TTS experiment; abandoned long ago. |
| `DEFAULT_TTS_PROVIDER=edge-tts` | Stale. Production never used edge-tts; this was a default before the Chatterbox/ElevenLabs migration. |

This is consistent with the Render service running outdated code from before the Mistral+ElevenLabs migration. It almost certainly served little to no real traffic in recent weeks. Phase A audit (2026-04-29) confirmed:
- No DNS records on `dreamvalley.app` or any subdomain point at Render
- No code in either repo hardcodes a `*.onrender.com` URL
- No GitHub Actions workflow references Render

### Vercel — minimal config

The `vercel.json` manifest is one line: `{ "framework": "nextjs" }`. No custom build commands, no custom env vars, no project-level configuration beyond the framework hint. Vercel was using defaults for everything.

Phase A audit confirmed: no DNS, no hardcoded URLs, no workflows reference Vercel.

---

## Render service config

> **Dashboard-only fields are marked `<dashboard required>`.** Anmol to fill these in from the Render dashboard before tear-down. The manifest-derived fields are populated from `render.yaml` (full text in the appendix below).

| Field | Value |
|---|---|
| Service name | `dreamweaver-api` (per `render.yaml`) |
| Service ID | `<dashboard required>` |
| Plan tier | `<dashboard required>` (likely Free per "Free tier" mentions in `docs/DAILY_PIPELINE_GUIDE.md` line 55) |
| Region | `<dashboard required>` |
| Runtime | `python` 3.11.7 |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `<dashboard required>` (likely `/health`, default Render check) |
| Persistent disk mount path | `<dashboard required>` (none expected — service was stateless) |
| Persistent disk size | `<dashboard required>` |
| Auto-deploy branch | `<dashboard required>` (likely `main` of `J110/dreamweaver-backend`) |
| Auto-deploy paths trigger | `<dashboard required>` (Render typically deploys on any push to the watched branch — confirm) |
| Custom domains attached | `<dashboard required>` (Phase A DNS audit found none on `dreamvalley.app`; confirm no other domain is wired) |

### Environment variables (from `render.yaml`)

| Key | Value | Notes |
|---|---|---|
| `PYTHON_VERSION` | `3.11.7` | Manifest constant |
| `GROQ_API_KEY` | `REDACTED-GROQ_API_KEY` | `sync: false` in manifest → set manually in dashboard. Stale (production uses Mistral). |
| `ENVIRONMENT` | `production` | Misleading — was actually staging. |
| `DEBUG` | `false` | |
| `CORS_ORIGINS` | `*` | Permissive; standard for staging. |
| `CHATTERBOX_URL` | `REDACTED-CHATTERBOX_URL` | `sync: false`. Stale (production uses ElevenLabs). |
| `KOKORO_URL` | `REDACTED-KOKORO_URL` | `sync: false`. Stale (Kokoro abandoned). |
| `DEFAULT_TTS_PROVIDER` | `edge-tts` | Stale. |

### Additional dashboard-only env vars

There may be env vars set in the Render dashboard that are NOT in `render.yaml` (vars added directly via the UI bypass the manifest). Worth a final check before deletion:

- `<dashboard required>` — list any keys here, redact values to `REDACTED-{key}` format

---

## Vercel project config

> **Dashboard-only fields are marked `<dashboard required>`.** Anmol to fill these in from the Vercel dashboard before tear-down.

| Field | Value |
|---|---|
| Project name | `dreamweaver-web` (likely; confirm) |
| Project ID | `<dashboard required>` |
| Team / scope | `<dashboard required>` |
| Framework preset | `nextjs` (per `vercel.json`) |
| Build command | Default (Next.js: `next build`) |
| Output directory | Default (Next.js: `.next`) |
| Install command | Default (npm/pnpm/yarn auto-detected) |
| Production branch | `<dashboard required>` (likely `main` of `J110/dreamweaver-web`) |
| Preview branches | `<dashboard required>` (likely all branches) |
| Custom domains attached | `<dashboard required>` (Phase A DNS audit found none on `dreamvalley.app`; confirm) |
| Build-time integrations | `<dashboard required>` (analytics, monitoring, Sentry, etc.) |

### Environment variables

The frontend repo's `MEMORY.md` notes "Env var: `NEXT_PUBLIC_API_URL` set in Vercel dashboard". Capture the full list:

- `NEXT_PUBLIC_API_URL` = `REDACTED-NEXT_PUBLIC_API_URL` (likely the public API URL — `https://api.dreamvalley.app` for production parity, or a Render staging URL)
- `<dashboard required>` — list any other keys, redact values

---

## DNS records related to these services (current state per Phase A audit)

Public DNS as of 2026-04-29 04:54 UTC:

| Hostname | Type | Value | Pointing at |
|---|---|---|---|
| `dreamvalley.app` | A | `34.14.172.180` | GCP VM (production) |
| `www.dreamvalley.app` | CNAME | `dreamvalley.app` → `34.14.172.180` | GCP VM (production) |
| `api.dreamvalley.app` | A | `34.14.172.180` | GCP VM (production) |

DNS provider: **GoDaddy** (`ns23/ns24.domaincontrol.com`).

**Zero records pointing at Render or Vercel** in the public DNS. The user (Anmol) should verify no additional non-public records exist via the GoDaddy dashboard before tear-down.

---

## Why these services were originally set up

Render and Vercel were the original deployment targets for the dreamweaver-backend and dreamweaver-web repos — pre-dating the GCP VM migration. They served as the "test environment" parallel to production:

- Push to `J110/dreamweaver-backend` `main` → Render builds and deploys automatically → backend reachable at the Render hostname
- Push to `J110/dreamweaver-web` `main` → Vercel builds and deploys automatically → frontend reachable at the Vercel preview URL

The pipeline cron used to commit generated content + seed data + covers to GitHub, which would trigger both auto-deploys, propagating new content to the test environment.

This stopped working as a cohesive "test environment" after several incremental changes:

1. **Audio + cover persistence stores** moved off-repo to `/opt/audio-store/` and `/opt/cover-store/` on the GCP VM. The Render/Vercel services no longer had access to these stores, so test deploys would 404 most cover and audio URLs.
2. **Production env-var divergence** — production switched to Mistral + ElevenLabs while Render's manifest stayed on Groq + Chatterbox.
3. **2026-04-29 `SKIP_PUBLISH_STEP=1`** — the cron stopped pushing generated content to GitHub entirely (added as a fix for a different incident; see commit `43517a8`). Render and Vercel stopped receiving daily content updates from cron.

By the time of decommissioning, neither service was a meaningful staging environment — both were dormant remnants of a prior architecture.

---

## Appendix: Manifest files

### `dreamweaver-backend/render.yaml`

```yaml
services:
  - type: web
    name: dreamweaver-api
    runtime: python
    pythonVersion: "3.11.7"
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: PYTHON_VERSION
        value: "3.11.7"
      - key: GROQ_API_KEY
        sync: false
      - key: ENVIRONMENT
        value: production
      - key: DEBUG
        value: "false"
      - key: CORS_ORIGINS
        value: "*"
      - key: CHATTERBOX_URL
        sync: false
      - key: KOKORO_URL
        sync: false
      - key: DEFAULT_TTS_PROVIDER
        value: "edge-tts"
```

### `dreamweaver-web/vercel.json`

```json
{
  "framework": "nextjs"
}
```

---

## Decommission checklist

For Phase C reference. Each item gets ticked when complete:

- [ ] Render dashboard: capture remaining `<dashboard required>` fields above
- [ ] Vercel dashboard: capture remaining `<dashboard required>` fields above
- [ ] Render dashboard: delete the `dreamweaver-api` service
- [ ] Vercel dashboard: delete the `dreamweaver-web` project
- [ ] GoDaddy DNS: confirm no records reference Render/Vercel; remove if any found
- [ ] `dreamweaver-backend`: delete `render.yaml` from repo
- [ ] `dreamweaver-web`: delete `vercel.json` from repo
- [ ] `dreamweaver-backend/CLAUDE.md`: edit lines 160 / 162 / 173 (per spec §7)
- [ ] `dreamweaver-backend/docs/DAILY_PIPELINE_GUIDE.md`: edit lines 19 / 55 / 56 / 65 / 579–583 / 596 / 599 (per spec §7)
- [ ] Verify `https://dreamvalley.app/` returns 200 post-teardown
- [ ] Verify `https://api.dreamvalley.app/api/v1/content?limit=1` returns 200 post-teardown
- [ ] Commit doc updates to `dreamweaver-backend` and push

A broader doc-cleanup pass (~20 docs reference render/vercel/staging beyond the spec-pinned files) is tracked as a separate follow-up — not part of teardown.
