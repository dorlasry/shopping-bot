"""Tests for the worker's consume loop (app.worker.consume_loop).

Reproduces a production bug: a transient Redis connection error (e.g. a
socket read timeout) from either queue.dequeue() or queue.seen() was
propagating out of consume_loop and crashing the whole worker process,
instead of being treated like the per-job errors that are already handled.
"""

from __future__ import annotations

from app import worker
from app.queue.base import IncomingJob


class FlakyQueue:
    """A queue whose dequeue() raises once, then returns no job."""

    def __init__(self) -> None:
        self.calls = 0

    def dequeue(self, timeout: int = 5):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("boom")

    def seen(self, message_id: str) -> bool:
        return False


def test_consume_loop_survives_dequeue_error(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    queue = FlakyQueue()
    iterations = {"n": 0}

    def should_continue():
        iterations["n"] += 1
        return iterations["n"] <= 2

    worker.consume_loop(wa=None, queue=queue, should_continue=should_continue)

    assert queue.calls == 2
    assert sleep_calls == [1]


class FlakySeenQueue:
    """A queue that dequeues one real job, but whose seen() raises once."""

    def __init__(self, job: IncomingJob) -> None:
        self._job = job
        self._dequeued = False
        self.seen_calls = 0

    def dequeue(self, timeout: int = 5):
        if self._dequeued:
            return None
        self._dequeued = True
        return self._job

    def seen(self, message_id: str) -> bool:
        self.seen_calls += 1
        if self.seen_calls == 1:
            raise ConnectionError("boom")
        return False


def test_consume_loop_survives_seen_error(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    job = IncomingJob(
        kind="message",
        phone="972500000001",
        name="Tester",
        message_id="wamid.1",
        text="hi",
    )
    queue = FlakySeenQueue(job)
    iterations = {"n": 0}

    def should_continue():
        iterations["n"] += 1
        return iterations["n"] <= 2

    worker.consume_loop(wa=None, queue=queue, should_continue=should_continue)

    assert queue.seen_calls == 1
    assert sleep_calls == [1]
