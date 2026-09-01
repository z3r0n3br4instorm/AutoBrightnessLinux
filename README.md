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
- **Colorimetric camera capture** — OpenTone pins the webcam's white balance to a known reference and discards warm-up frames, so it measures the ambient illuminant instead of the camera's own auto-corrected view.
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
| `OPENTONE_TRANSITION_DURATION` | `1.2` | Seconds to ramp a colour temperature change over. `0` applies changes instantly. |
| `OPENTONE_TRANSITION_STEPS` | `25` | Intermediate steps per ramp. Each is one `redshift` call (~17 ms), so this trades smoothness against process churn. |


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

### Live trace & continuous mode

`tools/opentone_trace.py` streams what OpenTone measures, roughly once a second,
and applies each new value via Redshift — a live True Tone mode, and the quickest
way to confirm the estimate genuinely tracks the light around you.

```bash
# Stream and apply until Ctrl+C
python tools/opentone_trace.py

# Measure only — applies nothing, safe for diagnosing
python tools/opentone_trace.py --dry-run

python tools/opentone_trace.py -d 60      # stop after 60 s
python tools/opentone_trace.py -i 0.3     # sample ~3x/second
python tools/opentone_trace.py -s 0.6     # snappier response (overrides smoothing)
```

Output columns are elapsed time, mean R/G/B, the raw CCT, the value after
clamping to the configured window, and what was applied (`=` already there,
`wait` throttled, `-` dry run):

```
     t       R      G      B    raw CCT  target  applied  warm            cool
   0.0   129.7  117.4   70.2       4072    4072    4072K  |    #              |
   0.8   129.8  117.4   70.2       4075    4075        =  |    #              |
```

