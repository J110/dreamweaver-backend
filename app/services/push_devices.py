from __future__ import annotations

import hashlib
from datetime import datetime, timezone


def _id(uid: str, target: str) -> str:
    return hashlib.sha256(f"{uid}:{target}".encode()).hexdigest()


def register(db_client, uid: str, target: str, platform: str, permission: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    device_id = _id(uid, target)
    row = {
        "id": device_id,
        "uid": uid,
        "target": target,
        "target_type": "fcm_registration_token",
        "platform": platform,
        "permission": permission,
        "active": True,
        "updated_at": now,
    }
    existing = db_client.collection("push_devices").document(device_id).get()
    row["created_at"] = (existing.to_dict() or {}).get("created_at", now) if existing.exists else now
    db_client.collection("push_devices").document(device_id).set(row)
    return row


def unregister(db_client, uid: str, target: str) -> None:
    ref = db_client.collection("push_devices").document(_id(uid, target))
    if ref.get().exists:
        ref.update({"active": False, "updated_at": datetime.now(timezone.utc).isoformat()})


def active_for_user(db_client, uid: str) -> list[dict]:
    return [
        snapshot.to_dict() or {}
        for snapshot in db_client.collection("push_devices").where("uid", "==", uid).where("active", "==", True).get()
    ]


def active_targets(db_client, uid: str | None = None) -> list[dict]:
    query = db_client.collection("push_devices").where("active", "==", True)
    if uid:
        query = query.where("uid", "==", uid)
    return [snapshot.to_dict() or {} for snapshot in query.get()]
