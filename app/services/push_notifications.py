from __future__ import annotations

import os

from app.config import get_settings


class PushUnavailable(RuntimeError):
    pass


def _push_app():
    settings = get_settings()
    if not settings.firebase_push_project_id:
        raise PushUnavailable("firebase_push_project_id_missing")
    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError as exc:
        raise PushUnavailable("firebase_admin_missing") from exc
    try:
        return firebase_admin.get_app("dreamvalley-push")
    except ValueError:
        pass
    if settings.firebase_push_credentials_path:
        if not os.path.exists(settings.firebase_push_credentials_path):
            raise PushUnavailable("firebase_push_credentials_missing")
        credential = credentials.Certificate(settings.firebase_push_credentials_path)
    else:
        try:
            default_app = firebase_admin.get_app()
        except ValueError as exc:
            raise PushUnavailable("firebase_default_app_missing") from exc
        if default_app.project_id != settings.firebase_push_project_id:
            raise PushUnavailable("firebase_push_credentials_path_missing")
        credential = default_app.credential
    try:
        return firebase_admin.initialize_app(
            credential,
            {"projectId": settings.firebase_push_project_id},
            name="dreamvalley-push",
        )
    except ValueError:
        return firebase_admin.get_app("dreamvalley-push")


def send(db_client, targets: list[dict], title: str, body: str, route: str) -> dict:
    if not get_settings().push_notifications_enabled:
        raise PushUnavailable("push_notifications_disabled")
    if not route.startswith("/") or route.startswith("//"):
        raise ValueError("invalid_route")
    tokens = list(dict.fromkeys(row.get("target") for row in targets if row.get("target")))
    if not tokens:
        return {"attempted": 0, "sent": 0, "failed": 0}
    from firebase_admin import messaging
    app = _push_app()
    sent = 0
    failed = 0
    for offset in range(0, len(tokens), 500):
        batch = tokens[offset:offset + 500]
        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data={"route": route},
            tokens=batch,
        )
        response = messaging.send_each_for_multicast(message, app=app)
        sent += response.success_count
        failed += response.failure_count
        for token, result in zip(batch, response.responses):
            if not result.success and result.exception and "registration-token-not-registered" in str(result.exception):
                for row in targets:
                    if row.get("target") == token:
                        db_client.collection("push_devices").document(row["id"]).update({"active": False})
    return {"attempted": len(tokens), "sent": sent, "failed": failed}
