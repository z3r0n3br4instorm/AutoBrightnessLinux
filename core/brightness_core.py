import os
import time
import subprocess

from core.config import get_min_brightness
from core import ztmetro_backend

# OpenCV / PIL / numpy are imported lazily inside the camera methods so that
# lux-based sources (the built-in ALS, the remote sensor) work on a machine
# with none of the camera stack installed.

bright_file = os.path.expanduser("~/.local/share/brightness.ztrf")

class BrightnessAnalyzer:
    def __init__(self, cameraid=None, smoothing_factor=0.3, min_change_threshold=5):
        """``cameraid`` may be None when only the brightness-setting helpers
        are needed — that avoids powering on the webcam for lux-based sources.
        """
        self.image = None
        if cameraid is None:
            self.camera = None
        else:
            import cv2
            self.camera = cv2.VideoCapture(cameraid)
        self.previous_brightness = None
        self.smoothing_factor = smoothing_factor
        self.min_change_threshold = min_change_threshold


    def release(self):
        """Release the camera so another capture (e.g. OpenTone) can open it."""
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

    def capture_image(self):
        import cv2
        from PIL import Image

        if self.camera is None:
            raise RuntimeError("No camera configured for this analyzer.")
        ret, frame = self.camera.read()
        if not ret:
            raise RuntimeError("Failed to capture image from camera.")
        self.image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        return self.image

        
    def get_prominent_color(self, image):
        import cv2
        import numpy as np

        image_array = np.array(image)
        image_bgr = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
        image_float = image_bgr.astype(np.float32)
        luminance = 0.0722 * image_float[:,:,0] + 0.7152 * image_float[:,:,1] + 0.2126 * image_float[:,:,2]
        
        h, w = luminance.shape
        center_region = luminance[h//4:3*h//4, w//4:3*w//4]
        weighted_luminance = np.mean(center_region)
        
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        p50 = np.percentile(gray, 50)
        
        combined_brightness = 0.7 * weighted_luminance + 0.3 * p50
        
        rgb_equivalent = [int(combined_brightness)] * 3
        
        return rgb_equivalent, combined_brightness
    
    def calculate_brightness(self, rgb_color):
        r, g, b = rgb_color
        brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255 * 100
        return brightness
    
    def smooth_brightness(self, new_brightness):
        if self.previous_brightness is None:
            self.previous_brightness = new_brightness
            return new_brightness
        
        smoothed = (self.smoothing_factor * new_brightness + 
                   (1 - self.smoothing_factor) * self.previous_brightness)
        
        if abs(smoothed - self.previous_brightness) >= self.min_change_threshold:
            self.previous_brightness = smoothed
            return int(smoothed)
        else:
            return int(self.previous_brightness)
    
    def _apply(self, percent):
        """Set the screen to ``percent``, through whatever this machine has."""
        if ztmetro_backend.available():
            if not ztmetro_backend.send(f"brightness {int(percent)}"):
                raise subprocess.CalledProcessError(1, "ztmetro.ctl")
            return
        subprocess.run(['brightnessctl', 'set', f'{percent}%'], check=True)

    def getCurrentBrightness(self):
        if ztmetro_backend.available():
            # The shell is not asked: the last value applied is on disk.
            if os.path.exists(bright_file):
                with open(bright_file, 'r') as f:
                    return int(f.read().strip())
            return 100
        try:
            result = subprocess.run(['brightnessctl', 'get'], capture_output=True, text=True, check=True)
            current = int(result.stdout.strip())

            result = subprocess.run(['brightnessctl', 'max'], capture_output=True, text=True, check=True)
            max_brightness = int(result.stdout.strip())
            
            return int((current / max_brightness) * 100)
        except (subprocess.CalledProcessError, FileNotFoundError):
            if os.path.exists(bright_file):
                with open(bright_file, 'r') as f:
                    return int(f.read().strip())
            return 50
    
    def setBrightness(self, target_brightness, step_size=2, delay=0.05):
        min_brightness = get_min_brightness()
        if target_brightness < min_brightness or target_brightness > 100:
            raise ValueError(
                f"Brightness must be between {min_brightness} and 100 "
                f"(never below {min_brightness} to avoid turning off the display)"
            )
        
        current = self.getCurrentBrightness()

        if abs(target_brightness - current) <= step_size:
            try:
                self._apply(target_brightness)
                with open(bright_file, 'w') as f:
                    f.write(str(target_brightness))
            except subprocess.CalledProcessError as e:
                print(f"Error setting brightness: {e}")
            return
        
        direction = 1 if target_brightness > current else -1
        
        while abs(current - target_brightness) > step_size:
            current += step_size * direction
            try:
                self._apply(current)
                time.sleep(delay)
            except subprocess.CalledProcessError as e:
                print(f"Error setting brightness: {e}")
                break
        
        try:
            self._apply(target_brightness)
            with open(bright_file, 'w') as f:
                f.write(str(target_brightness))
        except subprocess.CalledProcessError as e:
            print(f"Error setting brightness: {e}")
    
# if __name__ == "__main__":
#     image_path = "URL"
#     loader = ImageLoader(image_path)
    
#     try:
#         image = loader.load_image()
#         print(f"Image loaded with size: {loader.get_image_size()}")
        
#         prominent_colors = loader.check_prominent_colors(threshold=50)
#         print(f"Prominent colors (count > 50): {prominent_colors}")
#         most_prominent_color, average_color = ImageLoader.get_average_of_most_prominent_color(image_path)
#         print(f"Most prominent color: {most_prominent_color}, Average of most prominent color: {average_color}")
#     except Exception as e:
#         print(f"Error: {e}")