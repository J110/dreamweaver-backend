import pytest
from fastapi.testclient import TestClient

from scripts.character_test_helpers import FakeFirestore, seed_character, seed_user


def generation_body(idempotency_key="character-generation-0001", quote_version="0"):
    return {
        "inputs": {
            "name": "Lumi",
            "character_type": "fox",
            "gender": "not_specified",
            "traits": ["curious", "kind"],
        },
        "quote_version": quote_version,
        "idempotency_key": idempotency_key,
    }


@pytest.fixture
def api_state():
    from app.dependencies import get_current_user, get_db_client
    from app.main import app

    db = FakeFirestore()
    app.dependency_overrides[get_db_client] = lambda: db
    yield app, db, get_current_user
    app.dependency_overrides.pop(get_db_client, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client(api_state):
    app, _, _ = api_state
    return TestClient(app)


@pytest.fixture
def authed_client(api_state):
    app, db, get_current_user = api_state
    repo = type("Repo", (), {"db": db})()
    seed_user(repo)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u1"}
    return TestClient(app)


def test_all_character_routes_require_auth(client):
    paths = [
        ("GET", "/api/v1/characters"),
        ("POST", "/api/v1/characters/quote"),
        ("POST", "/api/v1/characters/generations"),
        ("GET", "/api/v1/characters/generations/job-1"),
    ]
    for method, path in paths:
        assert client.request(method, path, json={} if method == "POST" else None).status_code == 401


def test_quote_returns_slot_and_projected_balance(authed_client):
    response = authed_client.post(
        "/api/v1/characters/quote",
        json={"mode": "create", "target_character_id": None},
    )
    assert response.status_code == 200
    assert response.json()["data"]["slot_number"] == 1
    assert response.json()["data"]["credit_cost"] == 0


def test_submit_returns_202_and_same_job_for_retry(authed_client):
    body = generation_body(idempotency_key="character-generation-0001")
    first = authed_client.post("/api/v1/characters/generations", json=body)
    second = authed_client.post("/api/v1/characters/generations", json=body)
    assert first.status_code == second.status_code == 202
    assert first.json()["data"]["id"] == second.json()["data"]["id"]


def test_list_detail_job_status_and_delete_are_scoped_to_current_user(api_state):
    app, db, get_current_user = api_state
    repo = type("Repo", (), {"db": db})()
    seed_user(repo)
    seed_user(repo, uid="u2")
    character = seed_character(repo, "u1", slot_number=1)
    other = seed_character(repo, "u2", slot_number=2)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u1"}
    client = TestClient(app)

    listed = client.get("/api/v1/characters")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [character["id"]]
    assert client.get(f"/api/v1/characters/{character['id']}").status_code == 200
    assert client.get(f"/api/v1/characters/{other['id']}").status_code == 404

    job = client.post("/api/v1/characters/generations", json=generation_body()).json()["data"]
    assert client.get(f"/api/v1/characters/generations/{job['id']}").json()["data"]["status"] == "accepted"
    assert client.delete(f"/api/v1/characters/{character['id']}").status_code == 200


def test_repository_rejection_returns_safe_error_code(api_state):
    app, db, get_current_user = api_state
    repo = type("Repo", (), {"db": db})()
    seed_user(repo, credits_frozen=True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u1"}
    response = TestClient(app).post(
        "/api/v1/characters/generations",
        json=generation_body(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "credits_frozen"
