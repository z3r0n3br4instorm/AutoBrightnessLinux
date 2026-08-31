"""OpenTone: Ambient color temperature estimation and display synchronization using Redshift."""

import os
import shutil
import subprocess
import logging
from typing import Optional, Tuple, Union

from core.config import (
    get_opentone_min_temp,
    get_opentone_max_temp,
    get_opentone_smoothing_factor,
    get_opentone_min_change_threshold,
)

logger = logging.getLogger("opentone")

OPENTONE_FILE = os.path.expanduser("~/.local/share/opentone.ztrf")


class OpenTone:
    """Estimates ambient color temperature from camera frames and adjusts display color temperature via Redshift."""

    def __init__(
        self,
        cameraid: Optional[int] = None,
        min_temp: Optional[int] = None,
        max_temp: Optional[int] = None,
        smoothing_factor: Optional[float] = None,
        min_change_threshold: Optional[int] = None,
    ):
        """Initialize OpenTone analyzer.

        Args:
            cameraid: Camera device index, or None for camera-less operations.
            min_temp: Minimum color temperature in Kelvin (e.g. 2700 or 3000).
            max_temp: Maximum color temperature in Kelvin (e.g. 6500 or 7500).
            smoothing_factor: EMA smoothing factor (0.0 to 1.0).
            min_change_threshold: Minimum change in Kelvin required to trigger an update.
        """
        self.cameraid = cameraid
        self.camera = None
        if cameraid is not None:
            import cv2

            self.camera = cv2.VideoCapture(cameraid)
            try:
                self.camera.set(cv2.CAP_PROP_AUTO_WB, 0)
            except Exception:
                pass

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
        self.previous_temp: Optional[int] = self.get_current_temperature()

    def __del__(self):
        if self.camera is not None:
            try:
                self.camera.release()
            except Exception:
                pass

    def capture_image(self):
        """Capture a single frame from the camera and return it as a PIL Image."""
        import cv2
        from PIL import Image

        if self.camera is None:
            raise RuntimeError("No camera configured for OpenTone analyzer.")
        ret, frame = self.camera.read()
        if not ret or frame is None:
            raise RuntimeError("Failed to capture image from camera.")
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    def estimate_color_temperature(self, image=None) -> float:
        """Estimate the Correlated Color Temperature (CCT) in Kelvin from an image.

        Uses robust illuminant estimation (Shades of Gray combined with specular/bright
        patch extraction), transforms to CIE 1931 xy chromaticity space, and applies
        McCamy's formula.

        Args:
            image: PIL Image, numpy array (RGB or BGR), or None to capture from camera.

        Returns:
            Estimated CCT in Kelvin, clamped to [min_temp, max_temp].
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
            logger.warning("Zero luminance detected; defaulting CCT to 6500K")
            return 6500.0

        # CIE chromaticity coordinates
        x = X / total
        y = Y / total

        # McCamy's approximation formula for CCT
        denom = 0.1858 - y
        if abs(denom) < 1e-6:
            denom = 1e-6 if denom >= 0 else -1e-6

        n = (x - 0.3320) / denom
        cct = 449.0 * (n ** 3) + 3525.0 * (n ** 2) + 6823.3 * n + 5520.33

        # Guard against extreme negative or NaN results
        if np.isnan(cct) or cct < 1000.0:
            cct = float(self.min_temp)
        elif cct > 25000.0:
            cct = float(self.max_temp)

        # Clamp to configured range
        clamped_cct = max(float(self.min_temp), min(float(self.max_temp), cct))
        return clamped_cct

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

    def get_current_temperature(self) -> int:
        """Read the currently applied color temperature from state file or default to 6500K."""
        if os.path.exists(OPENTONE_FILE):
            try:
                with open(OPENTONE_FILE, "r") as f:
                    val = int(f.read().strip())
                    if 1000 <= val <= 25000:
                        return val
            except Exception:
                pass
        return 6500

    def set_temperature(
        self,
        target_temp: int,
        smooth_step: bool = False,
        step_size: int = 100,
        delay: float = 0.02,
    ) -> bool:
        """Apply color temperature systemwide using Redshift.

        Args:
            target_temp: Target temperature in Kelvin (e.g. 3000 to 6500).
            smooth_step: If True, transition gradually to target temperature.
            step_size: Step size in Kelvin for gradual transition.
            delay: Delay in seconds between steps.

        Returns:
            True if Redshift command succeeded, False otherwise.
        """
        if not shutil.which("redshift"):
            logger.error("Redshift binary not found in PATH. Please install redshift.")
            return False

        if target_temp < 1000 or target_temp > 25000:
            raise ValueError(f"Target temperature {target_temp}K is outside valid Redshift range (1000-25000K).")

        current = self.get_current_temperature()

        try:
            if smooth_step and abs(target_temp - current) > step_size:
                import time

                direction = 1 if target_temp > current else -1
                temp = current
                while abs(temp - target_temp) > step_size:
                    temp += step_size * direction
                    subprocess.run(
                        ["redshift", "-P", "-O", str(temp)],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    time.sleep(delay)

            subprocess.run(
                ["redshift", "-P", "-O", str(target_temp)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            os.makedirs(os.path.dirname(OPENTONE_FILE), exist_ok=True)
            with open(OPENTONE_FILE, "w") as f:
                f.write(str(target_temp))
            self.previous_temp = target_temp
            logger.info("Applied color temperature %dK via Redshift", target_temp)
            return True
        except subprocess.CalledProcessError as e:
            logger.error("Redshift failed to set color temperature: %s", e)
            return False

    def reset(self) -> bool:
        """Reset display color temperature using Redshift (-x)."""
        if not shutil.which("redshift"):
            logger.error("Redshift binary not found in PATH.")
            return False
        try:
            subprocess.run(
                ["redshift", "-x"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if os.path.exists(OPENTONE_FILE):
                try:
                    os.remove(OPENTONE_FILE)
                except Exception:
                    pass
            self.previous_temp = 6500
            logger.info("Display color temperature reset to neutral default.")
            return True
        except subprocess.CalledProcessError as e:
            logger.error("Redshift failed to reset: %s", e)
            return False


# Backward compatibility alias
OpenToneAnalyzer = OpenTone


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

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
    raw_cct = opentone.estimate_color_temperature()
    smoothed_cct = opentone.smooth_temperature(raw_cct)
    print(f"Raw CCT: {raw_cct:.1f} K, Smoothed CCT: {smoothed_cct} K")
    success = opentone.set_temperature(smoothed_cct)
    if success:
        print(f"Successfully applied {smoothed_cct}K display color temperature.")
    else:
        print("Failed to apply color temperature.")
