from __future__ import annotations

import json
import logging


REDACTED_KEYS = frozenset({"reconnect_token", "token", "camera", "frame", "image"})


def _redact(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in REDACTED_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if context:
            payload["context"] = _redact(context)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("spells_server")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, str(level).upper()))
    logger.propagate = False
    return logger