Show it a warm (yellow) surface and `B` should collapse while the raw CCT drops
towards 2000–3000 K; a blue surface pushes the other way. If both leave the
reading near its baseline, the white-balance lock is not holding — see
[OpenTone runs but the display colour never changes](#opentone-runs-but-the-display-colour-never-changes).

Applies are guarded twice: by the configured hysteresis
(`OPENTONE_MIN_CHANGE_THRESHOLD`) and by `--min-apply-interval` (default 2 s),
since each apply spawns a Redshift process. The last applied temperature persists
after exit — `python main.py --reset-tone` returns to neutral.

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
├── tools/
│   └── opentone_trace.py     # Live CCT trace + continuous apply (see below)
└── core/
    ├── brightness_core.py    # Camera capture, brightness analysis, brightnessctl
    ├── config.py             # .env loader (brightness & OpenTone settings)
    ├── log_setup.py          # stderr + systemd journal logging
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
      │                 │                          │ Sequential capture│
┌─────▼─────┐     ┌─────▼─────┐                    │  (WB-pinned CCT)  │
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
2. **Pinned White Balance & Warm-up (required for correctness):** OpenTone opens the camera itself rather than reusing the brightness frame, disables auto white balance **and** pins `WB_TEMPERATURE` to a 6500 K reference, then discards 12 frames so auto-exposure settles. The camera has to behave like a colorimeter: auto white balance cancels out the very colour cast being measured, and merely disabling it leaves the driver's stale WB value in place, which biases every estimate. The measurement is the **median of 5 frames** to reject mains flicker and noise.
3. **ROI & Illuminant Extraction:** Samples the central 60% region of the frame, rejects clipped highlights (>245) and dark noise (<15), and computes the illuminant vector using a blend of **Shades of Gray** ($p=6$ Minkowski norm) and top 10% specular/white patch sampling.
4. **Linearization & CIE XYZ Transformation:** Converts sRGB channels to linear RGB and transforms to **CIE 1931 XYZ** space using the standard sRGB D65 matrix.
5. **Correlated Color Temperature (CCT):** Derives chromaticity coordinates $(x, y)$ and calculates CCT in Kelvin via **McCamy's formula**:
   $$n = \frac{x - 0.3320}{0.1858 - y}$$
   $$CCT = 449.0 n^3 + 3525.0 n^2 + 6823.3 n + 5520.33$$
6. **Smoothing & Redshift Integration:** Clamps CCT to `[OPENTONE_MIN_TEMP, OPENTONE_MAX_TEMP]` (default 3000K–6500K) — logging whenever the raw estimate falls outside that window, since a reading pinned to an edge usually means the measurement is wrong rather than the room being that warm or cool — then smooths with an exponential moving average and hysteresis thresholding, and applies it systemwide via `redshift -P -O <CCT>`. State is persisted to `~/.local/share/opentone.ztrf`.

   Because each run is a separate process, the EMA is effectively a *cross-run* filter seeded from that state file. On a first run (or after `--reset-tone`) there is no prior state, so the measurement is adopted directly instead of easing from an assumed neutral.

7. **Ramped transition:** the change is never applied as a jump. It is spread over `OPENTONE_TRANSITION_DURATION` (default 1.2 s) in `OPENTONE_TRANSITION_STEPS` steps (default 25) using smoothstep easing, so it starts and ends gently and reads as a fade. The ramp is *time-based*, so a 3500 K change takes no longer than a 200 K one and the number of `redshift` invocations is bounded either way. Changes below 40 K are applied in a single step, since ramping something barely visible only burns invocations.

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

### OpenTone runs but the display colour never changes

Check the logged CCT. If every run reports a raw CCT at or beyond
`OPENTONE_MAX_TEMP` (e.g. always exactly 6500 K), the measurement is wrong, not
the room — the display is being set to neutral, which looks like "nothing
happened".

Confirm Redshift itself works, independently of OpenTone:

```bash
redshift -P -O 3000                      # should visibly warm the screen
xrandr --verbose | grep -i -A1 'connected primary' | grep -i gamma
redshift -x                              # reset
```

A working gamma ramp reports something like `Gamma: 1.0:1.5:2.2`; `1.0:1.0:1.0`
means no gamma ramp is applied. Note that Redshift needs X11 (or DRM) — under a Wayland
compositor use `gammastep`, `wlsunset` or `hyprsunset` instead.

If Redshift is fine, the cause is camera white balance. OpenTone pins
`white_balance_temperature` to 6500 K, but the control has a limited range that
varies by camera:

```bash
v4l2-ctl -d /dev/video0 --list-ctrls | grep -i white_balance
```

If 6500 K is outside `min`/`max`, OpenTone logs `Camera white balance not
pinned` and its estimates will be biased; pass a `wb_reference` inside that
range when constructing `OpenTone`.

### `Redshift failed to set color temperature ... exit status 1`

Redshift needs a display server connection. The usual cause is being launched
from a **systemd user unit that started before the graphical session**: the user
manager gains `DISPLAY`/`XAUTHORITY` when the session imports them, but an
already-running unit's environment is never updated retroactively, and its child
processes inherit that gap. Runs from a terminal work; runs from the unit fail.

The log now names the real reason, e.g.:

```
redshift -P -O 4269 failed (exit 1): `RANDR Query Version' returned error -1 |
  Initialization of randr failed. | X request failed: XOpenDisplay
```

OpenTone recovers automatically — it queries `systemctl --user show-environment`
for `DISPLAY`/`XAUTHORITY` and falls back to probing `/tmp/.X11-unix` and the
runtime directory, logging what it used:

```
DISPLAY was unset; using :0 from systemd user environment
XAUTHORITY was unset; using /run/user/1000/lyxauth from systemd user environment
```

If it still cannot connect, push the values into the unit yourself:

```bash
systemctl --user import-environment DISPLAY XAUTHORITY
systemctl --user restart <your-unit>.service
```

Under Wayland, Redshift cannot help at all — use `gammastep`, `wlsunset` or
`hyprsunset`.

### OpenTone changes colour temperature only slowly

That is the cross-run EMA working as configured. Each run moves
`OPENTONE_SMOOTHING_FACTOR` (default `0.3`) of the way towards the measurement,
and changes smaller than `OPENTONE_MIN_CHANGE_THRESHOLD` (default `50` K) are
suppressed entirely. To jump straight to the current measurement:

```bash
python main.py --reset-tone     # clears state, next run adopts its measurement
```

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
