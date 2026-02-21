"""
File-backed data store that persists across process restarts.
Replaces Firestore with a JSON-file-backed dict store.
Used when no Firebase credentials are found.
"""

import uuid
import json
import os
import threading
from datetime import datetime
from typing import Optional
from pathlib import Path


def _json_serial(obj):
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


class LocalStore:
    """File-backed data store that mimics Firestore operations."""

    def __init__(self):
        self.collections: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

        # Persistent data directory
        self._data_dir = Path(__file__).parent.parent.parent / "data"
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._load_data()

    def _load_data(self):
        """Load from persistent data dir, falling back to seed data."""
        seed_dir = Path(__file__).parent.parent.parent / "seed_output"

        # For each collection, prefer persistent file over seed file
        collection_sources = {
            "content": ("content.json", "content.json", "id"),
            "subscriptions": ("subscriptions.json", "subscriptions.json", "tier"),
            "voices": ("voices.json", "voices.json", "id"),
        }

        for coll_name, (data_file, seed_file, key_field) in collection_sources.items():
            persistent_path = self._data_dir / data_file
            seed_path = seed_dir / seed_file

            if persistent_path.exists():
                # Use persistent data (survives restarts)
                with open(persistent_path) as f:
                    items = json.load(f)
                    self.collections[coll_name] = {
                        item[key_field]: item for item in items
                    }
                # Merge new seed items + backfill missing fields on existing items
                if seed_path.exists():
                    with open(seed_path) as f:
                        seed_items = json.load(f)
                        changed = False
                        # Fields that should always be updated from seed
                        # (frontend-owned fields that may improve over time)
                        SEED_PREFERRED_FIELDS = {"cover", "musicParams", "audio_variants"}
                        for item in seed_items:
                            item_id = item[key_field]
                            if item_id not in self.collections[coll_name]:
                                # New seed item — add it
                                self.collections[coll_name][item_id] = item
                                changed = True
                            else:
                                # Backfill missing fields from seed
                                existing = self.collections[coll_name][item_id]
                                for k, v in item.items():
                                    if k not in existing:
                                        existing[k] = v
                                        changed = True
                                    elif k in SEED_PREFERRED_FIELDS and v and existing.get(k) != v:
                                        # Overwrite stale values for seed-preferred fields
                                        existing[k] = v
                                        changed = True
                        if changed:
                            self._persist_collection(coll_name)
            elif seed_path.exists():
                # First boot: load seed data and persist it
                with open(seed_path) as f:
                    items = json.load(f)
                    self.collections[coll_name] = {
                        item[key_field]: item for item in items
                    }
                self._persist_collection(coll_name)

        # Load users, interactions, and tokens from persistent storage
        for coll_name in ["users", "interactions", "tokens"]:
            persistent_path = self._data_dir / f"{coll_name}.json"
            if persistent_path.exists():
                with open(persistent_path) as f:
                    items = json.load(f)
                    self.collections[coll_name] = {
                        item.get("id", item.get("uid", str(uuid.uuid4()))): item
                        for item in items
                    }
            elif coll_name not in self.collections:
                self.collections[coll_name] = {}

    def _persist_collection(self, name: str):
        """Write a collection to disk as JSON."""
        path = self._data_dir / f"{name}.json"
        items = list(self.collections.get(name, {}).values())
        with open(path, "w") as f:
            json.dump(items, f, indent=2, default=_json_serial)

    def _persist(self, collection_name: str):
        """Thread-safe persist after write operations."""
        try:
            self._persist_collection(collection_name)
        except Exception:
            pass  # Don't crash on write failure

    def collection(self, name: str) -> "CollectionRef":
        if name not in self.collections:
            self.collections[name] = {}
        return CollectionRef(self, name)


