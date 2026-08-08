# AutoBrightness

**Version 0.0.2**

An intelligent automatic screen brightness adjustment system. It can use your
laptop camera (ambient-light analysis via OpenCV) **or** a remote light sensor
on your Android phone — or both in a hybrid fallback chain — to automatically
set the optimal screen brightness.

## Features

- **Dual sensor sources** — local camera, remote Android sensor, or hybrid
  (camera first, remote fallback). Switchable via `.env`.
- **mDNS auto-discovery** — finds the Android SensorServer on your local
  network without manual IP configuration.
- **Ambient light analysis** — captures and analyzes environmental lighting
  using computer vision.
- **Logarithmic lux→brightness mapping** — matches human perception.
- **Smooth transitions** — gradual brightness ramping to prevent eye strain.
- **Hypridle integration** — hooks into Hyprland's idle daemon.
- **Keyboard backlight sync** — optionally adjusts keyboard backlight based on
  screen brightness.
- **Configurable minimum brightness** — never turns your display off (default
  floor: 5 %).

---

## Requirements

### System dependencies

| Package | Purpose |
|---|---|
| `python` 3.10+ | Runtime |
| `brightnessctl` | Screen brightness control |
| `bc` | Math in shell scripts |
| `avahi-utils` | mDNS discovery of the Android sensor |

Install on **Arch / EndeavourOS**:
```bash
sudo pacman -S python python-opencv python-pillow python-numpy brightnessctl bc avahi
```

Install on **Ubuntu / Debian**:
```bash
sudo apt install python3 python3-opencv python3-pil python3-numpy brightnessctl bc avahi-utils
```

Install on **Fedora**:
```bash
sudo dnf install python3 python3-opencv python3-pillow python3-numpy brightnessctl bc avahi-tools
```

### Python packages

```bash
pip install -r requirements.txt
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
| `SENSOR_MODE` | `hybrid` | `camera` — local camera only; `remote` — Android sensor only; `hybrid` — camera first, remote fallback. |

---

## Usage

### Manual execution

```bash
cd ~/Documents/AutoBrightnessLinux
source ~/.osenv/bin/activate   # if using a venv
python main.py
```

### Hypridle integration

AutoBrightness works with [Hypridle](https://github.com/hyprwm/hypridle),
Hyprland's idle daemon, for automatic brightness adjustment based on user
activity.

#### Setup

Edit `~/.config/hypr/hypridle.conf` and add:

```properties
general {

}

listener {
    timeout = 3
    on-timeout = cd /home/zerone/Documents/AutoBrightnessLinux && source ~/.osenv/bin/activate && python main.py && BRIGHTNESS=$(cat ~/.local/share/brightness.ztrf) && KBD_LEVEL=$(printf "%.0f" $(echo "$BRIGHTNESS * 5 / 100" | bc -l)) && [ $KBD_LEVEL -lt 1 ] && KBD_LEVEL=1; brightnessctl -d asus::kbd_backlight s $KBD_LEVEL
    on-resume = cd /home/zerone/Documents/AutoBrightnessLinux && source ~/.osenv/bin/activate && python main.py && BRIGHTNESS=$(cat ~/.local/share/brightness.ztrf) && KBD_LEVEL=$(printf "%.0f" $(echo "$BRIGHTNESS * 5 / 100" | bc -l)) && [ $KBD_LEVEL -lt 1 ] && KBD_LEVEL=1; brightnessctl -d asus::kbd_backlight s $KBD_LEVEL
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
  brightness.
- **Resume:** Brightness is re-analyzed as soon as you return.
- **Keyboard sync:** Keyboard backlight tracks 20 % of screen brightness (min
  level 1).
- **Fallback (10 s):** After 10 seconds of idle, keyboard backlight dims to
  minimum.

---

## File structure

```
AutoBrightnessLinux/
├── README.md
├── main.py                   # Entry point & sensor orchestration
├── requirements.txt
├── .env                      # Your local config (gitignored)
├── .env.example              # Config template
└── core/
    ├── brightness_core.py    # Camera capture, brightness analysis, brightnessctl
    ├── config.py             # .env loader (min brightness, sensor mode)
    ├── sensor_discovery.py   # mDNS discovery via avahi-browse
    └── websocket_sensor.py   # WebSocket client for SensorServer
```

---

## How it works

### Camera path

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
4. Brightness is ramped smoothly via `brightnessctl`.

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
