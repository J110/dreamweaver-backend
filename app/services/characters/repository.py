import hashlib
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from app.schemas.character_schema import (
    CharacterQuote,
    CharacterRecord,
    GenerationErrorCode,
    GenerationJob,
    GenerationRequest,
    GenerationStatus,
)
from app.services.characters.domain import (
    generation_credit_cost,
    lowest_free_slot,
    quote_version_for_revision,
)
from app.utils.credits import (
    available_credit_total,
    debit_reserved_credit_fields,
    release_credit_fields,
    reserve_credit_fields,
)


class CharacterRepositoryError(ValueError):
    pass


class CharacterRepository:
    def __init__(self, db_client):
        self.db_client = db_client

    def quote_version(self, uid: str) -> str:
        counter = self._document_data(self._counter_ref(uid).get()) or self._default_counter()
        return quote_version_for_revision(counter.get("revision", 0))

    def quote_generation(
        self,
        uid: str,
        mode: str,
        target_character_id: str | None = None,
    ) -> CharacterQuote:
        user = self._require_document(self._user_ref(uid), "not_found")
        counter = self._document_data(self._counter_ref(uid).get()) or self._default_counter()
        slot_number = self._slot_for_generation(uid, mode, target_character_id, counter)
        credit_cost = generation_credit_cost(mode, slot_number)
        credits_before = available_credit_total(user)
        return CharacterQuote(
            slot_number=slot_number,
            credit_cost=credit_cost,
            credits_before=credits_before,
            credits_after=max(0, credits_before - credit_cost),
            quote_version=quote_version_for_revision(counter.get("revision", 0)),
        )

    def accept_generation(
        self,
        uid: str,
        request: GenerationRequest,
        target_character_id: str | None = None,
    ) -> GenerationJob:
        job_ref = self._job_ref(uid, request.idempotency_key)

        def accept(transaction):
            existing = self._document_data(self._read(transaction, job_ref))
            if existing:
                return GenerationJob.model_validate(existing)

            user_ref = self._user_ref(uid)
            user = self._require_document(user_ref, "not_found", transaction)
            counter_ref = self._counter_ref(uid)
            counter = self._document_data(self._read(transaction, counter_ref)) or self._default_counter()
            quote_version = quote_version_for_revision(counter.get("revision", 0))
            if request.quote_version != quote_version:
                self._reject("stale_quote")
            slot_number = self._slot_for_generation(
                uid, mode="edit" if target_character_id else "create",
                target_character_id=target_character_id, counter=counter, transaction=transaction,
            )
            mode = "edit" if target_character_id else "create"
            credit_cost = generation_credit_cost(mode, slot_number)
            if user.get("credits_frozen"):
                self._reject("credits_frozen")
            if available_credit_total(user) < credit_cost:
                self._reject("insufficient_credits")

            try:
                reserved_fields = reserve_credit_fields(user, credit_cost)
            except ValueError:
                self._reject("insufficient_credits")
            self._write_update(transaction, user_ref, reserved_fields)

            reserved_slots = set(counter.get("reserved_slots", []))
            slot_reservations = self._slot_reservations(counter)
            if mode == "create":
                reserved_slots.add(slot_number)
                slot_reservations[str(slot_number)] = job_ref.id
            next_counter = {
                "occupied_slots": sorted(set(counter.get("occupied_slots", []))),
                "reserved_slots": sorted(reserved_slots),
                "slot_reservations": slot_reservations,
                "revision": int(counter.get("revision", 0)) + 1,
            }
            self._write_set(transaction, counter_ref, next_counter)
            character_id = target_character_id or uuid.uuid4().hex
            portrait_version = 1
            if target_character_id:
                portrait_version = int(
                    self._require_document(
                        self._character_ref(target_character_id), "not_found", transaction
                    ).get("version", 0)
                ) + 1
            job = GenerationJob(
                id=job_ref.id,
                uid=uid,
                mode=mode,
                status=GenerationStatus.accepted,
                quote_version=quote_version,
                idempotency_key=request.idempotency_key,
                slot_number=slot_number,
                reserved_credit_amount=credit_cost,
                reserved_slot_number=slot_number if mode == "create" else None,
                target_character_id=target_character_id,
                character_id=character_id,
                portrait_filename=f"{character_id}-v{portrait_version}.webp",
                created_at=datetime.now(timezone.utc).isoformat(),
                inputs=request.inputs,
            )
            self._write_set(transaction, job_ref, job.model_dump(mode="json"))
            return job

        return self._run_transaction(accept)

    def claim_next_job(
        self,
        worker_id: str,
        lease_seconds: int,
        now: datetime | str | None = None,
    ) -> GenerationJob | None:
        claimed_at = self._coerce_time(now)
        lease_expires_at = (claimed_at + timedelta(seconds=lease_seconds)).isoformat()

        def claim(transaction):
            candidates = []
            for job_id, job_data in self._generation_jobs(transaction):
                if job_data.get("kind") == "media_cleanup":
                    continue
                status = job_data.get("status")
                expired = status == GenerationStatus.generating.value and self._lease_expired(
                    job_data.get("lease_expires_at"), claimed_at
                )
                if status == GenerationStatus.accepted.value or expired:
                    candidates.append((job_id, job_data))
            if not candidates:
                return None
            job_id, job_data = sorted(candidates, key=lambda candidate: candidate[0])[0]
            job_data.update({
                "status": GenerationStatus.generating.value,
                "lease_worker_id": worker_id,
                "lease_expires_at": lease_expires_at,
            })
            self._write_set(transaction, self._job_ref_by_id(job_id), job_data)
            return GenerationJob.model_validate(job_data)

        return self._run_transaction(claim)

    def mark_stage(self, job_id: str, stage: str) -> GenerationJob:
        job_ref = self._job_ref_by_id(job_id)

        def mark(transaction):
            job_data = self._require_document(job_ref, "not_found", transaction)
            if job_data.get("status") != GenerationStatus.generating.value:
                self._reject("not_found")
            job_data["stage"] = stage
            self._write_set(transaction, job_ref, job_data)
            return GenerationJob.model_validate(job_data)

        return self._run_transaction(mark)

    def complete_generation(
        self,
        job_id: str,
        profile: dict,
        portrait_url: str,
        portrait_filename: str | None = None,
    ) -> CharacterRecord:
        job_ref = self._job_ref_by_id(job_id)

        def complete(transaction):
            job_data = self._require_document(job_ref, "not_found", transaction)
            job = GenerationJob.model_validate(job_data)
            if job.status == GenerationStatus.completed:
                return CharacterRecord.model_validate(
                    self._require_document(self._character_ref(job.character_id), "not_found", transaction)
                )
            if job.status not in {GenerationStatus.accepted, GenerationStatus.generating}:
                self._reject("not_found")

            user_ref = self._user_ref(job.uid)
            user = self._require_document(user_ref, "not_found", transaction)
            counter_ref = self._counter_ref(job.uid)
            counter = self._document_data(self._read(transaction, counter_ref)) or self._default_counter()
            character_id = job.character_id or job.target_character_id or uuid.uuid4().hex
            character_ref = self._character_ref(character_id)
            if job.mode == "edit":
                existing = self._require_document(character_ref, "not_found", transaction)
                record = CharacterRecord(
                    id=character_id,
                    uid=job.uid,
                    slot_number=job.slot_number,
                    version=int(existing.get("version", 0)) + 1,
                    profile=profile,
                    portrait_url=portrait_url,
                    portrait_filename=portrait_filename or job.portrait_filename,
                )
            else:
                record = CharacterRecord(
                    id=character_id,
                    uid=job.uid,
                    slot_number=job.slot_number,
                    version=1,
                    profile=profile,
                    portrait_url=portrait_url,
                    portrait_filename=portrait_filename or job.portrait_filename,
                )

            self._write_set(transaction, character_ref, record.model_dump())
            self._write_update(
                transaction,
                user_ref,
                debit_reserved_credit_fields(user, job.reserved_credit_amount),
            )
            reserved_slots = set(counter.get("reserved_slots", []))
            slot_reservations = self._slot_reservations(counter)
            if (
                job.reserved_slot_number is not None
                and slot_reservations.get(str(job.reserved_slot_number)) == job.id
            ):
                reserved_slots.discard(job.reserved_slot_number)
                slot_reservations.pop(str(job.reserved_slot_number))
            occupied_slots = set(counter.get("occupied_slots", []))
            occupied_slots.add(job.slot_number)
            self._write_set(transaction, counter_ref, {
                "occupied_slots": sorted(occupied_slots),
                "reserved_slots": sorted(reserved_slots),
                "slot_reservations": slot_reservations,
                "revision": int(counter.get("revision", 0)) + 1,
            })
            job_data.update({
                "status": GenerationStatus.completed.value,
                "character_id": character_id,
                "portrait_filename": portrait_filename or job.portrait_filename,
                "error_code": None,
                "stage": "completed",
                "lease_worker_id": None,
                "lease_expires_at": None,
            })
            self._write_set(transaction, job_ref, job_data)
            return record

        return self._run_transaction(complete)

    def fail_generation(self, job_id: str, error_code: str) -> GenerationJob:
        job_ref = self._job_ref_by_id(job_id)

        def fail(transaction):
            job_data = self._require_document(job_ref, "not_found", transaction)
            job = GenerationJob.model_validate(job_data)
            if job.status not in {GenerationStatus.accepted, GenerationStatus.generating}:
                return job
            user_ref = self._user_ref(job.uid)
            user = self._require_document(user_ref, "not_found", transaction)
            counter_ref = self._counter_ref(job.uid)
            counter = self._document_data(self._read(transaction, counter_ref)) or self._default_counter()
            self._write_update(
                transaction,
                user_ref,
                release_credit_fields(user, job.reserved_credit_amount),
            )
            reserved_slots = set(counter.get("reserved_slots", []))
            slot_reservations = self._slot_reservations(counter)
            if (
                job.reserved_slot_number is not None
                and slot_reservations.get(str(job.reserved_slot_number)) == job.id
            ):
                reserved_slots.discard(job.reserved_slot_number)
                slot_reservations.pop(str(job.reserved_slot_number))
            self._write_set(transaction, counter_ref, {
                "occupied_slots": sorted(set(counter.get("occupied_slots", []))),
                "reserved_slots": sorted(reserved_slots),
                "slot_reservations": slot_reservations,
                "revision": int(counter.get("revision", 0)) + 1,
            })
            job_data.update({
                "status": GenerationStatus.failed.value,
                "error_code": GenerationErrorCode(error_code).value,
                "stage": "failed",
                "lease_worker_id": None,
                "lease_expires_at": None,
            })
            self._write_set(transaction, job_ref, job_data)
            return GenerationJob.model_validate(job_data)

        return self._run_transaction(fail)

    def claim_next_media_cleanup(
        self,
        worker_id: str,
        lease_seconds: int,
        now: datetime | str | None = None,
    ) -> dict | None:
        claimed_at = self._coerce_time(now)
        lease_expires_at = (claimed_at + timedelta(seconds=lease_seconds)).isoformat()

        def claim(transaction):
            candidates = []
            for job_id, cleanup in self._generation_jobs(transaction):
                if cleanup.get("kind") != "media_cleanup":
                    continue
                status = cleanup.get("status")
                expired = status == "media_cleanup_generating" and self._lease_expired(
                    cleanup.get("lease_expires_at"), claimed_at
                )
                if status == "media_cleanup_pending" or expired:
                    candidates.append((job_id, cleanup))
            if not candidates:
                return None
            job_id, cleanup = sorted(candidates, key=lambda candidate: candidate[0])[0]
            cleanup.update({
                "status": "media_cleanup_generating",
                "lease_worker_id": worker_id,
                "lease_expires_at": lease_expires_at,
            })
            self._write_set(transaction, self._job_ref_by_id(job_id), cleanup)
            return cleanup

        return self._run_transaction(claim)

    def complete_media_cleanup(self, cleanup_id: str) -> None:
        cleanup_ref = self._job_ref_by_id(cleanup_id)

        def complete(transaction):
            cleanup = self._require_document(cleanup_ref, "not_found", transaction)
            if cleanup.get("kind") != "media_cleanup":
                self._reject("not_found")
            cleanup.update({
                "status": "completed",
                "lease_worker_id": None,
                "lease_expires_at": None,
            })
            self._write_set(transaction, cleanup_ref, cleanup)

        self._run_transaction(complete)

    def delete_character(self, uid: str, character_id: str) -> None:
        def delete(transaction):
            character_ref = self._character_ref(character_id)
            character = self._require_document(character_ref, "not_found", transaction)
            if character.get("uid") != uid:
                self._reject("forbidden")
            counter_ref = self._counter_ref(uid)
            counter = self._document_data(self._read(transaction, counter_ref)) or self._default_counter()
            occupied_slots = set(counter.get("occupied_slots", []))
            occupied_slots.discard(character["slot_number"])
            self._write_delete(transaction, character_ref)
            self._write_set(transaction, counter_ref, {
                "occupied_slots": sorted(occupied_slots),
                "reserved_slots": sorted(set(counter.get("reserved_slots", []))),
                "slot_reservations": self._slot_reservations(counter),
                "revision": int(counter.get("revision", 0)) + 1,
            })
            self._write_set(transaction, self._cleanup_ref(character_id), {
                "id": f"cleanup-{character_id}",
                "kind": "media_cleanup",
                "status": "media_cleanup_pending",
                "character_id": character_id,
                "portrait_url": character.get("portrait_url"),
            })

        self._run_transaction(delete)

    def _slot_for_generation(
        self,
        uid: str,
        mode: str,
        target_character_id: str | None,
        counter: dict,
        transaction=None,
    ) -> int:
        if mode == "edit":
            if not target_character_id:
                self._reject("not_found")
            character = self._require_document(
                self._character_ref(target_character_id), "not_found", transaction
            )
            if character.get("uid") != uid:
                self._reject("forbidden")
            return int(character["slot_number"])
        if mode != "create":
            self._reject("not_found")
        slot_number = lowest_free_slot(
            list(counter.get("occupied_slots", [])),
            list(counter.get("reserved_slots", [])) + [
                int(slot) for slot in self._slot_reservations(counter)
            ],
        )
        if slot_number is None:
            self._reject("no_slots")
        return slot_number

    def _run_transaction(self, callback):
        runner = getattr(self.db_client, "run_transaction", None)
        if callable(runner):
            return runner(callback)
        transaction_factory = getattr(self.db_client, "transaction", None)
        if callable(transaction_factory):
            transaction = transaction_factory()
            try:
                from firebase_admin import firestore
                return firestore.transactional(callback)(transaction)
            except ImportError:
                return callback(transaction)
        lock = getattr(self.db_client, "_lock", None)
        collections = getattr(self.db_client, "collections", None)
        if lock is not None and isinstance(collections, dict):
            with lock:
                snapshot = deepcopy(collections)
                try:
                    return callback(None)
                except Exception:
                    collection_names = set(collections) | set(snapshot)
                    collections.clear()
                    collections.update(snapshot)
                    persist = getattr(self.db_client, "_persist_collection", None)
                    if callable(persist):
                        for collection_name in collection_names:
                            persist(collection_name)
                    raise
        return callback(None)

    def _read(self, transaction, document_ref):
        if transaction is not None:
            return document_ref.get(transaction=transaction)
        return document_ref.get()

    @staticmethod
    def _document_data(snapshot):
        return snapshot.to_dict() if snapshot.exists else None

    def _require_document(self, document_ref, error_code: str, transaction=None):
        snapshot = self._read(transaction, document_ref)
        data = self._document_data(snapshot)
        if data is None:
            self._reject(error_code)
        return data

    @staticmethod
    def _reject(error_code: str):
        raise CharacterRepositoryError(error_code)

    @staticmethod
    def _default_counter():
        return {
            "occupied_slots": [],
            "reserved_slots": [],
            "slot_reservations": {},
            "revision": 0,
        }

    @staticmethod
    def _slot_reservations(counter: dict) -> dict[str, str]:
        return {
            str(slot): job_id
            for slot, job_id in (counter.get("slot_reservations") or {}).items()
        }

    def _write_set(self, transaction, document_ref, data):
        if transaction is not None and callable(getattr(transaction, "set", None)):
            transaction.set(document_ref, data)
            return
        document_ref.set(data)

    def _write_update(self, transaction, document_ref, fields):
        if transaction is not None and callable(getattr(transaction, "update", None)):
            transaction.update(document_ref, fields)
            return
        document_ref.update(fields)

    def _write_delete(self, transaction, document_ref):
        if transaction is not None and callable(getattr(transaction, "delete", None)):
            transaction.delete(document_ref)
            return
        document_ref.delete()

    def _user_ref(self, uid):
        return self.db_client.collection("users").document(uid)

    def _counter_ref(self, uid):
        return self.db_client.collection("character_slot_counters").document(uid)

    def _character_ref(self, character_id):
        return self.db_client.collection("characters").document(character_id)

    def _job_ref(self, uid, idempotency_key):
        digest = hashlib.sha256(f"{uid}\0{idempotency_key}".encode()).hexdigest()
        return self.db_client.collection("character_generation_jobs").document(digest)

    def _job_ref_by_id(self, job_id):
        return self.db_client.collection("character_generation_jobs").document(job_id)

    def _cleanup_ref(self, character_id):
        return self.db_client.collection("character_generation_jobs").document(
            f"cleanup-{character_id}"
        )

    def _generation_jobs(self, transaction) -> list[tuple[str, dict]]:
        collections = getattr(self.db_client, "collections", None)
        if isinstance(collections, dict):
            return [
                (job_id, deepcopy(job))
                for job_id, job in collections.get("character_generation_jobs", {}).items()
            ]
        collection = self.db_client.collection("character_generation_jobs")
        try:
            snapshots = collection.stream(transaction=transaction)
        except TypeError:
            snapshots = collection.stream()
        return [(snapshot.id, snapshot.to_dict()) for snapshot in snapshots]

    @staticmethod
    def _coerce_time(value: datetime | str | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    @classmethod
    def _lease_expired(cls, lease_expires_at: str | None, now: datetime) -> bool:
        if not lease_expires_at:
            return True
        return cls._coerce_time(lease_expires_at) <= now
