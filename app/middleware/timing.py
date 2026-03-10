"""Request timing middleware — records response time per request into an in-memory ring buffer."""

import time
from collections import deque
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

# Ring buffer: last N request records in memory
# Each entry: (timestamp, method, path, status_code, duration_ms)
MAX_BUFFER_SIZE = 10_000
_request_buffer: deque = deque(maxlen=MAX_BUFFER_SIZE)
_buffer_lock = Lock()

# Paths to skip (health checks, docs, static files)
_SKIP_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json", "/audio/pre-gen")


def get_request_buffer():
    """Return reference to the shared request buffer and its lock."""
    return _request_buffer, _buffer_lock


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip noisy paths
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        normalized = _normalize_path(path)

        with _buffer_lock:
            _request_buffer.append((
                time.time(),
                request.method,
                normalized,
                response.status_code,
                round(duration_ms, 1),
            ))

        return response


def _normalize_path(path: str) -> str:
    """Collapse dynamic path segments (UUIDs, hex IDs) into :id placeholders."""
    parts = path.split("/")
    normalized = []
    for part in parts:
        if len(part) > 8 and all(c in "0123456789abcdef-" for c in part.lower()):
            normalized.append(":id")
        else:
            normalized.append(part)
    return "/".join(normalized)
