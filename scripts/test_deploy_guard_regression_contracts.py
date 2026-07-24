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
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeClient:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url, **_kwargs):
        return self.responses[url]


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
