from app.services.local_store import LocalStore
from app.services.push_devices import active_for_user, register, unregister


def test_push_registration_is_idempotent_and_reversible(tmp_path):
    store = LocalStore(tmp_path)
    register(store, "user-1", "token-value-that-is-long-enough", "ios", "authorized")
    register(store, "user-1", "token-value-that-is-long-enough", "ios", "authorized")

    assert len(active_for_user(store, "user-1")) == 1
    unregister(store, "user-1", "token-value-that-is-long-enough")
    assert active_for_user(store, "user-1") == []