class CollectionRef:
    """Mimics Firestore collection reference."""

    def __init__(self, store: LocalStore, name: str):
        self._store = store
        self._data = store.collections[name]
        self._name = name
        self._filters = []
        self._order_by = None
        self._limit_val = None

    def document(self, doc_id: str) -> "DocumentRef":
        return DocumentRef(self._store, self._data, self._name, doc_id)

    def where(self, field: str, op: str, value) -> "CollectionRef":
        new_ref = CollectionRef(self._store, self._name)
        new_ref._filters = self._filters + [(field, op, value)]
        new_ref._order_by = self._order_by
        new_ref._limit_val = self._limit_val
        return new_ref

    def order_by(self, field: str, direction: str = "ASCENDING") -> "CollectionRef":
        new_ref = CollectionRef(self._store, self._name)
        new_ref._filters = self._filters
        new_ref._order_by = (field, direction)
        new_ref._limit_val = self._limit_val
        return new_ref

    def limit(self, count: int) -> "CollectionRef":
        new_ref = CollectionRef(self._store, self._name)
        new_ref._filters = self._filters
        new_ref._order_by = self._order_by
        new_ref._limit_val = count
        return new_ref

    def get(self) -> list["DocumentSnapshot"]:
        results = list(self._data.values())

        # Apply filters
        for field, op, value in self._filters:
            filtered = []
            for doc in results:
                doc_val = doc.get(field)
                if doc_val is None:
                    continue
                if op == "==" and doc_val == value:
                    filtered.append(doc)
                elif op == "!=" and doc_val != value:
                    filtered.append(doc)
                elif op == ">=" and doc_val >= value:
                    filtered.append(doc)
                elif op == "<=" and doc_val <= value:
                    filtered.append(doc)
                elif op == ">" and doc_val > value:
                    filtered.append(doc)
                elif op == "<" and doc_val < value:
                    filtered.append(doc)
                elif op == "in" and doc_val in value:
                    filtered.append(doc)
                elif op == "array_contains" and value in (doc_val if isinstance(doc_val, list) else []):
                    filtered.append(doc)
            results = filtered

        # Apply ordering
        if self._order_by:
            field, direction = self._order_by
            reverse = direction == "DESCENDING"
            results.sort(
                key=lambda d: d.get(field, ""),
                reverse=reverse,
            )

        # Apply limit
        if self._limit_val:
            results = results[: self._limit_val]

        return [DocumentSnapshot(doc.get("id", ""), doc) for doc in results]

    def stream(self):
        return self.get()

    def add(self, data: dict) -> "DocumentRef":
        doc_id = data.get("id", str(uuid.uuid4()))
        data["id"] = doc_id
        self._data[doc_id] = data
        self._store._persist(self._name)
        return DocumentRef(self._store, self._data, self._name, doc_id)


class DocumentRef:
    """Mimics Firestore document reference."""

    def __init__(self, store: LocalStore, collection_data: dict, collection_name: str, doc_id: str):
        self._store = store
        self._data = collection_data
        self._name = collection_name
        self._id = doc_id

    @property
    def id(self):
        return self._id

    def get(self) -> "DocumentSnapshot":
        doc = self._data.get(self._id, None)
        return DocumentSnapshot(self._id, doc)

    def set(self, data: dict, merge: bool = False):
        if merge and self._id in self._data:
            self._data[self._id].update(data)
        else:
            data["id"] = self._id
            self._data[self._id] = data
        self._store._persist(self._name)

    def update(self, data: dict):
        if self._id in self._data:
            self._data[self._id].update(data)
            self._store._persist(self._name)

    def delete(self):
        self._data.pop(self._id, None)
        self._store._persist(self._name)


class DocumentSnapshot:
    """Mimics Firestore document snapshot."""

    def __init__(self, doc_id: str, data: Optional[dict]):
        self.id = doc_id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> Optional[dict]:
        return self._data

    def get(self, field: str, default=None):
        if self._data is None:
            return default
        return self._data.get(field, default)


# ── Singleton ────────────────────────────────────────────────────

_local_store: Optional[LocalStore] = None


def get_local_store() -> LocalStore:
    """Get or create the singleton LocalStore instance."""
    global _local_store
    if _local_store is None:
        _local_store = LocalStore()
    return _local_store
