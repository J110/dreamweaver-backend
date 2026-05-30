"""Bounded-time fal_client.subscribe + balance-exhaustion detection.

fal_client.subscribe polls fal-ai job status over HTTP. If the remote
job never completes the call blocks forever — there is no built-in
overall timeout. This wraps it in a ThreadPoolExecutor to enforce a
total wall-clock budget, plus retries transient failures.

fal-ai returns 403 with body "Exhausted balance" when the account
balance runs out. We translate that into FalBalanceExhausted so
callers can mark the item as a balance-exhausted skip (not a generic
failure) and the daily email surfaces the top-up link.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FTimeoutError
import time

FAL_TOPUP_URL = "https://fal.ai/dashboard/billing"
BALANCE_EXHAUSTED_MARKER = "FAL_BALANCE_EXHAUSTED"


class FalBalanceExhausted(RuntimeError):
    """fal-ai account balance exhausted. Top up at fal.ai/dashboard/billing."""

    def __init__(self, detail: str = ""):
        msg = f"{BALANCE_EXHAUSTED_MARKER} fal-ai balance exhausted - top up at {FAL_TOPUP_URL}"
        if detail:
            msg += f" (detail: {detail})"
        super().__init__(msg)


def is_balance_exhausted_response(exc: BaseException) -> bool:
    """True iff `exc` is a fal-ai 403 whose body indicates an exhausted balance."""
    try:
        import httpx
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 403:
            body = exc.response.text or ""
            if "Exhausted balance" in body:
                return True
            low = body.lower()
            if "balance" in low and "exhaust" in low:
                return True
    except Exception:
        pass
    s = str(exc)
    return "Exhausted balance" in s or BALANCE_EXHAUSTED_MARKER in s


def _balance_detail(exc: BaseException) -> str:
    try:
        import httpx
        if isinstance(exc, httpx.HTTPStatusError):
            return (exc.response.text or "")[:200]
    except Exception:
        pass
    return str(exc)[:200]


def safe_upload_file(file_path) -> str:
    """fal_client.upload_file with balance-exhaustion detection."""
    import fal_client
    try:
        return fal_client.upload_file(str(file_path))
    except Exception as e:
        if is_balance_exhausted_response(e):
            raise FalBalanceExhausted(_balance_detail(e)) from e
        raise


def safe_subscribe(endpoint, arguments, *, with_logs: bool = False,
                   timeout: float = 600, attempts: int = 3,
                   start_timeout: float = 60, client_timeout: float = 120,
                   **extra):
    import fal_client
    last_err = None
    for i in range(attempts):
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(
                fal_client.subscribe, endpoint,
                arguments=arguments, with_logs=with_logs,
                start_timeout=start_timeout, client_timeout=client_timeout,
                **extra,
            )
            try:
                return fut.result(timeout=timeout)
            except _FTimeoutError:
                last_err = TimeoutError(
                    f"fal_client.subscribe exceeded {timeout}s "
                    f"(endpoint={endpoint}, attempt={i+1}/{attempts})"
                )
                print(f"  WARN {last_err}", flush=True)
                fut.cancel()
            except Exception as e:
                if is_balance_exhausted_response(e):
                    raise FalBalanceExhausted(_balance_detail(e)) from e
                last_err = e
                print(
                    f"  WARN fal_client.subscribe attempt {i+1}/{attempts} "
                    f"failed: {type(e).__name__}: {e}",
                    flush=True,
                )
        if i < attempts - 1:
            time.sleep(min(5 * (i + 1), 30))
    raise RuntimeError(
        f"fal_client.subscribe failed after {attempts} attempts: {last_err}"
    )
