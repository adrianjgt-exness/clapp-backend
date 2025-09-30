# app/config/logging_config.py
import json
import logging
import sys

from .settings import settings


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **{
                k: record.__dict__[k]
                for k in ("source", "meta")
                if k in record.__dict__
            },
        }
        return json.dumps(data)


def get_logger(name: str = "clapp") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:  # already configured
        return logger

    level = settings.LOGGING_LEVEL.upper()
    logger.setLevel(level)

    h = logging.StreamHandler(sys.stdout)
    h.setLevel(level)
    h.setFormatter(_JsonFormatter())
    logger.addHandler(h)

    logger.info("Logger ready (stdout-only, picked up by Fluent Bit)")
    return logger


logger = get_logger()  # exported singleton
