# BrightnessAnalyzer & OpenTone V0.0.3 by Zerone B. Storm
import argparse
import math
import logging
import sys

from core.brightness_core import BrightnessAnalyzer
from core.config import get_min_brightness, get_sensor_mode, get_opentone_enabled
from core.local_als import LocalALS, LocalALSUnavailable
from core.log_setup import setup_logging
from core.opentone import OpenTone

setup_logging()
logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_available_camera():
    import cv2

    for camera_index in range(10):
        cap = cv2.VideoCapture(camera_index)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                logger.info("Found working camera at index %d", camera_index)
                return camera_index
    return None


def lux_to_brightness(lux: float) -> int:
    """Convert a lux reading to a brightness percentage.

    Uses a logarithmic mapping that reflects human perception:
    - ~0 lux   → min_brightness %  (near-dark, never turns off display)
    - ~100 lux → 30 %  (dim room)
    - ~500 lux → 60 %  (well-lit room)
    - ~2000 lux → 90 %  (bright indoor / overcast outdoor)
    - ~10000+ lux → 100 % (direct sunlight)
    """
    min_brightness = get_min_brightness()
    if lux <= 0:
        return min_brightness
    # log10(1) = 0, log10(50000) ≈ 4.7 — cap at 100 %
    percent = (math.log10(max(lux, 0.1)) / 5.0) * 100  # 5 ≈ log10(100000)
    return max(min_brightness, min(100, int(round(percent))))


def apply_lux(lux: float, source: str) -> bool:
    """Map a lux reading to a brightness percentage and apply it."""
    brightness_pct = lux_to_brightness(lux)
    logger.info("Mapped lux %.1f → brightness %d %%", lux, brightness_pct)
    try:
        # No cameraid — the webcam is irrelevant to a lux-based source.
        BrightnessAnalyzer().setBrightness(brightness_pct)
    except Exception as e:
        logger.error("Failed to set brightness from %s: %s", source, e)
        return False
    logger.info("Brightness set from %s", source)
    return True


# ---------------------------------------------------------------------------
# OpenTone helpers & Async Runner
# ---------------------------------------------------------------------------

class OpenToneAsyncRunner:
    """Manages concurrent execution of OpenTone when lux-based sensors are active."""

    def __init__(self, camera_id=None):
        import threading

        self.camera_id = camera_id
        self.thread = None
        self.success = False
        self.started = False

    def start(self):
        """Start OpenTone in a background thread."""
        import threading

        if self.started:
            return
        self.started = True
        self.thread = threading.Thread(
            target=self._run,
            name="OpenToneWorker",
            daemon=True,
        )
        self.thread.start()
        logger.info("OpenTone started asynchronously in background thread")

    def _run(self):
        try:
            self.success = apply_opentone(camera_id=self.camera_id)
        except Exception as e:
            logger.error("Asynchronous OpenTone failed: %s", e)
            self.success = False

    def is_running(self) -> bool:
        return self.started and self.thread is not None and self.thread.is_alive()

    def wait(self, timeout: float = 15.0) -> bool:
        """Wait for the background OpenTone thread to finish."""
        if self.thread is not None:
            self.thread.join(timeout=timeout)
            if self.thread.is_alive():
                logger.warning("OpenTone background thread timed out after %.1f s", timeout)
                return False
        return self.success


