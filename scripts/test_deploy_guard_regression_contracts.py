from pathlib import Path
from datetime import datetime, timedelta, timezone

from scripts import deploy_guard


SOURCE = (Path(__file__).parent / "deploy_guard.py").read_text()


def test_verify_registers_nap_playlist_contract():
    assert "nap_issues = verify_nap_playlist_counts()" in SOURCE


def test_verify_registers_frontend_regression_suite():
    assert "frontend_regression_issues = verify_frontend_regression_suite()" in SOURCE


def test_nap_contract_runs_inside_the_backend_container():
    assert '"sudo", "docker", "exec", "dreamweaver-backend"' in SOURCE


def test_nap_contract_uses_authenticated_four_row_users():
    assert '"username": "deploy-guard-free"' in SOURCE
    assert '"username": "deploy-guard-premium"' in SOURCE
    assert '("free", {"username": "deploy-guard-free"' in SOURCE
    assert '}, 4),' in SOURCE


def test_radio_contract_does_not_require_premium_long_stories():
    required_types = SOURCE.split("required_types = ", 1)[1].splitlines()[0]
    assert "long_story" not in required_types


def test_story_snapshot_recognizes_single_file_silly_song_audio():
    assert 'item.get("subtype") == "silly_song"' in SOURCE
    assert 'f"/audio/silly-songs/{item[\'audio_file\']}"' in SOURCE


class FakeResponse:
    def __init__(self, status_code, text="", data=None):
        self.status_code = status_code
        self.text = text
        self.data = data

    def json(self):
        return self.data


class FakeClient:
    def __init__(self, responses, head_responses=None):
        self.responses = responses
        self.head_responses = head_responses or {}

    def get(self, url, **_kwargs):
        return self.responses[url]

    def head(self, url, **_kwargs):
        return self.head_responses[url]

    def close(self):
        pass


def test_frontend_runtime_guard_rejects_missing_bundle():
    frontend = "https://dreamvalley.app"
    client = FakeClient({
        f"{frontend}/?source=app": FakeResponse(
            200,
            '<script src="/_next/static/chunks/app.js"></script>'
            '<link href="/_next/static/css/app.css" rel="stylesheet">',
        ),
        f"{frontend}/nap-playlist": FakeResponse(200),
        f"{frontend}/_next/static/chunks/app.js": FakeResponse(404),
        f"{frontend}/_next/static/css/app.css": FakeResponse(200),
        f"{frontend}/version.json": FakeResponse(200),
        f"{frontend}/sw.js": FakeResponse(200),
        f"{frontend}/logo-new.png": FakeResponse(200),
        f"{frontend}/upgrade-showcase.webp": FakeResponse(200),
    })

    issues = deploy_guard.verify_frontend_runtime_assets(
        frontend=frontend,
        client=client,
    )

    assert issues == [
        "Frontend runtime asset returned 404: /_next/static/chunks/app.js"
    ]


def test_verify_registers_frontend_runtime_assets():
    assert "runtime_asset_issues = verify_frontend_runtime_assets()" in SOURCE


def test_frontend_runtime_guard_rejects_missing_upgrade_showcase():
    frontend = "https://dreamvalley.app"
    client = FakeClient({
        f"{frontend}/?source=app": FakeResponse(
            200,
            '<script src="/_next/static/chunks/app.js"></script>',
        ),
        f"{frontend}/nap-playlist": FakeResponse(200),
        f"{frontend}/_next/static/chunks/app.js": FakeResponse(200),
        f"{frontend}/version.json": FakeResponse(200),
        f"{frontend}/sw.js": FakeResponse(200),
        f"{frontend}/logo-new.png": FakeResponse(200),
        f"{frontend}/upgrade-showcase.webp": FakeResponse(404),
    })

    issues = deploy_guard.verify_frontend_runtime_assets(
        frontend=frontend,
        client=client,
    )

    assert issues == [
        "Frontend runtime asset returned 404: /upgrade-showcase.webp"
    ]


