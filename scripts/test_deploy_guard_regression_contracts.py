from pathlib import Path


SOURCE = (Path(__file__).parent / "deploy_guard.py").read_text()


def test_verify_registers_nap_playlist_contract():
    assert "nap_issues = verify_nap_playlist_counts()" in SOURCE


def test_verify_registers_frontend_regression_suite():
    assert "frontend_regression_issues = verify_frontend_regression_suite()" in SOURCE


def test_nap_contract_runs_inside_the_backend_container():
    assert '"sudo", "docker", "exec", "dreamweaver-backend"' in SOURCE
