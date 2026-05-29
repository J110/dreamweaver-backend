"""Platform-context middleware.

Detects the Flutter native wrapper from the User-Agent header (the
`DreamValleyApp/x.x` token the Flutter app injects via webview_flutter)
and sets a request-scoped contextvar that `is_premium()` reads.

This is the load-bearing half of the compliance gate: even with
PAYWALL_ENABLED=true on the backend, native-app requests are forced
premium via this signal until PAYWALL_NATIVE_ENABLED is flipped on
alongside a reviewed App Store build with corrected IAP + privacy
declarations.
"""

import re

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.utils.gating import set_native_app_flag


_NATIVE_UA = re.compile(r"DreamValleyApp/[\d.]+", re.IGNORECASE)


class PlatformContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ua = request.headers.get("user-agent", "") or ""
        set_native_app_flag(bool(_NATIVE_UA.search(ua)))
        return await call_next(request)