def test_current_playback_guard_rejects_missing_audio():
    frontend = "https://dreamvalley.app"
    api = "https://api.dreamvalley.app"
    client = FakeClient(
        {
            f"{api}/api/v1/content?lang=en&page=1": FakeResponse(
                200,
                data={
                    "data": {
                        "items": [{
                            "audio_variants": [{
                                "url": "/audio/pre-gen/current.mp3",
                            }],
                        }],
                    },
                },
            ),
            f"{api}/api/v1/content?lang=hi&page=1": FakeResponse(
                200,
                data={"data": {"items": []}},
            ),
            f"{api}/api/v1/playlist/nap?lang=en&tz=Asia%2FKolkata": FakeResponse(
                200,
                data={
                    "data": {
                        "items": [{
                            "audio_url": "/audio/pre-gen/nap.mp3",
                        }],
                    },
                },
            ),
            f"{api}/api/v1/playlist/nap?lang=hi&tz=Asia%2FKolkata": FakeResponse(
                200,
                data={"data": {"items": []}},
            ),
        },
        {
            f"{frontend}/audio/pre-gen/current.mp3": FakeResponse(200),
            f"{frontend}/audio/pre-gen/nap.mp3": FakeResponse(404),
        },
    )

    issues = deploy_guard.verify_current_playback_assets(
        frontend=frontend,
        api=api,
        client=client,
    )

    assert issues == [
        "Current playback audio returned 404: /audio/pre-gen/nap.mp3"
    ]


def test_verify_registers_current_playback_assets():
    assert "playback_issues = verify_current_playback_assets()" in SOURCE


def test_character_worker_deploy_contract_cannot_be_removed():
    assert '"GET /api/v1/characters without authentication returns 401"' in SOURCE
    assert '"dreamweaver-character-worker is online"' in SOURCE
    assert '"CHARACTER_MEDIA_DIR exists and is writable by the backend user"' in SOURCE
    assert '"every stored portrait URL returns HTTP 200"' in SOURCE
    assert '"no accepted/generating job is older than its lease plus recovery window"' in SOURCE
    assert '"active_characters"' in SOURCE
    assert '"pending_character_jobs"' in SOURCE
    assert "character_guard_issues = verify_character_generation_contracts(api, after)" in SOURCE


def test_character_worker_accepts_pm2_when_systemd_unit_is_absent(monkeypatch):
    api = "https://api.dreamvalley.app"
    client = FakeClient({
        f"{api}/api/v1/characters": FakeResponse(401),
    })
    monkeypatch.setattr(deploy_guard.httpx, "Client", lambda **_kwargs: client)

    def fake_ssh_run(command, timeout=120):
        if command == "systemctl is-active --quiet dreamweaver-character-worker":
            return "", 3
        if "pm2 describe dreamweaver-character-worker" in command:
            return "", 0
        return "", 0

    monkeypatch.setattr(deploy_guard, "_ssh_run", fake_ssh_run)

    issues = deploy_guard.verify_character_generation_contracts(
        api,
        {"active_characters": [], "pending_character_jobs": []},
    )

    assert deploy_guard.CHARACTER_DEPLOY_CONTRACTS[1] not in issues


def test_character_snapshot_loss_is_a_deploy_regression():
    changes = deploy_guard.diff_states(
        {
            "active_characters": [{"id": "character-1"}],
            "pending_character_jobs": [{"id": "job-1"}],
            "character_jobs": {"job-1": "accepted"},
        },
        {
            "active_characters": [],
            "pending_character_jobs": [],
            "character_jobs": {},
        },
    )

    assert "  ❌ REMOVED character: character-1" in changes["removed"]
    assert "  ❌ LOST character generation job: job-1" in changes["removed"]


def test_accepted_job_uses_configured_lease_plus_recovery_window():
    now = datetime.now(timezone.utc)
    job = {"status": "accepted", "created_at": (now - timedelta(seconds=359)).isoformat()}

    assert deploy_guard.character_job_is_stale(job, now, lease_seconds=300, recovery_seconds=60) is False
    job["created_at"] = (now - timedelta(seconds=361)).isoformat()
    assert deploy_guard.character_job_is_stale(job, now, lease_seconds=300, recovery_seconds=60) is True


def test_generating_job_uses_its_lease_expiry_plus_recovery_window():
    now = datetime.now(timezone.utc)
    job = {"status": "generating", "lease_expires_at": (now - timedelta(seconds=59)).isoformat()}

    assert deploy_guard.character_job_is_stale(job, now, lease_seconds=300, recovery_seconds=60) is False
    job["lease_expires_at"] = (now - timedelta(seconds=61)).isoformat()
    assert deploy_guard.character_job_is_stale(job, now, lease_seconds=300, recovery_seconds=60) is True
