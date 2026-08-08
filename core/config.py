"""Central configuration loaded from .env with sensible defaults."""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

_VALID_SENSOR_MODES = {"camera", "remote", "hybrid"}


def get_min_brightness() -> int:
    """Minimum brightness percentage (never 0 — that turns off the display)."""
    return int(os.getenv("MIN_BRIGHTNESS", "5"))


def get_sensor_mode() -> str:
    """Which sensor source to use.

    Returns one of:
      - ``"hybrid"``  – try camera first, fall back to remote (default)
      - ``"camera"``  – only the local camera
      - ``"remote"``  – only the WebSocket lux sensor
    """
    mode = os.getenv("SENSOR_MODE", "hybrid").strip().lower()
    if mode not in _VALID_SENSOR_MODES:
        print(
            f"ERROR: SENSOR_MODE={mode!r} is invalid. "
            f"Must be one of: {', '.join(sorted(_VALID_SENSOR_MODES))}.",
            file=sys.stderr,
        )
        sys.exit(1)
    return mode
