"""Build the configured queue backend.

This is the ONE place that knows about concrete implementations. Swapping to a
new backend at scale = add an implementation + one branch here.
"""

from __future__ import annotations

from app.config import settings
from app.queue.base import MessageQueue
from app.queue.memory import InMemoryQueue
from app.queue.redis_queue import RedisQueue


def build_queue() -> MessageQueue:
    backend = settings.queue_backend.lower()
    if backend == "redis":
        return RedisQueue(settings.redis_url, key=settings.queue_key)
    if backend == "memory":
        return InMemoryQueue()
    raise ValueError(
        f"Unknown QUEUE_BACKEND={settings.queue_backend!r}. Use 'redis' or 'memory'."
    )
