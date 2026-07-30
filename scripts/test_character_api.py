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
        ("GET", "/api/v1/characters/character-1"),
        ("POST", "/api/v1/characters/character-1/generations"),
        ("DELETE", "/api/v1/characters/character-1"),
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


def test_cross_user_character_routes_are_indistinguishable_from_not_found(api_state):
    app, db, get_current_user = api_state
    repo = type("Repo", (), {"db": db})()
    seed_user(repo)
    seed_user(repo, uid="u2")
    character = seed_character(repo, "u2", slot_number=1)
    db.collection("character_generation_jobs").document("job-u2").set({"uid": "u2"})
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u1"}
    client = TestClient(app)

    responses = [
        client.get(f"/api/v1/characters/{character['id']}"),
        client.get("/api/v1/characters/generations/job-u2"),
        client.post(
            "/api/v1/characters/quote",
            json={"mode": "edit", "target_character_id": character["id"]},
        ),
        client.post(
            f"/api/v1/characters/{character['id']}/generations",
            json=generation_body("character-generation-cross-user-edit"),
        ),
        client.delete(f"/api/v1/characters/{character['id']}"),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "not_found"


@pytest.mark.parametrize("body", [
    {"mode": "create", "target_character_id": "character-1"},
    {"mode": "edit", "target_character_id": None},
])
def test_quote_rejects_invalid_mode_target_combinations(authed_client, body):
    response = authed_client.post("/api/v1/characters/quote", json=body)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize("code,status_code", [
    ("not_found", 404),
    ("forbidden", 404),
    ("stale_quote", 409),
    ("no_slots", 409),
    ("insufficient_credits", 402),
    ("credits_frozen", 422),
])
def test_repository_errors_use_whitelisted_safe_codes(
    api_state, monkeypatch, code, status_code
):
    from app.api.v1 import characters
    from app.services.characters.repository import CharacterRepositoryError

    class RejectingRepository:
        def accept_generation(self, *args, **kwargs):
            raise CharacterRepositoryError(code)

    app, db, get_current_user = api_state
    repo = type("Repo", (), {"db": db})()
    seed_user(repo)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u1"}
    monkeypatch.setattr(characters, "_repository", lambda _: RejectingRepository())

    response = TestClient(app).post(
        "/api/v1/characters/generations",
        json=generation_body(f"character-generation-{code}"),
    )

    expected_code = "not_found" if code == "forbidden" else code
    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == expected_code


def test_unknown_repository_error_never_reaches_the_response(api_state, monkeypatch):
    from app.api.v1 import characters
    from app.services.characters.repository import CharacterRepositoryError

    class RejectingRepository:
        def accept_generation(self, *args, **kwargs):
            raise CharacterRepositoryError("database_host=private.internal")

    app, db, get_current_user = api_state
    repo = type("Repo", (), {"db": db})()
    seed_user(repo)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u1"}
    monkeypatch.setattr(characters, "_repository", lambda _: RejectingRepository())

    response = TestClient(app).post(
        "/api/v1/characters/generations",
        json=generation_body("character-generation-unknown-error"),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "generation_failed"
