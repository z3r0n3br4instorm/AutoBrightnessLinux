"""WebSocket client for the SensorServer Android app.

Connects to the WebSocket endpoint discovered via mDNS and continuously
receives sensor readings, exposing the latest lux value for brightness
calculations.
"""

import asyncio
import json
import logging
import threading
from typing import Any

import websockets

from .sensor_discovery import SensorDiscovery

logger = logging.getLogger(__name__)

# The SensorServer WebSocket endpoint for the light sensor.
_SENSOR_PATH = "/sensor/connect?type=android.sensor.light"


# Known Android sensor types that produce lux readings.
_LIGHT_SENSOR_TYPES = frozenset({
    "android.sensor.light",
    "android.sensor.ambient_light",
    "android.sensor.als",
    "light",
    "lux",
    "illuminance",
    "als",
})

# ---------------------------------------------------------------------------
# Mapping from each Android sensor type string to the index in the ``values``
# array that carries the lux reading.  Falls back to index 0 for unknown
# light-sensor types (most sensors only emit a single value anyway).
# ---------------------------------------------------------------------------
_LUX_INDEX: dict[str, int] = {
    "android.sensor.light": 0,
    "android.sensor.ambient_light": 0,
    "android.sensor.als": 0,
    "light": 0,
    "lux": 0,
    "illuminance": 0,
    "als": 0,
}


def _extract_lux(payload: Any) -> float | None:
    """Pull a lux / light value out of a JSON message.

    Handles the Android ``SensorEvent`` shape produced by the SensorServer
    app, as well as several common shorthand shapes::

        {"values": [342.0], "accuracy": 3, "timestamp": 123456789, ...}
        {"type": "android.sensor.light", "values": [342.0], ...}
        {"lux": 342.1}
        {"sensor": "light", "value": 342.1}
    """
    if isinstance(payload, (int, float)):
        return float(payload)

    if isinstance(payload, dict):
        # ── Android SensorEvent shape: {"values": [lux, ...]} ──────────
        if "values" in payload and isinstance(payload["values"], list):
            vals = payload["values"]
            if len(vals) > 0 and isinstance(vals[0], (int, float)):
                # If there's a "type" key we can pick the right index
                idx = _LUX_INDEX.get(payload.get("type", ""), 0)
                if idx < len(vals) and isinstance(vals[idx], (int, float)):
                    return float(vals[idx])
                return float(vals[0])

        # ── Direct keys ─────────────────────────────────────────────────
        for key in ("lux", "light", "illuminance", "luminance", "als"):
            if key in payload and isinstance(payload[key], (int, float)):
                return float(payload[key])

        # ── Nested dict: {"values": {"lux": ...}}, {"data": {"lux": ...}} ─
        for sub_key in ("values", "light", "sensor_data", "data"):
            if isinstance(payload.get(sub_key), dict):
                nested = _extract_lux(payload[sub_key])
                if nested is not None:
                    return nested

        # ── {"sensor": "light", "value": 123} pattern ───────────────────
        if payload.get("sensor") in _LIGHT_SENSOR_TYPES:
            val = payload.get("value")
            if isinstance(val, (int, float)):
                return float(val)

        # ── Generic fallback ────────────────────────────────────────────
        if "value" in payload and isinstance(payload["value"], (int, float)):
            return float(payload["value"])

    return None


class WebSocketSensor:
    """Async WebSocket client that bridges to sync code via a background loop.

    Usage from synchronous code::

        discovery = SensorDiscovery()
        discovery.start()

        sensor = WebSocketSensor(discovery)
        sensor.start()

        lux = sensor.lux          # most recent reading (None until first msg)
        sensor.stop()
    """

    def __init__(self, discovery: SensorDiscovery) -> None:
        self._discovery = discovery
        self._lux: float | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected = False

    # -- public properties (thread-safe) ----------------------------------

    @property
    def lux(self) -> float | None:
        """Latest lux reading, or *None* if nothing received yet."""
        with self._lock:
            return self._lux

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    # -- async core -------------------------------------------------------

    async def _connect_and_read(self) -> None:
        """Reconnection loop: connect → read → reconnect on disconnect."""
        while self._running:
            base = self._discovery.ws_url
            if base is None:
                logger.debug("No sensor URL yet – waiting for discovery…")
                await asyncio.sleep(2.0)
                continue
            url = base + _SENSOR_PATH

            try:
                logger.info("Connecting to %s", url)
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    open_timeout=10,
                ) as ws:
                    with self._lock:
                        self._connected = True
                    logger.info("Connected to SensorServer at %s", url)

                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            payload = json.loads(message)
                        except json.JSONDecodeError:
                            logger.debug("Non-JSON message: %s", message[:120])
                            continue

                        lux = _extract_lux(payload)
                        if lux is not None:
                            with self._lock:
                                self._lux = lux
                            logger.debug("Lux: %.1f", lux)
                        else:
                            logger.debug(
                                "Unrecognised payload shape: %s",
                                json.dumps(payload)[:200],
                            )

            except (
                websockets.ConnectionClosed,
                ConnectionRefusedError,
                OSError,
                asyncio.TimeoutError,
            ) as exc:
                logger.warning("WebSocket disconnected: %s – will retry", exc)
            except Exception:
                logger.exception("Unexpected WebSocket error – will retry")
            finally:
                with self._lock:
                    self._connected = False

            if self._running:
                await asyncio.sleep(3.0)  # back-off before reconnecting

    def _run_loop(self) -> None:
        """Entry-point for the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_read())
        finally:
            self._loop.close()

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Launch the WebSocket client in a daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the client and join the background thread."""
        self._running = False
        # Schedule a no-op to unblock the event loop if it's waiting
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def wait_for_reading(self, timeout: float = 15.0) -> float | None:
        """Block until we have at least one lux reading, then return it.

        Returns *None* if *timeout* expires before a reading arrives.
        """
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._lux is not None:
                    return self._lux
            time.sleep(0.25)
        return None
