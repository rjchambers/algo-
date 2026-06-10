"""structlog JSON logging with secret redaction and rotating file output."""

import logging
import logging.handlers
import re
from pathlib import Path

import structlog

# Anything that looks like a private key / long hex blob, or a value of a
# secret-named field, is redacted before it can reach a log sink.
_HEX_KEY_RE = re.compile(r"0x[0-9a-fA-F]{40,}")
_SECRET_FIELD_RE = re.compile(r"(key|secret|signature|token|password)", re.IGNORECASE)

REDACTED = "[REDACTED]"


def _redact_value(value):
    if isinstance(value, str):
        return _HEX_KEY_RE.sub(REDACTED, value)
    if isinstance(value, dict):
        return {
            k: REDACTED if _SECRET_FIELD_RE.search(str(k)) else _redact_value(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(v) for v in value)
    return value


def redact_secrets(logger, method_name, event_dict):
    """structlog processor: redact secret-named fields and key-shaped strings."""
    return {
        k: REDACTED if _SECRET_FIELD_RE.search(str(k)) else _redact_value(v)
        for k, v in event_dict.items()
    }


def configure_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_dir / "hl_trader.jsonl", maxBytes=20_000_000, backupCount=5
            )
        )
    logging.basicConfig(level=level.upper(), handlers=handlers, format="%(message)s")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_secrets,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str, **context):
    return structlog.get_logger(name).bind(**context)
