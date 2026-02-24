"""
Reliable wrapper — retry decorator with exponential backoff and jitter.

Handles transient HTTP errors (429, 5xx), timeouts, and connection errors.
Inspired by ZeroClaw's reliable pattern.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
from typing import Any, Callable, TypeVar

import httpx

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# HTTP status codes that should trigger a retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


def reliable(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: int = 2,
) -> Callable[[F], F]:
    """Decorator for adding retry logic to async functions.

    Implements exponential backoff with jitter for transient failures.
    On HTTP 429 (rate limit), reads Retry-After header if available.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds before first retry.
        max_delay: Maximum delay in seconds between retries.
        exponential_base: Base for exponential backoff calculation.

    Returns:
        Decorated async function with retry logic.

    Example:
        @reliable(max_retries=5, base_delay=2.0)
        async def call_api():
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)

                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code

                    if status_code not in RETRYABLE_STATUS_CODES:
                        logger.error(
                            "%s failed with non-retryable HTTP %d: %s",
                            func.__name__,
                            status_code,
                            exc,
                        )
                        raise

                    last_exception = exc

                    if attempt >= max_retries:
                        break

                    # On 429, check for Retry-After header
                    delay = _calculate_delay(
                        attempt, base_delay, max_delay, exponential_base
                    )
                    if status_code == 429:
                        retry_after = exc.response.headers.get("Retry-After")
                        if retry_after is not None:
                            try:
                                delay = max(delay, float(retry_after))
                            except (ValueError, TypeError):
                                pass
                            logger.warning(
                                "%s rate limited (429), Retry-After=%s, "
                                "waiting %.1fs (attempt %d/%d)",
                                func.__name__,
                                retry_after,
                                delay,
                                attempt + 1,
                                max_retries,
                            )
                        else:
                            logger.warning(
                                "%s rate limited (429), waiting %.1fs "
                                "(attempt %d/%d)",
                                func.__name__,
                                delay,
                                attempt + 1,
                                max_retries,
                            )
                    else:
                        logger.warning(
                            "%s failed with HTTP %d, retrying in %.1fs "
                            "(attempt %d/%d)",
                            func.__name__,
                            status_code,
                            delay,
                            attempt + 1,
                            max_retries,
                        )

                    await asyncio.sleep(delay)

                except asyncio.TimeoutError as exc:
                    last_exception = exc

                    if attempt >= max_retries:
                        break

                    delay = _calculate_delay(
                        attempt, base_delay, max_delay, exponential_base
                    )
                    logger.warning(
                        "%s timed out, retrying in %.1fs (attempt %d/%d)",
                        func.__name__,
                        delay,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(delay)

                except ConnectionError as exc:
                    last_exception = exc

                    if attempt >= max_retries:
                        break

                    delay = _calculate_delay(
                        attempt, base_delay, max_delay, exponential_base
                    )
                    logger.warning(
                        "%s connection error: %s, retrying in %.1fs "
                        "(attempt %d/%d)",
                        func.__name__,
                        exc,
                        delay,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(delay)

            # All retries exhausted
            logger.error(
                "%s failed after %d retries: %s",
                func.__name__,
                max_retries,
                last_exception,
            )
            if last_exception is not None:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed with no exception captured")

        return wrapper  # type: ignore[return-value]

    return decorator


def _calculate_delay(
    attempt: int,
    base_delay: float,
    max_delay: float,
    exponential_base: int,
) -> float:
    """Calculate delay with exponential backoff and jitter.

    Uses full jitter strategy: delay = random(0, min(max_delay, base * exp_base^attempt))
    This provides good spread of retry times to avoid thundering herd.

    Args:
        attempt: Current attempt number (0-based).
        base_delay: Base delay in seconds.
        max_delay: Maximum delay cap.
        exponential_base: Base for exponentiation.

    Returns:
        Delay in seconds with jitter applied.
    """
    exp_delay = base_delay * (exponential_base ** attempt)
    capped_delay = min(exp_delay, max_delay)
    # Full jitter: uniform random between 0 and capped_delay
    jittered_delay = random.uniform(0, capped_delay)
    return jittered_delay
