def content_ref_for_user(db_client, content_id: str, uid: str | None):
    public_ref = db_client.collection("content").document(content_id)
    if public_ref.get().exists:
        return public_ref
    generated_ref = db_client.collection("generated_content").document(content_id)
    generated = generated_ref.get()
    if generated.exists and uid and (generated.to_dict() or {}).get("owner_uid") == uid:
        return generated_ref
    return public_ref


def content_snapshot_for_user(db_client, content_id: str, uid: str | None):
    return content_ref_for_user(db_client, content_id, uid).get()


def generated_content_for_user(db_client, uid: str) -> list[dict]:
    collection = db_client.collection("generated_content")
    if hasattr(db_client, "collections"):
        values = db_client.collections.get("generated_content", {}).values()
        return [dict(item) for item in values if item.get("owner_uid") == uid]
    return [snapshot.to_dict() for snapshot in collection.where("owner_uid", "==", uid).get()]

