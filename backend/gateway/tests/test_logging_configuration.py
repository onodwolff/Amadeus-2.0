import io
import logging

import pytest

from backend.gateway.app import logging as logging_config


def _reset_root_logger(original_handlers):
    root = logging.getLogger()
    root.handlers = list(original_handlers)
    root.setLevel(logging.NOTSET)


@pytest.mark.parametrize("initial_handlers", [None, [logging.StreamHandler(io.StringIO())]])
def test_setup_logging_respects_existing_handlers(initial_handlers):
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        if initial_handlers is None:
            root.handlers = []
            expected_handlers = 1
        else:
            root.handlers = list(initial_handlers)
            expected_handlers = len(initial_handlers)

        logging_config.setup_logging(level="DEBUG")

        assert len(root.handlers) == expected_handlers
        assert root.level == logging.DEBUG
        for handler in root.handlers:
            if initial_handlers is None:
                assert handler.level in (logging.NOTSET, logging.DEBUG)
            else:
                assert handler.level == logging.DEBUG
    finally:
        _reset_root_logger(original_handlers)
