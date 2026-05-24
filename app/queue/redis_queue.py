"""Redis-backed queue — the production backend.

Uses a Redis list as a FIFO queue: LPUSH to enqueue, BRPOP to block-and-pop.
Dedup uses SET NX EX (set-if-absent with TTL) keyed on the WhatsApp message id.

Reliability note: this is at-MOST-once (a job is gone once BRPOP returns). For
stricter at-least-once delivery, switch BRPOP to BRPOPLPUSH into a processing
list and delete after success, or move to Redis Streams with consumer groups.
For the MVP this simple form is reliable enough and easy to reason about.
"""

from __future__ import annotations

import redis

from app.queue.base import IncomingJob, MessageQueue

_SEEN_TTL_SECONDS = 24 * 60 * 60  # remember processed ids for a day


class RedisQueue(MessageQueue):
    def __init__(self, url: str, key: str = "shopping:incoming") -> None:
        self._redis = redis.Redis.from_url(url)
        self._key = key

    def enqueue(self, job: IncomingJob) -> None:
        self._redis.lpush(self._key, job.to_json())

    def dequeue(self, timeout: int = 5) -> IncomingJob | None:
        item = self._redis.brpop([self._key], timeout=timeout)
        if item is None:
            return None
        _key, raw = item  # brpop returns (key, value)
        return IncomingJob.from_json(raw)

    def seen(self, message_id: str) -> bool:
        # SET key "1" NX EX ttl -> returns True if it was set (i.e. NOT seen before).
        was_set = self._redis.set(
            f"shopping:seen:{message_id}", "1", nx=True, ex=_SEEN_TTL_SECONDS
        )
        return not bool(was_set)

    def close(self) -> None:
        self._redis.close()
