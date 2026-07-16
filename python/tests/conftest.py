"""Shared fixtures for genekit tests."""

import logging
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    """Restore root logging state and close handlers opened by a test.

    On Windows an open FileHandler holds a lock on its file, which breaks pytest's ``tmp_path``
    cleanup — so every handler a test attaches must be closed, not merely detached.
    """
    root = logging.getLogger()
    before_handlers = list(root.handlers)
    before_level = root.level
    before_loggers = set(logging.Logger.manager.loggerDict)
    yield
    for handler in list(root.handlers):
        if handler not in before_handlers:
            root.removeHandler(handler)
            handler.close()
    for name in set(logging.Logger.manager.loggerDict) - before_loggers:
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
    root.handlers[:] = before_handlers
    root.setLevel(before_level)
