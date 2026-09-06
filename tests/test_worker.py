"""Tests for the worker's consume loop (app.worker.consume_loop).

Reproduces a production bug: a transient queue.dequeue() error (e.g. a Redis
connection blip) was propagating out of consume_loop and crashing the whole
worker process, instead of being treated like the per-job errors that are
already handled.
"""

from __future__ import annotations

from app import worker


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
