import hashlib
import uuid
from copy import deepcopy

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
                inputs=request.inputs,
            )
            self._write_set(transaction, job_ref, job.model_dump(mode="json"))
            return job

        return self._run_transaction(accept)

    def complete_generation(
        self,
        job_id: str,
        profile: dict,
        portrait_url: str,
    ) -> CharacterRecord:
        job_ref = self._job_ref_by_id(job_id)

        def complete(transaction):
            job_data = self._require_document(job_ref, "not_found", transaction)
            job = GenerationJob.model_validate(job_data)
            if job.status == GenerationStatus.completed:
                return CharacterRecord.model_validate(
                    self._require_document(self._character_ref(job.character_id), "not_found", transaction)
                )
            if job.status != GenerationStatus.accepted:
                self._reject("not_found")

            user_ref = self._user_ref(job.uid)
            user = self._require_document(user_ref, "not_found", transaction)
            counter_ref = self._counter_ref(job.uid)
            counter = self._document_data(self._read(transaction, counter_ref)) or self._default_counter()
            character_id = job.target_character_id or uuid.uuid4().hex
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
                )
            else:
                record = CharacterRecord(
                    id=character_id,
                    uid=job.uid,
                    slot_number=job.slot_number,
                    version=1,
                    profile=profile,
                    portrait_url=portrait_url,
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
                "error_code": None,
            })
            self._write_set(transaction, job_ref, job_data)
            return record

        return self._run_transaction(complete)

    def fail_generation(self, job_id: str, error_code: str) -> GenerationJob:
        job_ref = self._job_ref_by_id(job_id)

        def fail(transaction):
            job_data = self._require_document(job_ref, "not_found", transaction)
            job = GenerationJob.model_validate(job_data)
            if job.status != GenerationStatus.accepted:
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
            })
            self._write_set(transaction, job_ref, job_data)
            return GenerationJob.model_validate(job_data)

        return self._run_transaction(fail)

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
