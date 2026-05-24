"""In-memory queue — zero dependencies, for local dev / tests / single-process mode.

Only works when producer and consumer live in the SAME process (the web app runs
the worker in a background thread). For a real multi-process deployment, use Redis.
"""

from __future__ import annotations

import threading
from collections import deque

from app.queue.base import IncomingJob, MessageQueue


class InMemoryQueue(MessageQueue):
    def __init__(self) -> None:
        self._dq: deque[IncomingJob] = deque()
        self._seen: set[str] = set()
        self._cv = threading.Condition()

    def enqueue(self, job: IncomingJob) -> None:
        with self._cv:
            self._dq.appendleft(job)
            self._cv.notify()

    def dequeue(self, timeout: int = 5) -> IncomingJob | None:
        with self._cv:
            if not self._dq:
                self._cv.wait(timeout=timeout)
            if not self._dq:
                return None
            return self._dq.pop()

    def seen(self, message_id: str) -> bool:
        with self._cv:
            if message_id in self._seen:
                return True
            self._seen.add(message_id)
            return False
