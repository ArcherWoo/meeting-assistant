from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }

        message = record.getMessage()
        parsed_payload: dict[str, Any] | None = None
        if message.startswith("{") and message.endswith("}"):
            try:
                maybe_payload = json.loads(message)
            except json.JSONDecodeError:
                parsed_payload = None
            else:
                if isinstance(maybe_payload, dict):
                    parsed_payload = maybe_payload

        if parsed_payload:
            payload.update(parsed_payload)
        else:
            payload["message"] = message

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def _normalize_level(raw_level: str) -> int:
    normalized = str(raw_level or "").strip().upper() or "INFO"
    return getattr(logging, normalized, logging.INFO)


def configure_logging() -> None:
    level = _normalize_level(os.getenv("MEETING_ASSISTANT_LOG_LEVEL", "INFO"))
    log_format = str(os.getenv("MEETING_ASSISTANT_LOG_FORMAT", "json")).strip().lower() or "json"

    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(StructuredJsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    logging.basicConfig(level=level, handlers=[handler], force=True)
