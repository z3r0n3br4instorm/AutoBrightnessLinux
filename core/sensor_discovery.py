"""SensorServer discovery via avahi-browse (mDNS/DNS-SD).

Runs a background thread that periodically queries avahi-browse for the
_websocket._tcp service and keeps the IP address and port up to date.
"""

import re
import subprocess
import threading
import time
import logging

logger = logging.getLogger(__name__)


class SensorDiscovery:
    """Discover the SensorServer WebSocket endpoint via avahi-browse.

    Runs a daemon thread that polls avahi-browse on an interval so the
    connection info stays current when the server IP changes (e.g. DHCP
    renewal, device reconnect).
    """

    def __init__(self, poll_interval: float = 30.0):
        self._poll_interval = poll_interval
        self._lock = threading.Lock()
        self._hostname: str | None = None
        self._address: str | None = None
        self._port: int | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    # -- public read-only properties (thread-safe) ------------------------

    @property
    def address(self) -> str | None:
        with self._lock:
            return self._address

    @property
    def port(self) -> int | None:
        with self._lock:
            return self._port

    @property
    def hostname(self) -> str | None:
        with self._lock:
            return self._hostname

    @property
    def ws_url(self) -> str | None:
        """Return a full ws:// URL if everything is known, else None."""
        with self._lock:
            if self._address and self._port:
                return f"ws://{self._address}:{self._port}"
            return None

    @property
    def is_available(self) -> bool:
        with self._lock:
            return self._address is not None and self._port is not None

    # -- discovery --------------------------------------------------------

    def _query_avahi(self) -> tuple[str | None, str | None, int | None]:
        """Run avahi-browse once and return (hostname, address, port).

        Uses ``-t`` to terminate after receiving the cached record and
        ``-r`` to resolve details (address, port, txt).
        """
        try:
            result = subprocess.run(
                ["avahi-browse", "-r", "-t", "_websocket._tcp"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError:
            logger.warning("avahi-browse not found – is avahi-utils installed?")
            return None, None, None
        except subprocess.TimeoutExpired:
            logger.warning("avahi-browse timed out")
            return None, None, None

        output = result.stdout
        if result.returncode != 0 or not output.strip():
            logger.debug("avahi-browse returned nothing for _websocket._tcp")
            return None, None, None

        return self._parse_output(output)

    @staticmethod
    def _parse_output(
        output: str,
    ) -> tuple[str | None, str | None, int | None]:
        """Pull hostname, address and port out of avahi-browse human output.

        Example line we're interested in::

            = wlp3s0 IPv4 SensorServer   _websocket._tcp   local
               hostname = [Android_I0OF8IC9.local]
               address = [192.168.8.104]
               port = [8081]
               txt = []
        """
        hostname = None
        address = None
        port = None

        # Prefer IPv4 entries; they appear after IPv6 in the output, so
        # later values naturally overwrite earlier ones.
        current_section = None
        for line in output.splitlines():
            line = line.rstrip()
            if line.startswith("="):
                current_section = line
                continue

            # Match indented key = [value] lines
            m = re.match(r"\s+(\w+)\s*=\s*\[([^\]]*)\]", line)
            if m:
                key, value = m.group(1), m.group(2).strip()
                if key == "hostname":
                    hostname = value or None
                elif key == "address":
                    address = value or None
                elif key == "port":
                    try:
                        port = int(value)
                    except (ValueError, TypeError):
                        port = None

        return hostname, address, port

    def _poll_loop(self) -> None:
        """Run in a background thread; polls avahi forever."""
        logger.info(
            "Sensor discovery started (poll every %.0f s)", self._poll_interval
        )
        while self._running:
            try:
                hostname, address, port = self._query_avahi()
            except Exception:
                logger.exception("Unexpected error during avahi query")
                hostname, address, port = None, None, None

            with self._lock:
                changed = (
                    hostname != self._hostname
                    or address != self._address
                    or port != self._port
                )
                if changed:
                    logger.info(
                        "SensorServer updated → hostname=%s address=%s port=%s",
                        hostname,
                        address,
                        port,
                    )
                self._hostname = hostname
                self._address = address
                self._port = port

            time.sleep(self._poll_interval)

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Launch the background discovery thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the background thread to stop (best-effort)."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def wait_until_available(self, timeout: float = 30.0) -> bool:
        """Block until the sensor is discovered or *timeout* expires."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_available:
                return True
            time.sleep(0.5)
        return False
