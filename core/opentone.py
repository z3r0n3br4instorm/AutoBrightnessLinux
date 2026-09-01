"""OpenTone: Ambient color temperature estimation and display synchronization using Redshift."""

import glob
import os
import shutil
import subprocess
import logging
import time
from typing import Optional, Tuple, Union

from core.config import (
    get_opentone_min_temp,
    get_opentone_max_temp,
    get_opentone_smoothing_factor,
    get_opentone_min_change_threshold,
    get_opentone_transition_duration,
    get_opentone_transition_steps,
)

logger = logging.getLogger("opentone")

OPENTONE_FILE = os.path.expanduser("~/.local/share/opentone.ztrf")

# Neutral daylight white point — the "do nothing" display temperature.
NEUTRAL_TEMP = 6500

# Redshift's own accepted range, independent of the user's configured window.
REDSHIFT_MIN_TEMP = 1000
REDSHIFT_MAX_TEMP = 25000

# To estimate the ambient illuminant the camera has to behave like a
# colorimeter, so its white balance must be pinned to a known reference:
#   * auto white balance cancels out the very colour cast we are measuring;
#   * merely *disabling* auto white balance is not enough — the driver keeps
#     whatever value it last held (observed on this MacBook: 3204 K, and 2800 K
#     on a cold open, the control's minimum). That is a strong blue-boosting
#     correction, so every frame reads blue, the CCT estimate lands around
#     13000–25000 K, and clamping flattens it to max_temp. The result is a
#     display temperature of "neutral" on every run — i.e. no visible effect.
# Pinning WB to the control's neutral default fixes the bias at the source.
WB_REFERENCE_KELVIN = 6500

# Frames discarded before measuring: auto-exposure needs time to settle
# (mean luminance was observed climbing from 52 to 100 over the first ~10
# frames, and the very first frame after open is the worst offender).
WARMUP_FRAMES = 12

# Frames combined per measurement; the median rejects flicker and noise.
MEASUREMENT_SAMPLES = 5

# Changes smaller than this are applied in one go — ramping a barely-visible
# shift only burns redshift invocations.
MIN_RAMP_DELTA_K = 40


def _systemd_user_env(key: str) -> Optional[str]:
    """Read a variable from the systemd user manager's environment.

    Authoritative when available: the graphical session imports the real
    DISPLAY/XAUTHORITY there, so this beats guessing from the filesystem.
    """
    if not shutil.which("systemctl"):
        return None
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None

    for line in result.stdout.splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == key and value:
            return value.strip()
    return None


def _detect_display() -> Optional[str]:
    """Guess a DISPLAY value from the X11 sockets that exist."""
    for socket in sorted(glob.glob("/tmp/.X11-unix/X*")):
        number = os.path.basename(socket)[1:]
        if number.isdigit():
            return f":{number}"
    return None


