# AutoBrightness & OpenTone

**Version 0.0.3**

An intelligent automatic screen brightness and ambient color temperature adjustment system for Linux.
It dynamically adjusts screen brightness using your laptop's **built-in ambient light sensor**, **laptop camera** (ambient-light analysis via OpenCV), **or** a remote light sensor on your Android phone.

With **OpenTone** (True Tone for Linux), it analyzes the ambient color temperature of your environment using the webcam and synchronizes your display's white point systemwide using **Redshift**.

## Features

- **OpenTone (True Tone for Linux, enabled by default)** — captures ambient lighting through the webcam, calculates Correlated Color Temperature (CCT in Kelvin) using CIE 1931 colorimetry and McCamy's approximation, and dynamically adapts your display systemwide using `redshift`.
- **Asynchronous concurrent execution** — when a lux sensor (built-in ALS or remote WebSocket sensor) is available, OpenTone runs concurrently in a background thread while screen brightness is stepping, cutting overall adjustment latency in half.
- **Three sensor sources for brightness** — built-in ambient light sensor (ALS), local camera, remote Android sensor, or hybrid (ALS → camera → remote). Switchable via `.env`.
- **Built-in ALS support** — reads true lux from the kernel IIO subsystem (`/sys/bus/iio/devices`). Works on MacBooks via `acpi_als` and on most laptops with an `hid-sensor-als`. Preferred over the camera when present: it is more accurate, instant, and never powers on the webcam.
- **mDNS auto-discovery** — finds the Android SensorServer on your local network without manual IP configuration.
- **Ambient light analysis** — captures and analyzes environmental lighting using computer vision.
- **Logarithmic lux→brightness mapping** — matches human perception.
- **Smooth transitions & hysteresis** — gradual ramping and smoothing to prevent jitter and eye strain.
- **Shared camera frame optimization** — when both camera brightness and OpenTone are active, captures a single frame to save battery and webcam overhead.
- **Hypridle integration** — hooks into Hyprland's idle daemon.
- **Keyboard backlight sync** — optionally adjusts keyboard backlight based on screen brightness.
- **Configurable minimum brightness & temperature limits** — safe floor limits (never turns off display or applies extreme tints).


---

## Requirements

### System dependencies

| Package | Purpose |
|---|---|
| `python` 3.10+ | Runtime |
| `brightnessctl` | Screen brightness control |
| `redshift` | Display color temperature control (for OpenTone) |
| `bc` | Math in shell scripts |
| `avahi-utils` | mDNS discovery of the Android sensor |

Install on **Arch / EndeavourOS**:
```bash
sudo pacman -S python python-opencv python-pillow python-numpy brightnessctl redshift bc avahi
```

Install on **Ubuntu / Debian**:
```bash
sudo apt install python3 python3-opencv python3-pil python3-numpy brightnessctl redshift bc avahi-utils
```

Install on **Fedora**:
```bash
sudo dnf install python3 python3-opencv python3-pillow python3-numpy brightnessctl redshift bc avahi-tools
```

### Python packages

```bash
pip install -r requirements.txt
```

Only `python-dotenv` is needed for `SENSOR_MODE=local` — OpenCV, Pillow and
numpy are imported lazily by the camera path, and `websockets`/`zeroconf` only
by the remote path, so an ALS-only setup does not need them installed.

### Built-in ambient light sensor (local / hybrid mode)

Check whether your laptop exposes one:

```bash
grep -l . /sys/bus/iio/devices/iio:device*/in_illuminance_* 2>/dev/null
```

If nothing is listed, try loading the driver (MacBooks use ACPI):

```bash
sudo modprobe acpi_als
```

To make it persist across reboots:

```bash
echo acpi_als | sudo tee /etc/modules-load.d/acpi_als.conf
```

Verify the reading is live rather than a stale constant — cover the sensor
(top bezel, beside the webcam on MacBooks) and watch the number fall:

