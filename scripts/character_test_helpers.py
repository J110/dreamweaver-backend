import threading
from copy import deepcopy

import pytest

from app.schemas.character_schema import CharacterInput, GenerationRequest
from app.services.characters.repository import CharacterRepository


DEFAULT_PROFILE = {
    "name": "Lumi",
    "character_type": "fox",
    "gender": "not_specified",
    "traits": ["curious", "kind"],
    "custom_description": "A moonlit fox",
}
DEFAULT_PORTRAIT_URL = "https://images.example.test/characters/lumi.png"


class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = deepcopy(data) if data is not None else None
        self.exists = data is not None

    def to_dict(self):
        return deepcopy(self._data) if self._data is not None else None


class FakeDocument:
    def __init__(self, db, collection, doc_id):
        self.db = db
        self.collection_name = collection
        self.id = doc_id

    def get(self, transaction=None):
        before_read = getattr(self.db, "_before_read", None)
        if callable(before_read):
            before_read(self.collection_name, self.id)
        return FakeSnapshot(self.id, self.db.collections[self.collection_name].get(self.id))

    def set(self, data):
        self.db._before_write(self.collection_name, self.id)
        self.db.collections[self.collection_name][self.id] = deepcopy(data)

    def update(self, fields):
        self.db._before_write(self.collection_name, self.id)
        self.db.collections[self.collection_name][self.id].update(deepcopy(fields))

    def delete(self):
        self.db._before_write(self.collection_name, self.id)
        self.db.collections[self.collection_name].pop(self.id, None)


class FakeCollection:
    def __init__(self, db, name):
        self.db = db
        self.name = name

    def document(self, doc_id):
        return FakeDocument(self.db, self.name, doc_id)


class FakeTransaction:
    def get(self, document):
        yield document.get(self)

    def set(self, document, data):
        document.set(data)

    def update(self, document, fields):
        document.update(fields)

    def delete(self, document):
        document.delete()


class FakeFirestore:
    def __init__(self):
        self.collections = {
            "characters": {},
            "character_generation_jobs": {},
            "character_slot_counters": {},
            "users": {},
        }
        self._lock = threading.RLock()
        self._failed_write = None

    def collection(self, name):
        self.collections.setdefault(name, {})
        return FakeCollection(self, name)

    def run_transaction(self, callback):
        with self._lock:
            snapshot = deepcopy(self.collections)
            try:
                return callback(FakeTransaction())
            except Exception:
                self.collections.clear()
                self.collections.update(snapshot)
                raise

    def fail_next_write(self, collection, doc_id):
        self._failed_write = (collection, doc_id)

    def _before_write(self, collection, doc_id):
        if self._failed_write == (collection, doc_id):
            self._failed_write = None
            raise RuntimeError("transaction_write_failed")


class FakeLocalStore:
    def __init__(self):
        self.collections = {
            "characters": {},
            "character_generation_jobs": {},
            "character_slot_counters": {},
            "users": {},
        }
        self._lock = threading.RLock()
        self._failed_write = None
        self._read_barrier = None
        self._read_target = None

    def collection(self, name):
        self.collections.setdefault(name, {})
        return FakeCollection(self, name)

    def fail_next_write(self, collection, doc_id):
        self._failed_write = (collection, doc_id)

    def _before_write(self, collection, doc_id):
        if self._failed_write == (collection, doc_id):
            self._failed_write = None
            raise RuntimeError("transaction_write_failed")

    def synchronize_reads_at(self, collection, doc_id):
        self._read_target = (collection, doc_id)
        self._read_barrier = threading.Barrier(2)

    def _before_read(self, collection, doc_id):
        if self._read_target == (collection, doc_id):
            try:
                self._read_barrier.wait(timeout=0.1)
            except threading.BrokenBarrierError:
                pass


class FakeCharacterRepository(CharacterRepository):
    def __init__(self):
        self.db = FakeFirestore()
        super().__init__(self.db)

    def user(self, uid):
        return self.db.collection("users").document(uid).get().to_dict()

    def character(self, character_id):
        return self.db.collection("characters").document(character_id).get().to_dict()

    def cleanup_marker(self, character_id):
        return self.db.collection("character_generation_jobs").document(
            f"cleanup-{character_id}"
        ).get().to_dict()

    def counter(self, uid):
        return self.db.collection("character_slot_counters").document(uid).get().to_dict()


def seed_user(
    repo,
    uid="u1",
    credits_remaining=3,
    topup_credits_remaining=0,
    credits_frozen=False,
):
    user = {
        "uid": uid,
        "credits_remaining": credits_remaining,
        "topup_credits_remaining": topup_credits_remaining,
        "credits_reserved": 0,
        "credits_frozen": credits_frozen,
    }
    repo.db.collection("users").document(uid).set(user)
    return user


def seed_character(repo, uid="u1", slot_number=1, version=1):
    character_id = f"character-{uid}-{slot_number}"
    character = {
        "id": character_id,
        "uid": uid,
        "slot_number": slot_number,
        "version": version,
        "profile": deepcopy(DEFAULT_PROFILE),
        "portrait_url": DEFAULT_PORTRAIT_URL,
    }
    repo.db.collection("characters").document(character_id).set(character)
    counter_ref = repo.db.collection("character_slot_counters").document(uid)
    counter = counter_ref.get().to_dict() or {
        "occupied_slots": [],
        "reserved_slots": [],
        "revision": 0,
        "slot_reservations": {},
    }
    counter["occupied_slots"] = sorted(set(counter["occupied_slots"] + [slot_number]))
    counter_ref.set(counter)
    return character


def create_request(idempotency_key="character-generation-create", quote_version="0"):
    return GenerationRequest(
        inputs=CharacterInput(
            name="Lumi",
            character_type="fox",
            gender="not_specified",
            traits=["curious", "kind"],
        ),
        quote_version=quote_version,
        idempotency_key=idempotency_key,
    )


def paid_create_request(idempotency_key="character-generation-paid", quote_version="0"):
    return create_request(idempotency_key=idempotency_key, quote_version=quote_version)


def edit_request(character, idempotency_key="character-generation-edit", quote_version="0"):
    return GenerationRequest(
        inputs=CharacterInput(
            name=character["profile"].get("name"),
            character_type="fox",
            gender="not_specified",
            traits=["curious", "kind"],
        ),
        quote_version=quote_version,
        idempotency_key=idempotency_key,
    )


class FakeGenerator:
    def generate(self, inputs):
        return deepcopy(DEFAULT_PROFILE), DEFAULT_PORTRAIT_URL


@pytest.fixture
def local_store_repo():
    return local_store_repo_fixture()


def local_store_repo_fixture():
    db = FakeLocalStore()
    repo = CharacterRepository(db)
    repo.db = db
    seed_user(repo)
    return repo


@pytest.fixture
def deterministic_profile():
    return deepcopy(DEFAULT_PROFILE)


@pytest.fixture
def deterministic_portrait_url():
    return DEFAULT_PORTRAIT_URL


@pytest.fixture
def fake_repo():
    repo = FakeCharacterRepository()
    seed_user(repo)
    repo.seed_character = lambda uid, slot_number, version=1: seed_character(
        repo, uid, slot_number, version
    )
    return repo
