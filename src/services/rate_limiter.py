"""Rate limiting service for managing API call frequencies."""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

RATE_LIMIT_WINDOW_SECONDS = 60
DEFAULT_REDDIT_RPM = 90
DEFAULT_GEMINI_RPM = 12

_CAPACITY_BY_SERVICE: dict[str, int] = {
    "reddit": 95,
    "gemini": 14,
}


class RateLimiter:
    """Manages rate limiting for different API services."""

    def __init__(self):
        self._call_history: dict[str, list[float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, service: str) -> asyncio.Lock:
        if service not in self._locks:
            self._locks[service] = asyncio.Lock()
        return self._locks[service]

    def _prune_expired_calls(self, service: str) -> None:
        """Remove call timestamps older than the rate limit window."""
        if service not in self._call_history:
            self._call_history[service] = []
            return

        cutoff = time.time() - RATE_LIMIT_WINDOW_SECONDS
        self._call_history[service] = [
            ts for ts in self._call_history[service] if ts > cutoff
        ]

    def _record_call(self, service: str) -> None:
        self._call_history[service].append(time.time())

    def _calls_in_window(self, service: str) -> int:
        return len(self._call_history.get(service, []))

    async def _wait_if_needed(self, service: str, requests_per_minute: int) -> None:
        """Wait until a slot is available, then record the call."""
        async with self._get_lock(service):
            self._prune_expired_calls(service)

            if self._calls_in_window(service) >= requests_per_minute:
                oldest_call = min(self._call_history[service])
                wait_time = RATE_LIMIT_WINDOW_SECONDS - (time.time() - oldest_call)

                if wait_time > 0:
                    logger.info(
                        f"{service.capitalize()} rate limit reached. "
                        f"Waiting {wait_time:.1f}s..."
                    )
                    await asyncio.sleep(wait_time)
                    self._prune_expired_calls(service)

            self._record_call(service)

    async def wait_for_reddit_limit(
        self, requests_per_minute: int = DEFAULT_REDDIT_RPM
    ) -> None:
        await self._wait_if_needed("reddit", requests_per_minute)

    async def wait_for_gemini_limit(
        self, requests_per_minute: int = DEFAULT_GEMINI_RPM
    ) -> None:
        await self._wait_if_needed("gemini", requests_per_minute)

    async def wait_between_batches(self, delay_seconds: float) -> None:
        """Pause between batches of requests."""
        if delay_seconds > 0:
            logger.info(f"Batch delay: {delay_seconds}s...")
            await asyncio.sleep(delay_seconds)

    def get_current_usage(self, service: str) -> dict[str, int]:
        """Return current API usage stats without mutating call history."""
        history = self._call_history.get(service, [])
        cutoff = time.time() - RATE_LIMIT_WINDOW_SECONDS
        calls_last_minute = sum(1 for ts in history if ts > cutoff)

        capacity = _CAPACITY_BY_SERVICE.get(service, 0)
        remaining = max(0, capacity - calls_last_minute)

        return {
            "calls_last_minute": calls_last_minute,
            "remaining_capacity": remaining,
        }


rate_limiter = RateLimiter()
