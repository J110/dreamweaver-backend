# Nap Playlist and Deploy Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee three free and four premium nap items using historical content, and block deployments that reintroduce today’s premium UI regressions.

**Architecture:** Make nap selection tier-safe at the cache boundary, search the full historical catalog before repeating content, and pad only as a last resort. Extend Deploy Guard with a production-data nap contract and the existing deterministic Emberlight verification suites.

**Tech Stack:** FastAPI, Pydantic, pytest, Next.js, Jest, Node.js

## Global Constraints

- Free nap playlists contain exactly 3 playable entries.
- Premium nap playlists contain exactly 4 playable entries.
- Historical content is preferred over repetition when today’s generation is incomplete.
- Deploy Guard exits non-zero for nap-count or Emberlight regression failures.

---

### Task 1: Nap playlist count contract

**Files:**
- Modify: `app/api/v1/playlist.py`
- Test: `scripts/test_nap_playlist_contract.py`

- [ ] Write tests proving tier-separated caching, unlimited historical fallback, and fourth-slot repetition.
- [ ] Run the focused test and confirm failure.
- [ ] Include membership tier in the nap cache key.
- [ ] Search the full historical catalog before repeating content.
- [ ] Re-run the focused test and confirm success.

### Task 2: Deploy Guard regression gates

**Files:**
- Modify: `scripts/deploy_guard.py`
- Test: `scripts/test_deploy_guard_regression_contracts.py`
- Modify: `dreamweaver-web/package.json`

- [ ] Register production-data nap checks for both tiers and languages.
- [ ] Register the Emberlight source and Jest regression suites.
- [ ] Run backend and web verification commands and confirm success.
