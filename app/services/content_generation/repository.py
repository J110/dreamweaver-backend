import hashlib
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from app.schemas.content_generation_schema import (
    ContentGenerationErrorCode,
    ContentGenerationJob,
    ContentGenerationRequest,
    ContentGenerationStatus,
)
from app.utils.credits import (
    available_credit_total,
    debit_reserved_credit_fields,
    release_credit_fields,
    reserve_credit_fields,
)


CONTENT_GENERATION_CREDIT_COST = 1


class ContentGenerationRepositoryError(ValueError):
    pass


class ContentGenerationRepository:
    def __init__(self, db_client):
        self.db_client = db_client

    def accept_generation(self, uid: str, request: ContentGenerationRequest) -> ContentGenerationJob:
        job_ref = self._job_ref(uid, request.idempotency_key)

        def accept(transaction):
            existing = self._data(self._read(transaction, job_ref))
            if existing:
                return ContentGenerationJob.model_validate(existing)

            active = self._active_job(uid, transaction)
            if active:
                self._reject("generation_in_progress")

            user_ref = self._user_ref(uid)
            user = self._require(user_ref, "not_found", transaction)
            if user.get("credits_frozen"):
                self._reject("credits_frozen")
            if available_credit_total(user) < CONTENT_GENERATION_CREDIT_COST:
                self._reject("insufficient_credits")

            character_snapshot = None
            if request.character_id:
                character = self._require(
                    self.db_client.collection("characters").document(request.character_id),
                    "not_found",
                    transaction,
                )
                if character.get("uid") != uid:
                    self._reject("not_found")
                character_snapshot = {
                    "id": character.get("id"),
                    "profile": character.get("profile", {}),
                    "portrait_url": character.get("portrait_url"),
                }

            self._write_update(
                transaction,
                user_ref,
                reserve_credit_fields(user, CONTENT_GENERATION_CREDIT_COST),
            )
            now = datetime.now(timezone.utc).isoformat()
            content_id = f"personal-{uuid.uuid4().hex}"
            job = ContentGenerationJob(
                id=job_ref.id,
                uid=uid,
                status=ContentGenerationStatus.accepted,
                stage="queued",
                idempotency_key=request.idempotency_key,
                reserved_credit_amount=CONTENT_GENERATION_CREDIT_COST,
                content_id=content_id,
                created_at=now,
                updated_at=now,
                inputs=request.model_dump(exclude={"idempotency_key"}),
                profile_snapshot={
                    "child_age": int(user.get("child_age") or 6),
                    "lang": user.get("preferred_lang") or user.get("lang") or "en",
                },
                character_snapshot=character_snapshot,
            )
            self._write_set(transaction, job_ref, job.model_dump(mode="json"))
            return job

        return self._run_transaction(accept)

    def current_generation(self, uid: str) -> ContentGenerationJob | None:
        candidates = [
            ContentGenerationJob.model_validate(data)
            for _, data in self._jobs(None)
            if data.get("uid") == uid
            and data.get("status") in {
                ContentGenerationStatus.accepted.value,
                ContentGenerationStatus.generating.value,
            }
        ]
        return sorted(candidates, key=lambda item: item.created_at, reverse=True)[0] if candidates else None

    def generation_job(self, job_id: str) -> ContentGenerationJob:
        return ContentGenerationJob.model_validate(
            self._require(self._job_ref_by_id(job_id), "not_found")
        )

    def claim_next_job(self, worker_id: str, lease_seconds: int, now=None) -> ContentGenerationJob | None:
        claimed_at = self._time(now)
        lease_expires_at = (claimed_at + timedelta(seconds=lease_seconds)).isoformat()

        def claim(transaction):
            candidates = []
            for job_id, data in self._jobs(transaction):
                status = data.get("status")
                expired = status == ContentGenerationStatus.generating.value and self._lease_expired(
                    data.get("lease_expires_at"), claimed_at
                )
                if status == ContentGenerationStatus.accepted.value or expired:
                    candidates.append((job_id, data))
            if not candidates:
                return None
            job_id, data = sorted(candidates, key=lambda item: item[1].get("created_at", ""))[0]
            data.update({
                "status": ContentGenerationStatus.generating.value,
                "stage": data.get("stage") or "writing",
                "lease_worker_id": worker_id,
                "lease_token": uuid.uuid4().hex,
                "lease_expires_at": lease_expires_at,
                "updated_at": claimed_at.isoformat(),
            })
            self._write_set(transaction, self._job_ref_by_id(job_id), data)
            return ContentGenerationJob.model_validate(data)

        return self._run_transaction(claim)

    def mark_stage(self, job_id: str, lease_token: str, stage: str) -> ContentGenerationJob:
        def mark(transaction):
            data = self._require(self._job_ref_by_id(job_id), "not_found", transaction)
            self._require_lease(data, lease_token)
            data.update({"stage": stage, "updated_at": datetime.now(timezone.utc).isoformat()})
            self._write_set(transaction, self._job_ref_by_id(job_id), data)
            return ContentGenerationJob.model_validate(data)

        return self._run_transaction(mark)

    def renew_lease(self, job_id: str, lease_token: str, lease_seconds: int) -> ContentGenerationJob:
        def renew(transaction):
            data = self._require(self._job_ref_by_id(job_id), "not_found", transaction)
            self._require_lease(data, lease_token)
            data.update({
                "lease_expires_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
                ).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            self._write_set(transaction, self._job_ref_by_id(job_id), data)
            return ContentGenerationJob.model_validate(data)

        return self._run_transaction(renew)

    def complete_generation(self, job_id: str, content: dict, lease_token: str) -> dict:
        def complete(transaction):
            job_ref = self._job_ref_by_id(job_id)
            data = self._require(job_ref, "not_found", transaction)
            job = ContentGenerationJob.model_validate(data)
            if job.status == ContentGenerationStatus.completed:
                return self._require(self._content_ref(job.content_id), "not_found", transaction)
            self._require_lease(data, lease_token)
            user_ref = self._user_ref(job.uid)
            user = self._require(user_ref, "not_found", transaction)
            now = datetime.now(timezone.utc).isoformat()
            record = {
                **content,
                "id": job.content_id,
                "owner_uid": job.uid,
                "author_id": job.uid,
                "visibility": "private",
                "source": "user_generation",
                "generation_job_id": job.id,
                "is_generated": True,
                "is_saved": True,
                "save_count": 1,
                "view_count": 0,
                "like_count": 0,
                "created_at": now,
                "updated_at": now,
            }
            self._write_set(transaction, self._content_ref(job.content_id), record)
            save_id = f"{job.uid}_{job.content_id}_save"
            self._write_set(transaction, self.db_client.collection("interactions").document(save_id), {
                "id": save_id,
                "user_id": job.uid,
                "content_id": job.content_id,
                "type": "save",
                "created_at": now,
            })
            counter_ref = self.db_client.collection("user_save_counters").document(job.uid)
            counter = self._data(self._read(transaction, counter_ref)) or {}
            self._write_set(transaction, counter_ref, {
                "id": job.uid,
                "user_id": job.uid,
                "saved_count": max(0, int(counter.get("saved_count") or 0)) + 1,
                "updated_at": now,
            })
            self._write_update(
                transaction,
                user_ref,
                debit_reserved_credit_fields(user, job.reserved_credit_amount),
            )
            data.update({
                "status": ContentGenerationStatus.completed.value,
                "stage": "completed",
                "error_code": None,
                "lease_worker_id": None,
                "lease_token": None,
                "lease_expires_at": None,
                "updated_at": now,
            })
            self._write_set(transaction, job_ref, data)
            return record

        return self._run_transaction(complete)

    def fail_generation(self, job_id: str, error_code: str, lease_token: str) -> ContentGenerationJob:
        def fail(transaction):
            job_ref = self._job_ref_by_id(job_id)
            data = self._require(job_ref, "not_found", transaction)
            job = ContentGenerationJob.model_validate(data)
            if job.status in {ContentGenerationStatus.completed, ContentGenerationStatus.failed}:
                return job
            self._require_lease(data, lease_token)
            user_ref = self._user_ref(job.uid)
            user = self._require(user_ref, "not_found", transaction)
            self._write_update(
                transaction,
                user_ref,
                release_credit_fields(user, job.reserved_credit_amount),
            )
            now = datetime.now(timezone.utc).isoformat()
            data.update({
                "status": ContentGenerationStatus.failed.value,
                "stage": "failed",
                "error_code": ContentGenerationErrorCode(error_code).value,
                "lease_worker_id": None,
                "lease_token": None,
                "lease_expires_at": None,
                "updated_at": now,
            })
            self._write_set(transaction, job_ref, data)
            return ContentGenerationJob.model_validate(data)

        return self._run_transaction(fail)

    def _active_job(self, uid, transaction):
        for _, data in self._jobs(transaction):
            if data.get("uid") == uid and data.get("status") in {
                ContentGenerationStatus.accepted.value,
                ContentGenerationStatus.generating.value,
            }:
                return data
        return None

    def _jobs(self, transaction):
        if hasattr(self.db_client, "collections"):
            return [
                (job_id, dict(data))
                for job_id, data in self.db_client.collections.get("content_generation_jobs", {}).items()
            ]
        query = self.db_client.collection("content_generation_jobs")
        snapshots = transaction.get(query) if transaction is not None else query.get()
        return [(snapshot.id, snapshot.to_dict()) for snapshot in snapshots]

    def _job_ref(self, uid, key):
        digest = hashlib.sha256(f"{uid}:{key}".encode()).hexdigest()
        return self.db_client.collection("content_generation_jobs").document(digest)

    def _job_ref_by_id(self, job_id):
        return self.db_client.collection("content_generation_jobs").document(job_id)

    def _user_ref(self, uid):
        return self.db_client.collection("users").document(uid)

    def _content_ref(self, content_id):
        return self.db_client.collection("generated_content").document(content_id)

    @staticmethod
    def _data(snapshot):
        return snapshot.to_dict() if snapshot and snapshot.exists else None

    def _require(self, ref, error, transaction=None):
        data = self._data(self._read(transaction, ref))
        if not data:
            self._reject(error)
        return data

    @staticmethod
    def _read(transaction, ref):
        return transaction.get(ref) if transaction is not None else ref.get()

    @staticmethod
    def _write_set(transaction, ref, data):
        transaction.set(ref, data) if transaction is not None else ref.set(data)

    @staticmethod
    def _write_update(transaction, ref, data):
        transaction.update(ref, data) if transaction is not None else ref.update(data)

    def _run_transaction(self, callback):
        runner = getattr(self.db_client, "run_transaction", None)
        if callable(runner):
            return runner(callback)
        factory = getattr(self.db_client, "transaction", None)
        if callable(factory):
            from firebase_admin import firestore
            return firestore.transactional(callback)(factory())
        lock = getattr(self.db_client, "_lock", None)
        with lock if lock is not None else nullcontext():
            return callback(None)

    @staticmethod
    def _time(value):
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @classmethod
    def _lease_expired(cls, value, now):
        return not value or cls._time(value) <= now

    @staticmethod
    def _require_lease(data, lease_token):
        if data.get("status") != ContentGenerationStatus.generating.value or data.get("lease_token") != lease_token:
            raise ContentGenerationRepositoryError("stale_lease")

    @staticmethod
    def _reject(code):
        raise ContentGenerationRepositoryError(code)
