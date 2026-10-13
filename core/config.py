"""Central configuration loaded from .env with sensible defaults."""

import os
import sys
from dotenv import find_dotenv, load_dotenv

# The .env in the working directory first, then the one beside the program.
# A compiled build lives elsewhere than its sources, so the first is what finds
# the settings there; variables already set are never overridden.
load_dotenv(find_dotenv(usecwd=True))
load_dotenv()

_VALID_SENSOR_MODES = {"local", "camera", "remote", "hybrid"}

_VALID_LOG_TARGETS = {"both", "journal", "stderr", "none"}


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


def get_log_target() -> str:
    """Where log records go.

    Returns one of:
      - ``"both"``     – stderr and the systemd journal (default)
      - ``"journal"``  – systemd journal only
      - ``"stderr"``   – terminal only
      - ``"none"``     – discard
    """
    target = os.getenv("LOG_TARGET", "both").strip().lower()
    if target not in _VALID_LOG_TARGETS:
        print(
            f"ERROR: LOG_TARGET={target!r} is invalid. "
            f"Must be one of: {', '.join(sorted(_VALID_LOG_TARGETS))}.",
            file=sys.stderr,
        )
        sys.exit(1)
    return target


def get_log_level() -> str:
    """Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""
    return os.getenv("LOG_LEVEL", "INFO").strip().upper()


def get_opentone_enabled() -> bool:
    """Whether OpenTone ambient color temperature adjustment is enabled."""
    return os.getenv("OPENTONE_ENABLED", "true").strip().lower() in ("true", "1", "yes", "on")



def get_opentone_source() -> str:
    """Where OpenTone measures the ambient colour temperature.

      - ``"auto"``   – a colour light sensor when there is one, else the camera
      - ``"sensor"`` – only a colour light sensor (IIO colortemp or RGB channels)
      - ``"camera"`` – only the webcam
    """
    source = os.getenv("OPENTONE_SOURCE", "auto").strip().lower()
    return source if source in ("auto", "sensor", "camera") else "auto"


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


def get_opentone_transition_duration() -> float:
    """Seconds a colour temperature change is ramped over (0 disables ramping)."""
    return float(os.getenv("OPENTONE_TRANSITION_DURATION", "1.2"))


def get_opentone_transition_steps() -> int:
    """Number of intermediate steps in a ramp.

    Each step is one ``redshift`` invocation (~17 ms), so this trades smoothness
    against process churn.
    """
    return int(os.getenv("OPENTONE_TRANSITION_STEPS", "25"))