def _detect_xauthority() -> Optional[str]:
    """Find a readable X authority file.

    Only X-authority-looking names are considered: a runtime directory also
    holds ICEauthority, which is a different protocol and useless to redshift.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    candidates = [
        path
        for path in sorted(glob.glob(os.path.join(runtime, "*")))
        if "xauth" in os.path.basename(path).lower()
    ]
    candidates.append(os.path.expanduser("~/.Xauthority"))

    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.R_OK) and os.path.getsize(path):
            return path
    return None


def _redshift_env() -> dict:
    """Environment for Redshift, filling in X credentials when they are absent.

    Redshift needs a display server connection. A process launched from a
    systemd user unit that started before the graphical session has no DISPLAY
    or XAUTHORITY — and unlike the user manager's environment, a running unit's
    is never updated retroactively — so redshift fails with
    ``XOpenDisplay``/``Initialization of randr failed`` and exit status 1.
    Recovering the values from the running session makes that case work instead
    of silently doing nothing.
    """
    env = os.environ.copy()

    if env.get("WAYLAND_DISPLAY"):
        return env  # Wayland: redshift needs the drm method, X vars are moot.

    for key, detect in (("DISPLAY", _detect_display), ("XAUTHORITY", _detect_xauthority)):
        if env.get(key):
            continue
        value = _systemd_user_env(key)
        source = "systemd user environment"
        if not value:
            value = detect()
            source = "autodetection"
        if value:
            env[key] = value
            logger.info("%s was unset; using %s from %s", key, value, source)

    return env


def _run_redshift(args: list) -> bool:
    """Run redshift, logging its actual output on failure.

    Output is captured rather than discarded: swallowing stderr previously made
    a display-server failure indistinguishable from success-with-no-effect.
    """
    env = _redshift_env()
    try:
        subprocess.run(
            ["redshift", *args],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip().replace("\n", " | ")
        logger.error(
            "redshift %s failed (exit %d): %s",
            " ".join(args),
            e.returncode,
            detail or "no output",
        )
        if "XOpenDisplay" in detail or "randr failed" in detail.lower():
            logger.error(
                "Redshift could not reach a display server (DISPLAY=%r, "
                "XAUTHORITY=%r). If this ran from a systemd user unit started "
                "before your graphical session, fix it with: systemctl --user "
                "import-environment DISPLAY XAUTHORITY && systemctl --user "
                "restart <unit>. Under Wayland, use gammastep/wlsunset/hyprsunset "
                "instead of redshift.",
                env.get("DISPLAY"),
                env.get("XAUTHORITY"),
            )
        return False


class OpenTone:
    """Estimates ambient color temperature from camera frames and adjusts display color temperature via Redshift."""

    def __init__(
        self,
        cameraid: Optional[int] = None,
        min_temp: Optional[int] = None,
        max_temp: Optional[int] = None,
        smoothing_factor: Optional[float] = None,
        min_change_threshold: Optional[int] = None,
        wb_reference: int = WB_REFERENCE_KELVIN,
        warmup_frames: int = WARMUP_FRAMES,
        samples: int = MEASUREMENT_SAMPLES,
    ):
        """Initialize OpenTone analyzer.

        Args:
            cameraid: Camera device index, or None for camera-less operations.
            min_temp: Minimum color temperature in Kelvin (e.g. 2700 or 3000).
            max_temp: Maximum color temperature in Kelvin (e.g. 6500 or 7500).
            smoothing_factor: EMA smoothing factor (0.0 to 1.0).
            min_change_threshold: Minimum change in Kelvin required to trigger an update.
            wb_reference: Camera white balance is pinned here while measuring.
            warmup_frames: Frames discarded so auto-exposure can settle.
            samples: Frames combined (median) per measurement.
        """
        self.cameraid = cameraid
        self.camera = None
        self.wb_reference = wb_reference
        self.warmup_frames = max(0, warmup_frames)
        self.samples = max(1, samples)
        self.wb_locked = False
        self._warmed = False

        if cameraid is not None:
            import cv2

            self.camera = cv2.VideoCapture(cameraid)
            if not self.camera.isOpened():
                # Usually another handle on the device is still open.
                self.camera.release()
                self.camera = None
                raise RuntimeError(
                    f"Could not open camera {cameraid} for OpenTone — it may "
                    f"still be held open by another capture."
                )
            self._configure_camera()

        self.min_temp = min_temp if min_temp is not None else get_opentone_min_temp()
        self.max_temp = max_temp if max_temp is not None else get_opentone_max_temp()
        self.smoothing_factor = (
            smoothing_factor
            if smoothing_factor is not None
            else get_opentone_smoothing_factor()
        )
        self.min_change_threshold = (
            min_change_threshold
            if min_change_threshold is not None
            else get_opentone_min_change_threshold()
        )
        # None on a first run (or after --reset-tone): smooth_temperature then
        # adopts the first measurement outright rather than easing from neutral.
        self.previous_temp: Optional[int] = self.read_state_temperature()

    def release(self) -> None:
        """Release the camera so another capture can open the device."""
        if self.camera is not None:
            try:
                self.camera.release()
            except Exception:
                pass
            self.camera = None

    def __del__(self):
        self.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    def _configure_camera(self) -> None:
        """Pin the camera's white balance to a known reference.

        Both steps are required: disabling auto white balance alone leaves the
        driver's stale WB value in place, which biases the illuminant estimate.
        Values are read back because UVC drivers silently ignore controls they
        do not implement.
        """
        import cv2

        if self.camera is None:
            return

        try:
            self.camera.set(cv2.CAP_PROP_AUTO_WB, 0)
            self.camera.set(cv2.CAP_PROP_WB_TEMPERATURE, self.wb_reference)
            auto_wb = self.camera.get(cv2.CAP_PROP_AUTO_WB)
            wb_temp = self.camera.get(cv2.CAP_PROP_WB_TEMPERATURE)
        except Exception as e:
            logger.warning("Could not configure camera white balance: %s", e)
            return

        # Tolerance covers drivers that quantise the control's value.
        self.wb_locked = auto_wb == 0 and abs(wb_temp - self.wb_reference) <= 100
        if self.wb_locked:
            logger.info("Camera white balance pinned to %dK", int(wb_temp))
        else:
            logger.warning(
                "Camera white balance not pinned (auto_wb=%s, wb_temperature=%s, "
                "wanted %dK) — colour temperature estimates will be biased. Check "
                "the control's range with: v4l2-ctl -d /dev/video%s --list-ctrls",
                auto_wb,
                wb_temp,
                self.wb_reference,
                self.cameraid,
            )

    def warmup(self) -> None:
        """Discard frames so auto-exposure settles before measuring."""
        if self.camera is None or self._warmed:
            return
        for _ in range(self.warmup_frames):
            self.camera.read()
            time.sleep(0.02)
        self._warmed = True

    def capture_image(self):
        """Capture a single frame from the camera and return it as a PIL Image."""
        import cv2
        from PIL import Image

        if self.camera is None:
            raise RuntimeError("No camera configured for OpenTone analyzer.")
        # Measuring a cold first frame is a large error source, so settle first.
        self.warmup()
        ret, frame = self.camera.read()
        if not ret or frame is None:
            raise RuntimeError("Failed to capture image from camera.")
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    def measure_cct(self, samples: Optional[int] = None) -> float:
        """Return the median raw CCT over several frames, in Kelvin.

        A single frame is noisy and flickers under mains lighting, so the
        median of a few is markedly more stable. The result is unclamped —
        pass it through :meth:`clamp_temperature` before applying.
        """
        import numpy as np

        if self.camera is None:
            raise RuntimeError("No camera configured for OpenTone analyzer.")

        n = self.samples if samples is None else max(1, samples)
        readings = []
        for _ in range(n):
            try:
                readings.append(self.estimate_color_temperature(self.capture_image()))
            except RuntimeError as e:
                logger.debug("Skipped a measurement frame: %s", e)

        if not readings:
            raise RuntimeError("No usable frames captured for CCT measurement.")

        median = float(np.median(readings))
        logger.info(
            "Measured ambient CCT %.0fK (median of %d frames, range %.0f–%.0fK)",
            median,
            len(readings),
            min(readings),
            max(readings),
        )
        return median

    def estimate_color_temperature(self, image=None) -> float:
        """Estimate the Correlated Color Temperature (CCT) in Kelvin from an image.

        Uses robust illuminant estimation (Shades of Gray combined with specular/bright
        patch extraction), transforms to CIE 1931 xy chromaticity space, and applies
        McCamy's formula.

        Args:
            image: PIL Image, numpy array (RGB or BGR), or None to capture from camera.

        Returns:
            Raw estimated CCT in Kelvin, clamped only to Redshift's physical
            range. Pass it through :meth:`clamp_temperature` before applying.
        """
        import numpy as np

        if image is None:
            image = self.capture_image()

        # Convert to numpy RGB array if PIL Image
        if hasattr(image, "convert"):
            image_array = np.array(image.convert("RGB"), dtype=np.float64)
        else:
            image_array = np.array(image, dtype=np.float64)
            if len(image_array.shape) != 3 or image_array.shape[2] != 3:
                raise ValueError(f"Expected 3-channel RGB image, got shape {image_array.shape}")

        h, w, _ = image_array.shape
        # Center region ROI (middle 60% of frame)
        y1, y2 = int(h * 0.2), int(h * 0.8)
        x1, x2 = int(w * 0.2), int(w * 0.8)
        roi = image_array[y1:y2, x1:x2]

        pixels = roi.reshape(-1, 3)

        # Standard sRGB luminance to filter extreme outliers
        luminance = 0.2126 * pixels[:, 0] + 0.7152 * pixels[:, 1] + 0.0722 * pixels[:, 2]

        # Ignore underexposed camera noise (< 15) and clipped sensor highlights (> 245)
        valid_mask = (luminance > 15.0) & (luminance < 245.0)
        valid_pixels = pixels[valid_mask] if np.any(valid_mask) else pixels
        valid_lum = luminance[valid_mask] if np.any(valid_mask) else luminance

        # 1. Shades of Gray illuminant estimate (Minkowski p=6 norm)
        p = 6.0
        shades_rgb = np.power(np.mean(np.power(valid_pixels, p), axis=0), 1.0 / p)

        # 2. White Patch / Specular reflection estimate (top 10% brightest valid pixels)
        top_threshold = np.percentile(valid_lum, 90.0)
        bright_pixels = valid_pixels[valid_lum >= top_threshold]
        bright_rgb = np.mean(bright_pixels, axis=0) if len(bright_pixels) > 0 else shades_rgb

        # Blend: 50% Shades of Gray + 50% White Patch for stable illuminant estimation
        illuminant_rgb = 0.5 * shades_rgb + 0.5 * bright_rgb
        r, g, b = illuminant_rgb / 255.0

        # Linearize sRGB channels (inverse gamma companding)
        def linearize(c: float) -> float:
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        r_lin = linearize(max(0.0, min(1.0, r)))
        g_lin = linearize(max(0.0, min(1.0, g)))
        b_lin = linearize(max(0.0, min(1.0, b)))

        # Convert to CIE 1931 XYZ using standard sRGB D65 matrix
        X = 0.4124564 * r_lin + 0.3575761 * g_lin + 0.1804375 * b_lin
        Y = 0.2126729 * r_lin + 0.7151522 * g_lin + 0.0721750 * b_lin
        Z = 0.0193339 * r_lin + 0.1191920 * g_lin + 0.9503041 * b_lin

        total = X + Y + Z
        if total <= 1e-6:
            logger.warning("Zero luminance detected; defaulting CCT to %dK", NEUTRAL_TEMP)
            return float(NEUTRAL_TEMP)

        # CIE chromaticity coordinates
        x = X / total
        y = Y / total

        # McCamy's approximation formula for CCT
        denom = 0.1858 - y
        if abs(denom) < 1e-6:
            denom = 1e-6 if denom >= 0 else -1e-6

        n = (x - 0.3320) / denom
        cct = 449.0 * (n ** 3) + 3525.0 * (n ** 2) + 6823.3 * n + 5520.33

        # Guard against NaN or physically meaningless results by clamping to
        # Redshift's own range. This is deliberately *not* the user's configured
        # window — squeezing the raw estimate into [min_temp, max_temp] here
        # would hide whether the measurement was sane, which is exactly what
        # masked the white-balance bias bug.
        if np.isnan(cct):
            logger.warning("CCT estimate was NaN; falling back to %dK", NEUTRAL_TEMP)
            return float(NEUTRAL_TEMP)

        return max(float(REDSHIFT_MIN_TEMP), min(float(REDSHIFT_MAX_TEMP), cct))

    def clamp_temperature(self, cct: float) -> int:
        """Clamp a raw CCT to the configured [min_temp, max_temp] window.

        Logs when the raw estimate falls outside the window — a reading pinned
        at either end usually means the measurement is wrong rather than the
        room being genuinely that warm or cool.
        """
        clamped = max(float(self.min_temp), min(float(self.max_temp), cct))
        if clamped != cct:
            logger.info(
                "Raw CCT %.0fK is outside the configured %d–%dK window; using %.0fK",
                cct,
                self.min_temp,
                self.max_temp,
                clamped,
            )
            if not self.wb_locked and self.camera is not None:
                logger.warning(
                    "White balance is not pinned, which biases estimates towards "
                    "the window edge — see the earlier warning."
                )
        return int(round(clamped))

    def smooth_temperature(self, new_temp: float) -> int:
        """Apply exponential moving average and hysteresis threshold to prevent jitter."""
        if self.previous_temp is None:
            self.previous_temp = int(round(new_temp))
            return self.previous_temp

        smoothed = (
            self.smoothing_factor * new_temp
            + (1.0 - self.smoothing_factor) * self.previous_temp
        )

        if abs(smoothed - self.previous_temp) >= self.min_change_threshold:
            self.previous_temp = int(round(smoothed))
            return self.previous_temp
        else:
            return int(round(self.previous_temp))

    def read_state_temperature(self) -> Optional[int]:
        """Return the last applied temperature, or None if there is no valid state.

        None matters: it lets the first run adopt its measurement directly
        instead of easing towards it from an assumed neutral, which otherwise
        guarantees a weak first adjustment.
        """
        if os.path.exists(OPENTONE_FILE):
            try:
                with open(OPENTONE_FILE, "r") as f:
                    val = int(f.read().strip())
                    if REDSHIFT_MIN_TEMP <= val <= REDSHIFT_MAX_TEMP:
                        return val
            except Exception:
                pass
        return None

    def get_current_temperature(self) -> int:
        """Read the currently applied color temperature, defaulting to neutral."""
        state = self.read_state_temperature()
        return state if state is not None else NEUTRAL_TEMP

    def set_temperature(
        self,
        target_temp: int,
        smooth: bool = True,
        duration: Optional[float] = None,
        steps: Optional[int] = None,
    ) -> bool:
        """Apply color temperature systemwide using Redshift.

        The change is ramped rather than jumped, so the shift is not jarring.
        The ramp is time-based: a fixed number of steps spread over a fixed
        duration, so a large change takes no longer than a small one and the
        number of ``redshift`` invocations stays bounded either way.

        Args:
            target_temp: Target temperature in Kelvin (e.g. 3000 to 6500).
            smooth: Ramp gradually. False applies in a single step.
            duration: Ramp length in seconds (default OPENTONE_TRANSITION_DURATION).
            steps: Intermediate steps (default OPENTONE_TRANSITION_STEPS).

        Returns:
            True if Redshift command succeeded, False otherwise.
        """
        if not shutil.which("redshift"):
            logger.error("Redshift binary not found in PATH. Please install redshift.")
            return False

        if target_temp < REDSHIFT_MIN_TEMP or target_temp > REDSHIFT_MAX_TEMP:
            raise ValueError(
                f"Target temperature {target_temp}K is outside valid Redshift "
                f"range ({REDSHIFT_MIN_TEMP}-{REDSHIFT_MAX_TEMP}K)."
            )

        if duration is None:
            duration = get_opentone_transition_duration()
        if steps is None:
            steps = get_opentone_transition_steps()

        current = self.get_current_temperature()
        delta = target_temp - current

        if smooth and duration > 0 and steps > 1 and abs(delta) >= MIN_RAMP_DELTA_K:
            logger.info(
                "Ramping %dK → %dK over %.2fs in %d steps",
                current,
                target_temp,
                duration,
                steps,
            )
            per_step = duration / steps
            for step in range(1, steps):
                progress = step / steps
                # Smoothstep easing: starts and ends gently, so the transition
                # reads as a fade rather than a linear sweep.
                eased = progress * progress * (3.0 - 2.0 * progress)
                intermediate = int(round(current + delta * eased))
                started = time.perf_counter()
                if not _run_redshift(["-P", "-O", str(intermediate)]):
                    return False
                # Subtract the invocation cost (~17 ms) so total wall time
                # tracks `duration` instead of overshooting it.
                remaining = per_step - (time.perf_counter() - started)
                if remaining > 0:
                    time.sleep(remaining)

        if not _run_redshift(["-P", "-O", str(target_temp)]):
            return False

        try:
            os.makedirs(os.path.dirname(OPENTONE_FILE), exist_ok=True)
            with open(OPENTONE_FILE, "w") as f:
                f.write(str(target_temp))
        except OSError as e:
            # The display did change, so this is not a failure — but the next
            # run would misjudge its starting point.
            logger.warning("Could not persist state to %s: %s", OPENTONE_FILE, e)

        self.previous_temp = target_temp
        logger.info("Applied color temperature %dK via Redshift", target_temp)
        return True

    def reset(self) -> bool:
        """Reset display color temperature using Redshift (-x)."""
        if not shutil.which("redshift"):
            logger.error("Redshift binary not found in PATH.")
            return False
        if not _run_redshift(["-x"]):
            return False

        if os.path.exists(OPENTONE_FILE):
            try:
                os.remove(OPENTONE_FILE)
            except OSError as e:
                logger.warning("Could not remove %s: %s", OPENTONE_FILE, e)

        # None, not NEUTRAL_TEMP: with no state the next run adopts its own
        # measurement instead of easing away from an assumed value.
        self.previous_temp = None
        logger.info("Display color temperature reset to neutral default.")
        return True


# Backward compatibility alias
OpenToneAnalyzer = OpenTone


if __name__ == "__main__":
    import sys
    from core.log_setup import setup_logging

    setup_logging()

    import cv2
    camera_id = None
    for idx in range(10):
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                camera_id = idx
                break

    if camera_id is None:
        logger.error("No working camera found.")
        sys.exit(1)

    opentone = OpenTone(camera_id)
    raw_cct = opentone.measure_cct()
    target_cct = opentone.clamp_temperature(raw_cct)
    smoothed_cct = opentone.smooth_temperature(target_cct)
    print(f"Raw CCT: {raw_cct:.1f} K, Target: {target_cct} K, Smoothed CCT: {smoothed_cct} K")
    success = opentone.set_temperature(smoothed_cct)
    if success:
        print(f"Successfully applied {smoothed_cct}K display color temperature.")
    else:
        print("Failed to apply color temperature.")
