#!/usr/bin/env python3
import signal
import socket
import threading

from app.config import get_settings
from app.dependencies import get_db_client
from app.services.content_generation.generator import ContentGenerator
from app.services.content_generation.repository import ContentGenerationRepository
from app.services.content_generation.worker import ContentGenerationWorker


def main() -> int:
    settings = get_settings()
    worker = ContentGenerationWorker(
        ContentGenerationRepository(get_db_client()),
        ContentGenerator(),
        settings.content_generation_media_dir,
        socket.gethostname(),
        settings.content_generation_worker_lease_seconds,
    )
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    while not stopping.is_set():
        if not worker.run_once():
            stopping.wait(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

