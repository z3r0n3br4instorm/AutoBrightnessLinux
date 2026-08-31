"""Central configuration loaded from .env with sensible defaults."""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

_VALID_SENSOR_MODES = {"local", "camera", "remote", "hybrid"}


def get_min_brightness() -> int:
    """Minimum brightness percentage (never 0 — that turns off the display)."""
    return int(os.getenv("MIN_BRIGHTNESS", "5"))


def get_sensor_mode() -> str:
    """Which sensor source to use.

    Returns one of:
      - ``"hybrid"``  – local ALS → camera → remote, first one that works
                        (default)
      - ``"local"``   – only the built-in ambient light sensor (IIO/sysfs)
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


def get_opentone_enabled() -> bool:
    """Whether OpenTone ambient color temperature adjustment is enabled."""
    return os.getenv("OPENTONE_ENABLED", "true").strip().lower() in ("true", "1", "yes", "on")



def get_opentone_min_temp() -> int:
    """Minimum color temperature in Kelvin for OpenTone (warm floor, e.g. 3000)."""
    return int(os.getenv("OPENTONE_MIN_TEMP", "3000"))


def get_opentone_max_temp() -> int:
    """Maximum color temperature in Kelvin for OpenTone (cool ceiling, e.g. 6500)."""
    return int(os.getenv("OPENTONE_MAX_TEMP", "6500"))


def get_opentone_smoothing_factor() -> float:
    """Smoothing factor for OpenTone exponential moving average (0.0 to 1.0)."""
    return float(os.getenv("OPENTONE_SMOOTHING_FACTOR", "0.3"))


def get_opentone_min_change_threshold() -> int:
    """Minimum temperature change in Kelvin required to trigger an update."""
    return int(os.getenv("OPENTONE_MIN_CHANGE_THRESHOLD", "50"))