```bash
watch -n1 cat /sys/bus/iio/devices/iio:device0/in_illuminance_input
```

### Android phone (remote / hybrid mode)

- The free **[SensorServer]** app installed on your Android device.
- Both the phone and laptop must be on the **same local network** (Wi-Fi).

---

## Quick start

```bash
cd ~/Documents/AutoBrightnessLinux
cp .env.example .env          # edit if you want to change defaults
pip install -r requirements.txt
python main.py
```

---

## Android SensorServer setup (remote / hybrid mode)

If you only use the camera (`SENSOR_MODE=camera`) you can skip this section.
For `remote` or `hybrid` mode, follow these steps on your Android phone.

### 1. Install SensorServer

Download and install **SensorServer** from the Google Play Store or F-Droid:

> **SensorServer** by *umer0586* — streams Android sensor data over WebSocket.

- [Google Play](https://play.google.com/store/apps/details?id=com.umer.sensorserver)
- [F-Droid](https://f-droid.org/packages/com.umer.sensorserver/)

### 2. Configure the app

1. Open **SensorServer** on your Android phone.
2. Go to the app **Settings** (gear icon).
3. Set the **WebSocket port** (default is `8081` — keep it or pick another).
4. Make sure **mDNS / NSD** (Network Service Discovery) is **enabled**. This
   advertises the service as `_websocket._tcp` so the laptop can find the
   phone automatically.

### 3. Start the server

1. On the main screen, tap the **play / start button**.
2. Grant any permissions the app asks for (sensor access).
3. You should see a "Server running" indicator with the local IP and port.
4. **Keep the app running in the foreground**, or:

   > **For background operation:** On most Android devices you can switch to
   > another app or lock the screen and SensorServer will keep streaming. If
   > your device aggressively kills background services, go to **Android
   > Settings → Apps → SensorServer → Battery → Unrestricted** and enable
   > **Background data**. Some manufacturers (Xiaomi, Huawei, OnePlus,
   > Samsung) require additional steps — search for "disable battery
   > optimization" for your specific device.

### 4. Verify the connection

Once SensorServer is running on your phone:

```bash
# Check that avahi sees the phone on the network:
avahi-browse -r -t _websocket._tcp
```

You should see output similar to:
```
= wlp3s0 IPv4 SensorServer   _websocket._tcp   local
   hostname = [Android_XXXXXX.local]
   address = [192.168.8.104]
   port = [8081]
   txt = []
```

If you see that, the laptop can discover the phone. Run `python main.py` (with
`SENSOR_MODE=remote` or `SENSOR_MODE=hybrid`) and it will connect automatically.

### 5. How the connection works

```
┌──────────────────┐       mDNS (avahi)       ┌──────────────────────┐
│   Android phone   │ ◄──────────────────────► │       Laptop         │
│                   │                          │                      │
│  SensorServer     │    WebSocket (ws://)     │  sensor_discovery.py │
│  port 8081        │ ◄────────────────────── │  websocket_sensor.py │
│                   │   /sensor/connect?       │                      │
│  Light sensor ────┤   type=android.sensor.   │  lux → brightness %  │
│                     light                    │  brightnessctl       │
└──────────────────┘                          └──────────────────────┘
```

1. SensorServer advertises `_websocket._tcp` via Android NSD (mDNS).
2. The laptop's `sensor_discovery.py` polls `avahi-browse` every 30 s to keep
   the phone's IP and port current.
3. `websocket_sensor.py` connects to `ws://<phone-ip>:8081/sensor/connect?type=android.sensor.light`
   and receives a continuous stream of lux readings.
4. `main.py` maps each lux value to a brightness percentage and ramps the
   screen via `brightnessctl`.

---

## Configuration (`.env`)

Copy the example file and edit it to your liking:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `MIN_BRIGHTNESS` | `5` | Lowest brightness % (never 0 — that would turn off the display). |
| `SENSOR_MODE` | `hybrid` | `local` — built-in ALS only; `camera` — local camera only; `remote` — Android sensor only; `hybrid` — built-in ALS first, then camera, then remote. |
| `OPENTONE_ENABLED` | `true` | Enabled by default. Runs OpenTone ambient color temperature adjustment on each run. |
| `OPENTONE_MIN_TEMP` | `3000` | Minimum color temperature in Kelvin (warm floor, e.g. 2700–3500K). |
| `OPENTONE_MAX_TEMP` | `6500` | Maximum color temperature in Kelvin (cool ceiling, e.g. 6500–7500K). |
| `OPENTONE_SMOOTHING_FACTOR` | `0.3` | Exponential moving average smoothing factor (0.0 to 1.0). |
| `OPENTONE_MIN_CHANGE_THRESHOLD` | `50` | Minimum temperature difference in Kelvin needed before Redshift updates the display. |


---

## Usage

### Manual execution

```bash
cd ~/Documents/AutoBrightnessLinux
source ~/.osenv/bin/activate   # if using a venv

# Standard execution (uses .env settings)
python main.py

# Run with OpenTone enabled
python main.py --tone

# Run ONLY OpenTone (skip brightness)
python main.py --tone-only

# Run ONLY Brightness (skip OpenTone even if enabled in .env)
python main.py --brightness-only

# Check current brightness & color temperature
python main.py --status

# Manually set a color temperature (e.g. 4500K)
python main.py --set-tone 4500

# Reset color temperature to default neutral (redshift -x)
python main.py --reset-tone
```

### Hypridle integration

AutoBrightness and OpenTone work with [Hypridle](https://github.com/hyprwm/hypridle),
Hyprland's idle daemon, for automatic brightness and color temperature adjustment based on user
activity.

#### Setup

Edit `~/.config/hypr/hypridle.conf` and add:

```properties
general {

}

listener {
    timeout = 3
    on-timeout = cd /home/zerone/Documents/AutoBrightnessLinux && source ~/.osenv/bin/activate && python main.py --tone && BRIGHTNESS=$(cat ~/.local/share/brightness.ztrf) && KBD_LEVEL=$(printf "%.0f" $(echo "$BRIGHTNESS * 5 / 100" | bc -l)) && [ $KBD_LEVEL -lt 1 ] && KBD_LEVEL=1; brightnessctl -d asus::kbd_backlight s $KBD_LEVEL
    on-resume = cd /home/zerone/Documents/AutoBrightnessLinux && source ~/.osenv/bin/activate && python main.py --tone && BRIGHTNESS=$(cat ~/.local/share/brightness.ztrf) && KBD_LEVEL=$(printf "%.0f" $(echo "$BRIGHTNESS * 5 / 100" | bc -l)) && [ $KBD_LEVEL -lt 1 ] && KBD_LEVEL=1; brightnessctl -d asus::kbd_backlight s $KBD_LEVEL
}

listener {
    timeout = 10
    on-timeout = brightnessctl -d asus::kbd_backlight s 1
}
```

> **Adjust paths:** Replace `/home/zerone/Documents/AutoBrightnessLinux` with
> your actual project path, `~/.osenv/bin/activate` with your venv path, and
> `asus::kbd_backlight` with your keyboard backlight device (`brightnessctl -l`
> to list devices).

#### How it works

- **Timeout (3 s):** When you stop using the computer for 3 seconds,
  AutoBrightness analyzes ambient light and adjusts screen + keyboard
  brightness, while OpenTone adapts the screen color temperature to ambient lighting.
- **Resume:** Brightness and tone are re-analyzed as soon as you return.
- **Keyboard sync:** Keyboard backlight tracks 20 % of screen brightness (min
  level 1).
- **Fallback (10 s):** After 10 seconds of idle, keyboard backlight dims to
  minimum.

---

## File structure

```
AutoBrightnessLinux/
├── README.md
├── main.py                   # Entry point & sensor / OpenTone orchestration
├── requirements.txt
├── .env                      # Your local config (gitignored)
├── .env.example              # Config template
└── core/
    ├── brightness_core.py    # Camera capture, brightness analysis, brightnessctl
    ├── config.py             # .env loader (brightness & OpenTone settings)
    ├── local_als.py          # Built-in ambient light sensor via IIO/sysfs
    ├── opentone.py           # OpenTone ambient CCT estimation & Redshift control
    ├── sensor_discovery.py   # mDNS discovery via avahi-browse
    └── websocket_sensor.py   # WebSocket client for SensorServer
```

---

## How it works

### OpenTone path (Ambient Color Temperature via Redshift)

```
                       ┌───────────────────────────────┐
                       │       python main.py          │
                       └──────────────┬────────────────┘
                                      │
               ┌──────────────────────┴──────────────────────┐
               │                                             │
      [Lux Sensor Active]                           [Camera Mode Active]
 (Built-in ALS / Remote WebSocket)                           │
               │                                             │
      ┌────────┴────────┐                          ┌─────────┴─────────┐
      │                 │                          │   Camera Capture  │
┌─────▼─────┐     ┌─────▼─────┐                    │   (single frame)  │
│  Thread 1 │     │  Thread 2 │                    └────┬───────────┬──┘
│Brightness │     │ OpenTone  │                         │           │
│  Ramping  │     │  (Camera  │                    ┌────▼────┐ ┌────▼────┐
│(sysfs PWM)│     │+ Redshift)│                    │Bright-  │ │OpenTone │
└─────┬─────┘     └─────┬─────┘                    │nessctl  │ │Redshift │
      │                 │                          └────┬────┘ └────┬────┘
      └────────┬────────┘                               └─────┬─────┘
               │                                              │
         [Both Done]                                    [Both Done]
```

1. **Concurrent Async Execution (Lux Sensors):** When a built-in ALS or remote sensor provides lux readings, OpenTone is spawned immediately in a background thread while screen brightness is smoothly adjusted on the main thread. Both adjustments execute in parallel, reducing latency by ~50%.
2. **Shared Frame Optimization (Camera Mode):** When the camera is used for brightness estimation, a single frame is captured and passed to both the brightness analyzer and OpenTone analyzer, avoiding dual camera initializations.
3. **ROI & Illuminant Extraction:** Samples the central 60% region of the frame, rejects clipped highlights (>245) and dark noise (<15), and computes the illuminant vector using a blend of **Shades of Gray** ($p=6$ Minkowski norm) and top 10% specular/white patch sampling.
4. **Linearization & CIE XYZ Transformation:** Converts sRGB channels to linear RGB and transforms to **CIE 1931 XYZ** space using the standard sRGB D65 matrix.
5. **Correlated Color Temperature (CCT):** Derives chromaticity coordinates $(x, y)$ and calculates CCT in Kelvin via **McCamy's formula**:
   $$n = \frac{x - 0.3320}{0.1858 - y}$$
   $$CCT = 449.0 n^3 + 3525.0 n^2 + 6823.3 n + 5520.33$$
6. **Smoothing & Redshift Integration:** Clamps CCT to `[OPENTONE_MIN_TEMP, OPENTONE_MAX_TEMP]` (default 3000K–6500K), smooths with exponential moving average and hysteresis thresholding, and applies it systemwide via `redshift -P -O <CCT>`. State is persisted to `~/.local/share/opentone.ztrf`.

### Built-in ALS path (preferred for brightness)

1. `local_als.py` scans `/sys/bus/iio/devices/iio:device*` for a device
   exposing an `in_illuminance_*` channel, preferring known ALS drivers
   (`acpi-als`, `hid-sensor-als`).
2. Reads `in_illuminance_input` (already scaled to lux by the driver); if only
   `in_illuminance_raw` exists, it applies the device's `scale` and `offset`.
3. Averages a few samples to smooth out flicker under mains lighting.
4. The lux value goes through the same logarithmic curve as the remote path.
5. Brightness is ramped smoothly via `brightnessctl` concurrently with OpenTone.

This path needs no camera for brightness calculation. In `hybrid` mode, ALS short-circuits the brightness chain while the camera is sampled in parallel for OpenTone.

### Camera path (brightness)

1. Scans for an available camera (indices 0–9).
2. Captures a frame and analyzes the center region for weighted luminance.
3. Combines luminance with 50th-percentile gray for robust brightness.
4. Converts to a 0–100 % brightness value, smooths with hysteresis.
5. Ramps the screen brightness in small steps via `brightnessctl`.

### Remote path (Android sensor)

1. `sensor_discovery.py` polls `avahi-browse` for `_websocket._tcp` services.
2. `websocket_sensor.py` connects to the discovered `ws://` endpoint and
   subscribes to `android.sensor.light`.
3. Each incoming lux value is mapped to a brightness percentage via a
   logarithmic curve.
4. Brightness is ramped smoothly via `brightnessctl` while OpenTone runs concurrently.

### Brightness mapping (lux → %)

The mapping uses a logarithmic curve to match human perception:

| Lux | Brightness | Environment |
|---|---|---|
| ~0 | min (5 %) | Near-dark |
| ~100 | ~30 % | Dim room |
| ~500 | ~60 % | Well-lit room |
| ~2 000 | ~90 % | Bright indoor |
| ~10 000+ | 100 % | Direct sunlight |

---

## Troubleshooting

### Built-in ALS not detected

- Confirm the channel exists:
  `ls /sys/bus/iio/devices/iio:device*/in_illuminance_*`
- Load the driver: `sudo modprobe acpi_als` (MacBooks) or
  `sudo modprobe hid-sensor-als`.
- If the module loads but no `iio:device*` appears, your firmware likely does
  not expose an `ACPI0008` device — check with
  `ls /sys/bus/acpi/devices/ | grep ACPI0008`.

### ALS reading is stuck at one value

`acpi_als` reports coarse, integer lux values that update slowly, so a flat
reading over a few seconds is normal. To confirm it is genuinely live, cover
the sensor and watch the value drop:

```bash
watch -n1 cat /sys/bus/iio/devices/iio:device0/in_illuminance_input
```

If it never changes while covered, the sensor is stale — set
`SENSOR_MODE=camera` or `remote` instead.

### Camera not found

- Ensure no other app is using the camera.
- Check permissions (`ls -l /dev/video*`).
- Try `sudo` if you hit permission issues.

### Brightness control not working

- Install `brightnessctl`: `sudo pacman -S brightnessctl`
- Add your user to the `video` group: `sudo usermod -a -G video $USER`
- Log out and back in after the group change.

### Android phone not discovered

- Both devices must be on the **same Wi-Fi network**.
- Make sure `avahi-utils` is installed and the `avahi-daemon` service is
  running: `systemctl status avahi-daemon`.
- On the phone: verify SensorServer is running and **NSD/mDNS is enabled** in
  its settings.
- Test manually: `avahi-browse -r -t _websocket._tcp`.
- Some routers block mDNS between Wi-Fi clients (AP isolation) — check your
  router settings.

### SensorServer keeps getting killed in the background

- **Android Settings → Apps → SensorServer → Battery → Unrestricted**.
- Enable **Background data** for the app.
- On some devices: lock the app in the recents / overview screen.
- Search for "disable battery optimization" guides for your specific phone
  model.

### Python dependencies missing

```bash
pip install -r requirements.txt
```

### Debug mode

Run the script manually to see detailed logs:

```bash
python main.py
```

---

## Contributing

Issues, feature requests, and pull requests are welcome.

## License

Created by Zerone B. Storm. Please provide appropriate attribution when using
or modifying this code.

[SensorServer]: https://github.com/umer0586/SensorServer
