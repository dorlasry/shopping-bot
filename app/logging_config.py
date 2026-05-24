"""Minimal structured-ish logging setup.

Keeps things simple for the MVP: a single console handler with a readable
format. Swap for structured JSON logging (e.g. structlog) when you ship to prod.
"""

import logging

from app.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # pywa and httpx are chatty at INFO; keep them at WARNING unless debugging.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pywa").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
