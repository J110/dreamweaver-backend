#!/usr/bin/env python3
import signal
import socket
import threading

from app.config import get_settings
from app.dependencies import get_db_client
from app.services.characters.generator import CharacterGenerator
from app.services.characters.repository import CharacterRepository
from app.services.characters.worker import CharacterWorker


def main() -> int:
    try:
        settings = get_settings()
        worker = CharacterWorker(
            CharacterRepository(get_db_client()),
            CharacterGenerator(),
            settings.character_media_dir,
            worker_id=socket.gethostname(),
        )
    except Exception:
        return 1

    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    return run_loop(worker, stopping)


def run_loop(worker, stopping: threading.Event, idle_seconds: int = 2) -> int:
    while not stopping.is_set():
        try:
            did_cleanup = worker.run_cleanup_once()
        except Exception:
            did_cleanup = False
        try:
            did_orphan_cleanup = not did_cleanup and worker.run_orphan_cleanup_once()
        except Exception:
            did_orphan_cleanup = False
        try:
            did_work = did_cleanup or did_orphan_cleanup or worker.run_once()
        except Exception:
            did_work = False
        if not did_work:
            stopping.wait(idle_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
