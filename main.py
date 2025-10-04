# BrightnessAnalyzer V0.0.1 by Zerone B. Storm
from core.brightness_core import BrightnessAnalyzer
import cv2

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

if __name__ == "__main__":
    # Try to automatically find the camera
    try:
        camera_id = find_available_camera()
        if camera_id is not None:
            analyzer = BrightnessAnalyzer(camera_id)
        else:
            raise RuntimeError("No working camera found")
    except:
        print("Automation Failed: Failed to get Camera ID")
        # analyzer = BrightnessAnalyzer(0)  
    try:
        image = analyzer.capture_image()
        prominent_color, avg_color = analyzer.get_prominent_color(image)
        print(f"Prominent Color: {prominent_color}, Average Color Value: {avg_color}")
        raw_brightness = analyzer.calculate_brightness(prominent_color)
        smoothed_brightness = analyzer.smooth_brightness(raw_brightness)
        print(f"Raw Brightness: {raw_brightness:.1f}, Smoothed: {smoothed_brightness}")
        analyzer.setBrightness(1 if smoothed_brightness <= 5 else smoothed_brightness)  

    except Exception as e:
        print(f"Automation Failed: {e}")