import os
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status


_buckets: dict[str, deque[float]] = defaultdict(deque)


def rate_limit(name: str, limit: int = 10, window_seconds: int = 60) -> Callable[[Request], None]:
    async def dependency(request: Request) -> None:
        if os.getenv("TESTING") == "True":
            return

        client_host = request.client.host if request.client else "unknown"
        key = f"{name}:{client_host}"
        now = time.monotonic()
        bucket = _buckets[key]

        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()

        if len(bucket) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Try again later.",
            )

        bucket.append(now)

    return dependency
