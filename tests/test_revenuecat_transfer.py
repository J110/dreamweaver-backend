from app.api.v1 import revenuecat
from app.services.local_store import LocalStore


def test_anonymous_transfer_reconciles_known_destination(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)
    store.collection("users").document("user-1").set({"uid": "user-1", "entitlements": {}})
    monkeypatch.setattr(revenuecat, "_fetch_customer_info", lambda uid: {"subscriber": {}})
    monkeypatch.setattr(revenuecat, "customer_info_to_source", lambda payload: {
        "status": "active",
        "expires": "2030-01-01T00:00:00Z",
        "product_id": "premium_annual",
        "store": "apple",
        "environment": "PRODUCTION",
    })
    monkeypatch.setattr(revenuecat, "_apply_native_tier_and_credits", lambda *args: None)

    revenuecat._process_transfer(store, {
        "transferred_from": ["$RCAnonymousID:source"],
        "transferred_to": ["user-1"],
        "store": "APP_STORE",
    })

    user = store.collection("users").document("user-1").get().to_dict()
    assert user["entitlements"]["apple"]["status"] == "active"
