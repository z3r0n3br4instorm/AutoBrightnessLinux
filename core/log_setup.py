"""Logging setup: stderr for interactive runs, systemd journal for history.

Journal output needs no third-party package — journald listens on the classic
syslog socket at ``/dev/log``, so :class:`logging.handlers.SysLogHandler`
reaches it directly. If ``python-systemd`` happens to be installed its
``JournalHandler`` is preferred, since it attaches structured fields
(``LOGGER``, ``CODE_FILE``, …) that ``journalctl -o json`` can filter on.
"""

import logging
import logging.handlers
import os
import sys

from core.config import get_log_level, get_log_target

# Journal tag: `journalctl -t autobrightness`
SYSLOG_IDENTIFIER = "autobrightness"

_JOURNAL_SOCKET = "/dev/log"

_configured = False


def _journal_handler() -> logging.Handler | None:
    """Return a handler writing to the systemd journal, or None if impossible."""
    # Preferred: structured native journal protocol.
    try:
        from systemd import journal  # type: ignore

        return journal.JournalHandler(SYSLOG_IDENTIFIER=SYSLOG_IDENTIFIER)
    except Exception:
        pass

    # Fallback: syslog socket, which on a systemd host is journald itself.
    if not os.path.exists(_JOURNAL_SOCKET):
        return None
    try:
        handler = logging.handlers.SysLogHandler(address=_JOURNAL_SOCKET)
    except OSError:
        return None

    # journald derives SYSLOG_IDENTIFIER from the "tag[pid]:" prefix. No
    # timestamp — the journal records its own, and a second one just adds noise.
    handler.setFormatter(
        logging.Formatter(
            f"{SYSLOG_IDENTIFIER}[{os.getpid()}]: %(name)s: %(message)s"
        )
    )
    return handler


def setup_logging(target: str | None = None, level: str | None = None) -> None:
    """Configure root logging once, per LOG_TARGET / LOG_LEVEL.

    Args:
        target: ``both`` (default), ``journal``, ``stderr`` or ``none``.
                Overrides ``LOG_TARGET`` when given.
        level: Log level name, e.g. ``DEBUG``. Overrides ``LOG_LEVEL``.
    """
    global _configured
    if _configured:
        return

    target = (target or get_log_target()).strip().lower()
    level_name = (level or get_log_level()).strip().upper()
    resolved = getattr(logging, level_name, None)
    if not isinstance(resolved, int):
        print(
            f"WARNING: LOG_LEVEL={level_name!r} is not a valid level; using INFO.",
            file=sys.stderr,
        )
        resolved = logging.INFO

    root = logging.getLogger()
    root.setLevel(resolved)
    for existing in root.handlers[:]:
        root.removeHandler(existing)

    if target in ("stderr", "both"):
        stream = logging.StreamHandler()
        stream.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(stream)

    if target in ("journal", "both"):
        handler = _journal_handler()
        if handler is not None:
            root.addHandler(handler)
        else:
            # Never fail silently: without this the run would look logged.
            print(
                "WARNING: journal logging unavailable "
                f"({_JOURNAL_SOCKET} missing and python-systemd not installed); "
                "falling back to stderr.",
                file=sys.stderr,
            )
            if target == "journal":
                root.addHandler(logging.StreamHandler())

    if not root.handlers:
        root.addHandler(logging.NullHandler())

    _configured = True
