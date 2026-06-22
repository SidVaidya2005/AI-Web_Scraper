"""Process-wide logging configuration for the `app.*` logger namespace."""

import logging

from app.config import Settings

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(settings: Settings) -> None:
    """Configure the `app` logger at `settings.log_level` (idempotent).

    Targets the `app` namespace so module loggers (`app.jobs`, `app.fetching`,
    …) inherit a single handler and level. Re-callable without stacking handlers
    so repeated `create_app()` in tests stays clean.
    """
    logger = logging.getLogger("app")
    logger.setLevel(settings.log_level)
    has_stream = any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    if not has_stream:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
    logger.propagate = False  # don't double-emit through the root logger
