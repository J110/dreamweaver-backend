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
    while not stopping.is_set():
        did_work = worker.run_cleanup_once() or worker.run_once()
        if not did_work:
            stopping.wait(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
