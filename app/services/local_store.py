"""
File-backed data store that persists across process restarts.
Replaces Firestore with a JSON-file-backed dict store.
Used when no Firebase credentials are found.

Content collection persistence (post-2026-04-29 refactor):
  - Per-content files at data/<type>[_hi]/<id>.json are the SOURCE OF TRUTH
  - data/content.json and seed_output/content.json are DERIVED SNAPSHOTS,
    rebuilt at boot and admin-reload by walking the per-content dirs
  - Runtime mutations route through _persist_content_item (per-content file
    write), NOT through the snapshot
  - See docs/superpowers/specs/2026-04-29-content-json-refactor.md
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


def _json_serial(obj):
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def _atomic_write_json(path: Path, data, strip_subtype: bool = False) -> None:
    """Atomically write JSON: tempfile + fsync + os.replace.

    Guarantees readers never observe a partially-written file. os.replace is
    atomic on POSIX as long as src and dst are on the same filesystem (both
    are under /opt/dreamweaver-backend/ in production).

    If strip_subtype=True and data is a dict containing a 'subtype' key, the
    field is removed before writing — per Open Question 3 of the content.json
    refactor spec, subtype is walker-stamped from directory placement and
    must not be persisted on disk.
    """
    if strip_subtype and isinstance(data, dict) and "subtype" in data:
        data = {k: v for k, v in data.items() if k != "subtype"}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=_json_serial)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# Per-content directory layout (spec §2c). Each tuple is:
#   (subdir_under_data, default_type, default_subtype, lang)
# Lang is fully directory-derived (every dir has a definite lang). Subtype
# is walker-stamped from this table — never read from per-content files.
PER_CONTENT_DIRS = [
    ("stories",          "story",       None,           "en"),
    ("stories_hi",       "story",       None,           "hi"),
    ("long_stories",     "long_story",  None,           "en"),
    ("long_stories_hi",  "long_story",  None,           "hi"),
    ("lullabies",        "song",        "lullaby",      "en"),
    ("lullabies_hi",     "song",        "lullaby",      "hi"),
    ("silly_songs",      "song",        "silly_song",   "en"),
    ("silly_songs_hi",   "song",        "silly_song",   "hi"),
    ("funny_shorts",     "song",        "funny_short",  "en"),
    ("funny_shorts_hi",  "song",        "funny_short",  "hi"),
    ("poems",            "poem",        None,           "en"),
    ("poems_hi",         "poem",        None,           "hi"),
]


def _content_target_dir(data_dir: Path, item: dict) -> Optional[Path]:
    """Derive the per-content target directory for a content item.

    Looks at item's type / subtype / lang and returns the matching directory
    path under data_dir, or None if no rule matches (caller should warn).
    Items with type=song and missing subtype are treated as lullabies (legacy
    behavior — see CLAUDE.md §"content.json Structure" subtype semantics).
    """
    typ = item.get("type")
    subtype = item.get("subtype")
    lang = item.get("lang") or item.get("language") or "en"
    suffix = "_hi" if lang == "hi" else ""

    if typ == "story":
        return data_dir / f"stories{suffix}"
    if typ == "long_story":
        return data_dir / f"long_stories{suffix}"
    if typ == "poem":
        return data_dir / f"poems{suffix}"
    if typ == "song":
        if subtype == "silly_song":
            return data_dir / f"silly_songs{suffix}"
        if subtype == "funny_short":
            return data_dir / f"funny_shorts{suffix}"
        # subtype == "lullaby" or absent (legacy)
        return data_dir / f"lullabies{suffix}"
    return None


class LocalStore:
    """File-backed data store that mimics Firestore operations."""

    def __init__(self):
        self.collections: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

        # Persistent data directory
        self._data_dir = Path(__file__).parent.parent.parent / "data"
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Seed data tracking for hot-reload
        self._seed_dir = Path(__file__).parent.parent.parent / "seed_output"
        self._seed_content_path = self._seed_dir / "content.json"
        self._last_seed_mtime: float = 0.0

        self._load_data()
        self._update_seed_mtime()

    def _load_data(self):
        """Load all collections from disk.

        Content collection: walk per-content directories (spec §2c) to build
        in-memory state, then write derived snapshots (data/content.json and
        seed_output/content.json). Per-content files are the source of truth.

        Other collections (subscriptions, voices, users, interactions, tokens,
        blog_*): unchanged — load from data/<name>.json snapshot, fall back
        to seed.
        """
        # ── Content: walker-driven, per spec §2c ────────────────────────────
        self._load_content()

        # ── Subscriptions, voices: snapshot-only, with seed fallback ────────
        seed_dir = Path(__file__).parent.parent.parent / "seed_output"
        for coll_name, (data_file, seed_file, key_field) in {
            "subscriptions": ("subscriptions.json", "subscriptions.json", "tier"),
            "voices": ("voices.json", "voices.json", "id"),
        }.items():
            persistent_path = self._data_dir / data_file
            seed_path = seed_dir / seed_file
            if persistent_path.exists():
                with open(persistent_path) as f:
                    items = json.load(f)
                    self.collections[coll_name] = {item[key_field]: item for item in items}
            elif seed_path.exists():
                with open(seed_path) as f:
                    items = json.load(f)
                    self.collections[coll_name] = {item[key_field]: item for item in items}
                self._persist_collection(coll_name)

        # ── Users, interactions, tokens, blog data: persistent only ─────────
        for coll_name in ["users", "interactions", "tokens", "blog_posts", "blog_comments"]:
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

    def _load_content(self) -> None:
        """Build the content collection from per-content files (spec §2c).

        Pre-migration safeguard: if NO per-content directories exist yet,
        fall back to loading from data/content.json snapshot and log loudly.
        Once any per-content dir has files, the walker is authoritative.
        """
        items_by_id = self._walk_per_content()

        any_per_content = any(
            (self._data_dir / subdir).is_dir()
            and any((self._data_dir / subdir).glob("*.json"))
            for subdir, _, _, _ in PER_CONTENT_DIRS
        )

        if not any_per_content:
            # Pre-migration fallback. Loud — this is the development /
            # transition window between this code landing and the backfill
            # script running. Once backfill creates per-content files,
            # this branch goes silent and the walker is authoritative.
            snapshot = self._data_dir / "content.json"
            if snapshot.exists():
                logger.warning(
                    "PRE-MIGRATION FALLBACK: no per-content directories found, "
                    "loading content collection from data/content.json snapshot. "
                    "Run scripts/migrate_content_to_per_file.py before going live."
                )
                with open(snapshot) as f:
                    items = json.load(f)
                items_by_id = {item["id"]: item for item in items}
            else:
                logger.warning(
                    "no per-content files and no content.json snapshot — "
                    "content collection is empty"
                )

        self.collections["content"] = items_by_id
        if items_by_id:
            self._write_snapshots()

    def _walk_per_content(self) -> dict[str, dict]:
        """Walk every per-content directory; build item-id → item dict.

        Stamps type / subtype / lang from directory placement (per OQ3:
        directory is source of truth, on-disk subtype field is ignored
        with a warning). Skips corrupt JSON files with a logged warning
        instead of crashing the boot.
        """
        items_by_id: dict[str, dict] = {}
        skipped: list[tuple[Path, str]] = []
        for subdir, default_type, default_subtype, default_lang in PER_CONTENT_DIRS:
            d = self._data_dir / subdir
            if not d.is_dir():
                continue
            for fp in sorted(d.glob("*.json")):
                if fp.name.endswith(".json.tmp"):
                    continue  # in-flight atomic-write tempfile
                try:
                    entry = json.loads(fp.read_text(encoding="utf-8"))
                except Exception as e:
                    skipped.append((fp, str(e)))
                    continue

                # Subtype: walker-stamped, never on-disk (OQ3).
                if "subtype" in entry and entry.get("subtype") != default_subtype:
                    logger.warning(
                        "subtype field present in %s — ignoring on-disk value %r, "
                        "stamping directory-derived value %r",
                        fp, entry.get("subtype"), default_subtype,
                    )
                entry["type"] = default_type
                entry["subtype"] = default_subtype  # may be None for stories/poems/long_stories

                # Lang: directory-derived. Warn on mismatch; directory wins.
                if entry.get("lang") not in (None, default_lang):
                    logger.warning(
                        "lang mismatch for %s: file says %s, dir says %s — using dir",
                        fp, entry.get("lang"), default_lang,
                    )
                entry["lang"] = default_lang
                entry["language"] = default_lang

                item_id = entry.get("id") or fp.stem
                entry["id"] = item_id
                if item_id in items_by_id:
                    logger.warning("duplicate id %s in %s (last-write-wins)", item_id, fp)
                items_by_id[item_id] = entry

        if skipped:
            logger.warning(
                "skipped %d corrupt per-content files; first 5: %s",
                len(skipped), skipped[:5],
            )
        return items_by_id

    def _write_snapshots(self) -> None:
        """Atomically write derived content.json snapshots (spec §2e.1).

        Sorted by id for stable diffs. Writes both the runtime snapshot
        (data/content.json) and the seed snapshot (seed_output/content.json)
        — external readers (analytics.py, sync_seed_data.py, deploy_guard,
        the seed-mtime poller in app/main.py) consume one or the other.
        """
        items = sorted(
            self.collections.get("content", {}).values(),
            key=lambda x: x.get("id", ""),
        )
        for path in [self._data_dir / "content.json",
                     self._seed_dir / "content.json"]:
            try:
                _atomic_write_json(path, items)
            except Exception as e:
                # Snapshot write failure should not block readiness — the
                # in-memory store is already consistent. Log loudly so it's
                # visible in observability.
                logger.warning("snapshot write failed for %s: %s", path, e)

    def _update_seed_mtime(self):
        """Record the current mtime of seed content.json."""
        try:
            if self._seed_content_path.exists():
                self._last_seed_mtime = self._seed_content_path.stat().st_mtime
        except OSError:
            pass

    def has_seed_changed(self) -> bool:
        """Check if seed content.json has been modified since last load."""
        try:
            if self._seed_content_path.exists():
                return self._seed_content_path.stat().st_mtime > self._last_seed_mtime
        except OSError:
            pass
        return False

    def reload_content(self) -> dict:
        """Re-read the content collection from per-content files (spec §2c).

        Thread-safe. Walks data/<type>[_hi]/*.json directories, rebuilds
        in-memory state, writes derived snapshots atomically. Called by
        the admin reload endpoint and the background mtime poller.

        Subscriptions and voices are NOT reloaded here — they don't change
        at runtime. To pick up changes to those, restart the container.
        """
        with self._lock:
            old_count = len(self.collections.get("content", {}))
            self._load_content()
            self._update_seed_mtime()
            new_count = len(self.collections.get("content", {}))
            return {
                "previous_count": old_count,
                "current_count": new_count,
                "added": new_count - old_count,
                "reloaded_at": datetime.now().isoformat(),
            }

    def _persist_collection(self, name: str):
        """Atomically write a non-content collection to disk as JSON.

        Use only for collections OTHER than 'content' (subscriptions, voices,
        users, interactions, tokens, blog_*). The content collection has its
        own routing — see _persist_content_item (§2g.1) and _write_snapshots.
        """
        path = self._data_dir / f"{name}.json"
        items = list(self.collections.get(name, {}).values())
        _atomic_write_json(path, items)

    def _persist_content_item(self, item_id: str) -> None:
        """Write a single content item to its per-content file (spec §2g.1).

        Called from runtime mutation paths (like_count, save_count). Atomic
        write per §2e.1, with subtype stripped (OQ3 — subtype is walker-
        stamped, never on disk). Does NOT touch the data/content.json
        snapshot — snapshot regenerates at next admin-reload or boot.

        If the item is not in memory (e.g. it was just deleted), removes
        the per-content file too.
        """
        item = self.collections.get("content", {}).get(item_id)
        if item is None:
            self._delete_content_file(item_id)
            return
        target_dir = _content_target_dir(self._data_dir, item)
        if target_dir is None:
            logger.warning(
                "cannot route content item %s to per-content file: "
                "no rule for type=%r subtype=%r lang=%r",
                item_id, item.get("type"), item.get("subtype"), item.get("lang"),
            )
            return
        path = target_dir / f"{item_id}.json"
        _atomic_write_json(path, item, strip_subtype=True)

    def _delete_content_file(self, item_id: str) -> None:
        """Remove the per-content file for a deleted content item.

        Searches all 12 per-content directories (we can't always derive the
        target from in-memory state if the item is already gone). Idempotent —
        no error if the file doesn't exist.
        """
        for subdir, _, _, _ in PER_CONTENT_DIRS:
            path = self._data_dir / subdir / f"{item_id}.json"
            try:
                if path.exists():
                    path.unlink()
            except OSError as e:
                logger.warning("failed to delete %s: %s", path, e)

    def _persist(self, collection_name: str, doc_id: Optional[str] = None):
        """Thread-safe persist after write operations.

        For the content collection, routes to _persist_content_item (per-
        content file, §2g.1) when doc_id is provided. Falls back to
        snapshot-style write only when doc_id is unknown (shouldn't happen
        from the LocalStore API; defensive fallback).

        For all other collections, writes the collection snapshot atomically.
        """
        try:
            if collection_name == "content" and doc_id is not None:
                self._persist_content_item(doc_id)
            else:
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
        self._store._persist(self._name, doc_id)
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
        self._store._persist(self._name, self._id)

    def update(self, data: dict):
        if self._id in self._data:
            self._data[self._id].update(data)
            self._store._persist(self._name, self._id)

    def delete(self):
        self._data.pop(self._id, None)
        self._store._persist(self._name, self._id)


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
