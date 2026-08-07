from app.services.local_store import LocalStore
from app.services.subscription_accounts import link_verified_apple_identity, primary_user_for_account, sync_subscription_account_from_user


def test_links_multiple_users_to_one_verified_email_account(tmp_path):
    store = LocalStore(tmp_path)
    store.collection("users").document("user-1").set({"uid": "user-1"})
    store.collection("users").document("user-2").set({"uid": "user-2"})

    first = link_verified_apple_identity(store, "user-1", "apple-subject", "Relay@Privaterelay.AppleID.com")
    second = link_verified_apple_identity(store, "user-2", "apple-subject", None)

    assert first["id"] == second["id"]
    assert second["user_uids"] == ["user-1", "user-2"]
    assert second["recovery_email"] == "relay@privaterelay.appleid.com"


def test_email_optional_apple_account_tracks_premium_user(tmp_path):
    store = LocalStore(tmp_path)
    store.collection("users").document("user-1").set({
        "uid": "user-1",
        "entitlements": {
            "apple": {
                "status": "active",
                "expires": "2030-01-01T00:00:00Z",
            },
        },
    })

    linked = link_verified_apple_identity(store, "user-1", "phone-only-apple-subject", None)
    synced = sync_subscription_account_from_user(store, "user-1")

    assert linked["recovery_email"] is None
    assert synced["tier"] == "premium"
    assert synced["status"] == "active"


def test_restore_prefers_premium_profile_on_shared_apple_account(tmp_path):
    store = LocalStore(tmp_path)
    store.collection("users").document("free-user").set({"uid": "free-user"})
    store.collection("users").document("premium-user").set({
        "uid": "premium-user",
        "entitlements": {
            "apple": {
                "status": "active",
                "expires": "2030-01-01T00:00:00Z",
            },
        },
    })
    account = {
        "primary_uid": "free-user",
        "user_uids": ["free-user", "premium-user"],
    }

    restored = primary_user_for_account(store, account)

    assert restored["uid"] == "premium-user"
