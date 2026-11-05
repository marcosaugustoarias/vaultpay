"""Structured JSON logging with secret/PII redaction (SEC-AUDIT-02)."""

from __future__ import annotations

import json
import logging
import re

_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[a-z0-9._\-]+"), r"\1[REDACTED]"),
    (
        re.compile(r"(?i)((?:password|passwd|secret|token|authorization|otp|totp|cookie)[\"'\s:=]+)[^\s\"',}]+"),
        r"\1[REDACTED]",
    ),
    (re.compile(r"\b\d{13,19}\b"), "[REDACTED-PAN]"),  # card-number-like sequences
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[REDACTED-EMAIL]"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = redact(record.getMessage())
        if record.exc_info:
            # Keep the stack for operators but scrub secrets out of it.
            message += " | " + redact(self.formatException(record.exc_info)).replace("\n", " ⏎ ")
        if message.startswith("{"):
            return message
        return json.dumps({"level": record.levelname, "logger": record.name, "message": message})


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").disabled = True  # we emit our own (no query strings)