def apply_opentone(image=None, camera_id=None) -> bool:
    """Estimate ambient color temperature and apply systemwide using Redshift."""
    try:
        if image is None:
            if camera_id is None:
                camera_id = find_available_camera()
            if camera_id is None:
                logger.warning("OpenTone: No working camera found.")
                return False
            analyzer = OpenTone(camera_id)
            try:
                # Median of several settled frames — a single frame straight
                # after opening the camera is both underexposed and noisy.
                raw_cct = analyzer.measure_cct()
            finally:
                analyzer.release()
        else:
            # Frame shared from the brightness path: it was captured without
            # OpenTone's white-balance lock, so the estimate is less reliable.
            analyzer = OpenTone()
            raw_cct = analyzer.estimate_color_temperature(image)

        target_cct = analyzer.clamp_temperature(raw_cct)
        smoothed_cct = analyzer.smooth_temperature(target_cct)
        logger.info(
            "OpenTone: Raw CCT: %.1f K → target %d K → smoothed %d K",
            raw_cct,
            target_cct,
            smoothed_cct,
        )
        success = analyzer.set_temperature(smoothed_cct)
        if success:
            logger.info("OpenTone: Color temperature set to %d K via Redshift", smoothed_cct)
            return True
        else:
            logger.warning("OpenTone: Failed to set color temperature via Redshift")
            return False
    except Exception as e:
        logger.error("OpenTone failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Sensor sources — each returns True once brightness has been applied
# ---------------------------------------------------------------------------

def try_local_als(opentone_runner: OpenToneAsyncRunner = None) -> bool:
    """Read the built-in ambient light sensor and apply the result."""
    try:
        als = LocalALS()
    except LocalALSUnavailable as e:
        logger.info("Local ALS not usable: %s", e)
        return False

    lux = als.read_lux()
    if lux is None:
        logger.warning("Local ALS (%s) returned no reading", als.name)
        return False

    logger.info("Local ALS (%s) reading: %.1f lux", als.name, lux)

    # Lux sensor is confirmed available — start OpenTone asynchronously
    # so camera sampling and Redshift run concurrently with brightness ramping.
    if opentone_runner is not None and not opentone_runner.started:
        logger.info("Lux sensor available (%s) – starting OpenTone asynchronously", als.name)
        opentone_runner.start()

    return apply_lux(lux, f"local ALS ({als.name})")


def try_camera() -> bool:
    """Estimate ambient brightness from a camera frame and apply the result."""
    camera_id = find_available_camera()
    if camera_id is None:
        logger.info("No working camera found.")
        return False

    try:
        # Released before returning so OpenTone can reopen the device — a
        # second VideoCapture on a still-open camera fails outright.
        with BrightnessAnalyzer(camera_id) as analyzer:
            image = analyzer.capture_image()
            prominent_color, avg_color = analyzer.get_prominent_color(image)
            logger.info("Prominent Color: %s, Average Color Value: %s", prominent_color, avg_color)
            raw_brightness = analyzer.calculate_brightness(prominent_color)
            smoothed_brightness = analyzer.smooth_brightness(raw_brightness)
            logger.info("Raw Brightness: %.1f, Smoothed: %d", raw_brightness, smoothed_brightness)
            analyzer.setBrightness(max(get_min_brightness(), smoothed_brightness))
    except Exception as e:
        logger.error("Camera mode failed: %s", e)
        return False

    logger.info("Brightness set from camera reading")
    return True


def try_remote(discovery, opentone_runner: OpenToneAsyncRunner = None) -> bool:
    """Read lux from the SensorServer over WebSocket and apply the result."""
    from core.websocket_sensor import WebSocketSensor

    if not discovery.wait_until_available(timeout=10.0):
        logger.warning("SensorServer not found via mDNS yet; will keep waiting…")

    # Start OpenTone in background while we connect and wait for WebSocket lux reading
    if opentone_runner is not None and not opentone_runner.started:
        logger.info("Remote lux sensor active – starting OpenTone asynchronously")
        opentone_runner.start()

    sensor = WebSocketSensor(discovery)
    sensor.start()
    try:
        lux = sensor.wait_for_reading(timeout=20.0)
        if lux is None:
            logger.error("No lux reading received from SensorServer – giving up.")
            return False
        logger.info("Received lux reading: %.1f", lux)
        return apply_lux(lux, "WebSocket lux value")
    finally:
        sensor.stop()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="AutoBrightness & OpenTone (TrueTone for Linux)"
    )
    parser.add_argument(
        "--opentone",
        "--tone",
        action="store_true",
        help="Enable OpenTone ambient color temperature adjustment for this run",
    )
    parser.add_argument(
        "--opentone-only",
        "--tone-only",
        action="store_true",
        help="Run only OpenTone color temperature adjustment (skip brightness)",
    )
    parser.add_argument(
        "--brightness-only",
        action="store_true",
        help="Run only brightness adjustment (skip OpenTone even if enabled in .env)",
    )
    parser.add_argument(
        "--reset-tone",
        action="store_true",
        help="Reset Redshift color temperature to neutral default (redshift -x)",
    )
    parser.add_argument(
        "--set-tone",
        type=int,
        metavar="TEMP",
        help="Manually set display color temperature in Kelvin (e.g. 4500)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current brightness and color temperature status",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.status:
        current_bright = BrightnessAnalyzer().getCurrentBrightness()
        current_temp = OpenTone().get_current_temperature()
        print(f"Current Brightness: {current_bright}%")
        print(f"Current Color Temperature: {current_temp}K")
        sys.exit(0)

    if args.reset_tone:
        OpenTone().reset()
        logger.info("OpenTone: Display color temperature reset to neutral.")
        sys.exit(0)

    if args.set_tone:
        success = OpenTone().set_temperature(args.set_tone)
        if success:
            logger.info("Set color temperature to %dK.", args.set_tone)
            sys.exit(0)
        else:
            logger.error("Failed to set color temperature.")
            sys.exit(1)

    opentone_active = (args.opentone or get_opentone_enabled()) and not args.brightness_only

    if args.opentone_only:
        success = apply_opentone()
        if not success:
            sys.exit(1)
        sys.exit(0)

    # Brightness adjustment flow
    mode = get_sensor_mode()
    logger.info("Sensor mode: %s (OpenTone: %s)", mode, "enabled" if opentone_active else "disabled")

    # mDNS discovery is only worth starting when the remote sensor might be
    # used; in hybrid mode it starts now so the IP:port is warm if we fall
    # through to it.
    discovery = None
    if mode in ("remote", "hybrid"):
        from core.sensor_discovery import SensorDiscovery

        discovery = SensorDiscovery(poll_interval=30.0)
        discovery.start()

    opentone_runner = OpenToneAsyncRunner() if opentone_active else None

    if mode == "local":
        sources = [lambda: try_local_als(opentone_runner)]
    elif mode == "camera":
        sources = [try_camera]
    elif mode == "remote":
        sources = [lambda: try_remote(discovery, opentone_runner)]
    else:  # hybrid — prefer the real sensor, then camera, then remote
        sources = [
            lambda: try_local_als(opentone_runner),
            try_camera,
            lambda: try_remote(discovery, opentone_runner),
        ]

    brightness_success = any(source() for source in sources)
    if not brightness_success:
        logger.error("No sensor source produced a usable reading for brightness.")

    # OpenTone adjustment completion or fallback
    if opentone_active:
        if opentone_runner is not None and opentone_runner.started:
            opentone_success = opentone_runner.wait()
            if not opentone_success:
                logger.warning("Asynchronous OpenTone adjustment could not be applied.")
        else:
            # Deliberately not reusing the brightness path's frame: that one is
            # captured with the camera's own auto white balance, which cancels
            # out the ambient colour cast OpenTone needs to measure. Costs one
            # extra camera open, buys a correct reading.
            opentone_success = apply_opentone()
            if not opentone_success:
                logger.warning("OpenTone adjustment could not be applied.")

    if not brightness_success and not opentone_active:
        sys.exit(1)

    logger.info("Done.")


