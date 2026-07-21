# AutoBrightness

**Version 0.0.1**

An intelligent automatic screen brightness adjustment system that uses your camera to analyze ambient lighting conditions and automatically sets optimal screen brightness levels.

## Features

- **Automatic Camera Detection**: Detects and uses the first available camera
- **Ambient Light Analysis**: Captures and analyzes environmental lighting using computer vision
- **Smart Brightness Calculation**: Uses advanced color analysis to determine optimal brightness
- **Smooth Transitions**: Gradual brightness adjustments to prevent eye strain
- **Hypridle Integration**: Seamless integration with Hyprland's idle daemon
- **Keyboard Backlight Sync**: Automatically adjusts keyboard backlight based on screen brightness
- **Fallback Protection**: Robust error handling with sensible defaults

## Requirements

### System Dependencies
- Python 3.x
- OpenCV (cv2)
- PIL (Pillow)
- NumPy
- `brightnessctl` (for brightness control)
- `bc` (for mathematical calculations in shell scripts)

### Hardware Requirements
- A working camera (webcam, built-in camera, etc.)
- A system with adjustable screen brightness
- Optional: Adjustable keyboard backlight

## Installation

1. **Clone or download the project**:
   ```bash
   cd ~/Documents
   git clone https://github.com/z3r0n3br4instorm/AutoBrightnessLinux.git AutoBrightness
   # OR copy the project files to ~/Documents/AutoBrightness
   ```

2. **Install system dependencies**:
   ```bash
   # On Arch Linux / EndeavourOS
   sudo pacman -S python python-opencv python-pillow python-numpy brightnessctl bc

   # On Ubuntu/Debian
   sudo apt install python3 python3-opencv python3-pil python3-numpy brightnessctl bc

   # On Fedora
   sudo dnf install python3 python3-opencv python3-pillow python3-numpy brightnessctl bc
   ```

3. **Set up Python virtual environment** (recommended):
   ```bash
   python -m venv ~/.osenv
   source ~/.osenv/bin/activate
   pip install opencv-python pillow numpy
   ```

4. **Test the installation**:
   ```bash
   cd ~/Documents/AutoBrightness
   python main.py
   ```

## Usage

### Manual Execution
```bash
cd ~/Documents/AutoBrightness
source ~/.osenv/bin/activate  # if using virtual environment
python main.py
```

### Hypridle Integration

AutoBrightness is designed to work seamlessly with Hypridle (Hyprland's idle daemon) for automatic brightness adjustment based on user activity.

#### Setup with Hypridle

1. **Edit your hypridle configuration**:
   ```bash
   nano ~/.config/hypr/hypridle.conf
   ```

2. **Add the following configuration**:
   ```properties
   general {
   
   }
   
   listener {
       timeout = 3
       on-timeout = cd /home/zerone/Documents/AutoBrightness && source ~/.osenv/bin/activate && python main.py && BRIGHTNESS=$(cat ~/.local/share/brightness.ztrf) && KBD_LEVEL=$(printf "%.0f" $(echo "$BRIGHTNESS * 5 / 100" | bc -l)) && [ $KBD_LEVEL -lt 1 ] && KBD_LEVEL=1; brightnessctl -d asus::kbd_backlight s $KBD_LEVEL
       on-resume = cd /home/zerone/Documents/AutoBrightness && source ~/.osenv/bin/activate && python main.py && BRIGHTNESS=$(cat ~/.local/share/brightness.ztrf) && KBD_LEVEL=$(printf "%.0f" $(echo "$BRIGHTNESS * 5 / 100" | bc -l)) && [ $KBD_LEVEL -lt 1 ] && KBD_LEVEL=1; brightnessctl -d asus::kbd_backlight s $KBD_LEVEL
   }
   
   listener {
       timeout = 10
       on-timeout = brightnessctl -d asus::kbd_backlight s 1
   }
   ```

3. **Adjust paths in the configuration**:
   - Replace `/home/zerone/Documents/AutoBrightnessLinux` with your actual project path
   - Replace `~/.osenv/bin/activate` with your virtual environment path
   - Adjust `asus::kbd_backlight` to match your keyboard backlight device

4. **Start hypridle**:
   ```bash
   hypridle &
   ```

#### How Hypridle Integration Works

- **Timeout (3 seconds)**: When you stop using your computer for 3 seconds, AutoBrightness analyzes the ambient light and adjusts both screen and keyboard brightness
- **Resume**: When you return to your computer, brightness is immediately re-analyzed and adjusted
- **Keyboard Sync**: Keyboard backlight is set to 20% of screen brightness (minimum level 1)
- **Fallback (10 seconds)**: If idle for 10+ seconds, keyboard backlight dims to minimum

## Configuration

### Brightness Analysis Settings

The brightness analysis can be customized by modifying the `BrightnessAnalyzer` initialization in `main.py`:

```python
analyzer = BrightnessAnalyzer(
    camera_id,
    smoothing_factor=0.3,      # How much to smooth brightness changes (0.0-1.0)
    min_change_threshold=5     # Minimum brightness change to apply
)
```

### Camera Selection

The system automatically detects available cameras, but you can force a specific camera by modifying the exception handling:

```python
except:
    print("Automation Failed: Failed to get Camera ID")
    analyzer = BrightnessAnalyzer(0)  # Force camera 0
```

## File Structure

```
AutoBrightnessLinux/
├── README.md
├── main.py                 # Main application entry point
└── core/
    ├── brightness_core.py  # Core brightness analysis logic
    └── __pycache__/        # Python cache files
```

## How It Works

1. **Camera Detection**: Automatically scans for available cameras (indices 0-9)
2. **Image Capture**: Captures a frame from the selected camera
3. **Color Analysis**: Analyzes the captured image to determine ambient lighting:
   - Extracts center region for better accuracy
   - Calculates weighted luminance and percentile values
   - Combines multiple metrics for robust brightness detection
4. **Brightness Calculation**: Converts color data to brightness percentage
5. **Smoothing**: Applies smoothing to prevent rapid brightness changes
6. **System Adjustment**: Sets screen brightness using `brightnessctl`
7. **Persistence**: Saves brightness value to `~/.local/share/brightness.ztrf`

## Troubleshooting

### Common Issues

**Camera not found**:
- Ensure your camera is not being used by another application
- Check camera permissions
- Try running with `sudo` if permission issues persist

**Brightness control not working**:
- Install `brightnessctl`: `sudo pacman -S brightnessctl`
- Check if your user is in the `video` group: `sudo usermod -a -G video $USER`
- Logout and login again after adding to video group

**Python dependencies missing**:
```bash
pip install opencv-python pillow numpy
```

**Hypridle not working**:
- Ensure Hyprland is running
- Check hypridle is installed: `pacman -S hypridle`
- Verify the paths in your hypridle.conf are correct

### Debug Mode

For debugging, you can run the script manually to see detailed output:
```bash
cd ~/Documents/AutoBrightnessLinux
python main.py
```

## Contributing

Feel free to submit issues, feature requests, and pull requests to improve AutoBrightness.

## License

This project is created by Zerone B. Storm. Please respect the author's work and provide appropriate attribution when using or modifying this code.

---

**Note**: This system is designed for Linux environments with Hypridle and uses `brightnessctl` for brightness control. Modifications may be needed for other desktop environments or operating systems.