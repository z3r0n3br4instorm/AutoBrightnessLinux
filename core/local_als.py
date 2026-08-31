"""Local ambient-light-sensor reader via the kernel IIO subsystem.

Many laptops (including the MacBook Pro, whose ALS sits in the top bezel and
is exposed by the ``acpi_als`` driver) publish illuminance through sysfs at
``/sys/bus/iio/devices/iio:deviceN``.  Reading that is far cheaper and more
accurate than inferring brightness from a camera frame, so it is preferred
whenever the hardware is present.

Values are read straight from sysfs — there is no connection to maintain, so
unlike :class:`~core.websocket_sensor.WebSocketSensor` this class needs no
background thread.
"""

import glob
import logging
import os
import time

logger = logging.getLogger(__name__)

_IIO_ROOT = "/sys/bus/iio/devices"

# Driver names known to expose an ambient light sensor.  Devices are matched
# primarily by the presence of an ``in_illuminance_*`` attribute; this list
# only decides *preference* when several candidates exist.
_PREFERRED_NAMES = (
    "acpi-als",
    "als",
    "hid-sensor-als",
)


def _read_attr(device_path: str, attr: str) -> str | None:
    """Read a sysfs attribute as stripped text, or ``None`` if unreadable."""
    try:
        with open(os.path.join(device_path, attr)) as f:
            return f.read().strip()
    except (OSError, ValueError):
        return None


def _read_float(device_path: str, attr: str) -> float | None:
    """Read a sysfs attribute as a float, or ``None`` if absent/malformed."""
    text = _read_attr(device_path, attr)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        logger.debug("Non-numeric value %r in %s/%s", text, device_path, attr)
        return None


def _has_illuminance(device_path: str) -> bool:
    """True when the device exposes a readable illuminance channel."""
    for attr in ("in_illuminance_input", "in_illuminance_raw"):
        path = os.path.join(device_path, attr)
        if os.path.exists(path) and os.access(path, os.R_OK):
            return True
    return False


class LocalALSUnavailable(RuntimeError):
    """Raised when no usable ambient light sensor exists on this machine."""


class LocalALS:
    """Reads lux from a local IIO ambient light sensor.

    Parameters
    ----------
    device_path:
        Explicit ``iio:deviceN`` directory to use.  When omitted the first
        usable sensor is discovered automatically.
    samples:
        How many readings to average per :meth:`read_lux` call.  Averaging
        smooths out the jitter cheap sensors show under mains lighting.
    sample_delay:
        Seconds to wait between samples.
    """

    def __init__(
        self,
        device_path: str | None = None,
        samples: int = 3,
        sample_delay: float = 0.1,
    ):
        self.device_path = device_path or self.discover()
        if self.device_path is None:
            raise LocalALSUnavailable(
                "No IIO ambient light sensor found. On a MacBook, check that "
                "the 'acpi_als' kernel module is loaded (modprobe acpi_als)."
            )

        self.samples = max(1, samples)
        self.sample_delay = sample_delay
        self.name = _read_attr(self.device_path, "name") or "unknown"

        # ``in_illuminance_input`` is already scaled to lux by the driver;
        # ``in_illuminance_raw`` needs the scale/offset applied by us.
        if os.path.exists(os.path.join(self.device_path, "in_illuminance_input")):
            self._attr = "in_illuminance_input"
            self._processed = True
        else:
            self._attr = "in_illuminance_raw"
            self._processed = False

        self._scale = _read_float(self.device_path, "in_illuminance_scale") or 1.0
        self._offset = _read_float(self.device_path, "in_illuminance_offset") or 0.0

        logger.info(
            "Local ALS: %s at %s (attribute %s)",
            self.name,
            self.device_path,
            self._attr,
        )

    # -- discovery ---------------------------------------------------------

    @staticmethod
    def discover() -> str | None:
        """Return the sysfs path of the best available ALS, or ``None``."""
        candidates = []
        for path in sorted(glob.glob(os.path.join(_IIO_ROOT, "iio:device*"))):
            if not _has_illuminance(path):
                continue
            name = (_read_attr(path, "name") or "").lower()
            # Lower rank sorts first: named ALS drivers beat generic devices.
            rank = (
                _PREFERRED_NAMES.index(name)
                if name in _PREFERRED_NAMES
                else len(_PREFERRED_NAMES)
            )
            candidates.append((rank, path))

        if not candidates:
            return None
        candidates.sort()
        return candidates[0][1]

    @staticmethod
    def is_available() -> bool:
        """True when this machine has a readable ambient light sensor."""
        return LocalALS.discover() is not None

    # -- reading -----------------------------------------------------------

    def read_lux(self) -> float | None:
        """Return the current illuminance in lux, or ``None`` on failure."""
        readings = []
        for i in range(self.samples):
            if i:
                time.sleep(self.sample_delay)
            value = _read_float(self.device_path, self._attr)
            if value is not None:
                readings.append(value)

        if not readings:
            logger.warning("Could not read %s from %s", self._attr, self.device_path)
            return None

        lux = sum(readings) / len(readings)
        if not self._processed:
            lux = (lux + self._offset) * self._scale
        return max(0.0, lux)
