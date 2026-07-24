from pathlib import Path

from scripts import deploy_guard


SOURCE = (Path(__file__).parent / "deploy_guard.py").read_text()


def test_verify_registers_nap_playlist_contract():
    assert "nap_issues = verify_nap_playlist_counts()" in SOURCE


def test_verify_registers_frontend_regression_suite():
    assert "frontend_regression_issues = verify_frontend_regression_suite()" in SOURCE


def test_nap_contract_runs_inside_the_backend_container():
    assert '"sudo", "docker", "exec", "dreamweaver-backend"' in SOURCE


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
