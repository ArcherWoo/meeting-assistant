import io
import logging
import os
import sys
import unittest
from unittest.mock import patch


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.logging_config import StructuredJsonFormatter, configure_logging


class LoggingConfigTests(unittest.TestCase):
    def test_structured_json_formatter_wraps_plain_message(self):
        formatter = StructuredJsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="plain message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        self.assertIn('"logger": "test.logger"', output)
        self.assertIn('"message": "plain message"', output)

    def test_structured_json_formatter_merges_json_payload(self):
        formatter = StructuredJsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg='{"event":"chat.request.started","request_id":"chat-1"}',
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        self.assertIn('"event": "chat.request.started"', output)
        self.assertIn('"request_id": "chat-1"', output)
        self.assertNotIn('"message":', output)

    def test_configure_logging_supports_text_mode(self):
        stream = io.StringIO()
        with patch.dict(os.environ, {"MEETING_ASSISTANT_LOG_FORMAT": "text", "MEETING_ASSISTANT_LOG_LEVEL": "INFO"}, clear=False):
            original_stream_handler = logging.StreamHandler

            def _stream_handler_factory(*args, **kwargs):
                return original_stream_handler(stream)

            with patch("services.logging_config.logging.StreamHandler", side_effect=_stream_handler_factory):
                configure_logging()
                logger = logging.getLogger("text-mode-test")
                logger.info("hello")

        self.assertIn("hello", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
