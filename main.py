# BrightnessAnalyzer V0.0.2 by Zerone B. Storm
import math
import logging
import sys

import cv2

from core.brightness_core import BrightnessAnalyzer
from core.config import get_min_brightness, get_sensor_mode
from core.sensor_discovery import SensorDiscovery
from core.websocket_sensor import WebSocketSensor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# mDNS discovery thread – runs from startup so the IP:port is always current
# ---------------------------------------------------------------------------

discovery = SensorDiscovery(poll_interval=30.0)
discovery.start()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_available_camera():
    for camera_index in range(10):
        cap = cv2.VideoCapture(camera_index)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                print(f"Found working camera at index {camera_index}")
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


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mode = get_sensor_mode()
    logger.info("Sensor mode: %s", mode)

    camera_id = None

    # ── Camera path (camera | hybrid) ────────────────────────────────────
    if mode in ("camera", "hybrid"):
        camera_id = find_available_camera()
        if camera_id is not None:
            try:
                analyzer = BrightnessAnalyzer(camera_id)
                image = analyzer.capture_image()
                prominent_color, avg_color = analyzer.get_prominent_color(image)
                print(f"Prominent Color: {prominent_color}, Average Color Value: {avg_color}")
                raw_brightness = analyzer.calculate_brightness(prominent_color)
                smoothed_brightness = analyzer.smooth_brightness(raw_brightness)
                print(f"Raw Brightness: {raw_brightness:.1f}, Smoothed: {smoothed_brightness}")
                analyzer.setBrightness(max(get_min_brightness(), smoothed_brightness))
                logger.info("Brightness set from camera reading")
            except Exception as e:
                print(f"Camera mode failed: {e}")
                camera_id = None  # force fallback below (hybrid only)
        elif mode == "camera":
            logger.error("Camera mode selected but no working camera found.")
            sys.exit(1)

    # ── Remote path (remote | hybrid fallback) ───────────────────────────
    if mode == "remote" or (mode == "hybrid" and camera_id is None):
        if camera_id is None:
            logger.info(
                "Using WebSocket sensor"
                if mode == "remote"
                else "No working camera – falling back to WebSocket sensor"
            )

        if not discovery.wait_until_available(timeout=10.0):
            logger.warning(
                "SensorServer not found via mDNS yet; will keep waiting…"
            )

        sensor = WebSocketSensor(discovery)
        sensor.start()

        lux = sensor.wait_for_reading(timeout=20.0)
        if lux is None:
            logger.error(
                "No lux reading received from SensorServer – giving up."
            )
            sensor.stop()
        else:
            logger.info("Received lux reading: %.1f", lux)
            brightness_pct = lux_to_brightness(lux)
            logger.info("Mapped lux %.1f → brightness %d %%", lux, brightness_pct)

            try:
                analyzer = BrightnessAnalyzer(0)
                analyzer.setBrightness(brightness_pct)
                logger.info("Brightness set from WebSocket lux value")
            except Exception as e:
                print(f"Automation Failed: {e}")
            finally:
                sensor.stop()

    # Keep discovery alive while other threads may need it; the daemon
    # thread will exit when the process exits.
    logger.info("Done.")
