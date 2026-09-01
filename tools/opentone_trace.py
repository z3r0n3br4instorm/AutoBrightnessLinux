#!/usr/bin/env python
"""Live ambient colour-temperature trace for OpenTone, with continuous apply.

Streams what OpenTone measures once or twice a second until Ctrl+C, and applies
each new value via Redshift — effectively a live True Tone mode. Smoothing and
hysteresis are the configured ones, so the display only moves when the estimate
genuinely shifts, and Redshift calls are additionally rate-limited.

Pass --dry-run to observe without touching the display.

Usage:
    python tools/opentone_trace.py              # stream and apply until Ctrl+C
    python tools/opentone_trace.py --dry-run    # measure only, apply nothing
    python tools/opentone_trace.py -d 60        # stop after 60 seconds
    python tools/opentone_trace.py -i 0.3       # faster sampling
    python tools/opentone_trace.py -s 0.6       # snappier response

The last applied temperature persists after exit, as with a normal run. To go
back to neutral: python main.py --reset-tone
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Silence the INFO chatter so the trace stays readable.
logging.disable(logging.INFO)

import numpy as np  # noqa: E402

from core.opentone import OpenTone  # noqa: E402

# Bar spans warm (left) to cool (right).
BAR_MIN_K, BAR_MAX_K, BAR_WIDTH = 2000.0, 9000.0, 34


def find_camera():
    import cv2

    for index in range(10):
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            ok, frame = cap.read()
            cap.release()
            if ok and frame is not None:
                return index
    return None


def bar_for(cct: float) -> str:
    fraction = (cct - BAR_MIN_K) / (BAR_MAX_K - BAR_MIN_K)
    pos = int(max(0.0, min(1.0, fraction)) * (BAR_WIDTH - 1))
    return " " * pos + "#"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-d", "--duration", type=float, default=None,
                        help="seconds to sample (default: until Ctrl+C)")
    parser.add_argument("-i", "--interval", type=float, default=0.7,
                        help="seconds between samples (default: 0.7)")
    parser.add_argument("-c", "--camera", type=int, default=None,
                        help="camera index (default: auto-detect)")
    parser.add_argument("-n", "--dry-run", "--no-apply", action="store_true",
                        dest="dry_run",
                        help="measure only; do not call Redshift")
    parser.add_argument("-s", "--smoothing", type=float, default=None,
                        help="override OPENTONE_SMOOTHING_FACTOR (0-1); higher "
                             "reacts faster")
    parser.add_argument("--min-apply-interval", type=float, default=2.0,
                        help="minimum seconds between Redshift calls (default: 2.0)")
    args = parser.parse_args()

    if args.smoothing is not None and not 0.0 < args.smoothing <= 1.0:
        parser.error("--smoothing must be greater than 0 and at most 1")

    camera_id = args.camera if args.camera is not None else find_camera()
    if camera_id is None:
        print("No working camera found.", file=sys.stderr)
        return 1

    try:
        analyzer = OpenTone(camera_id, smoothing_factor=args.smoothing)
    except RuntimeError as e:
        print(f"{e}", file=sys.stderr)
        return 1

    print(f"camera {camera_id} | white balance pinned to {analyzer.wb_reference}K "
          f"(locked={analyzer.wb_locked}) | configured window "
          f"{analyzer.min_temp}-{analyzer.max_temp}K")
    print(f"smoothing {analyzer.smoothing_factor} | hysteresis "
          f"{analyzer.min_change_threshold}K | "
          f"{'DRY RUN — nothing applied' if args.dry_run else 'applying via Redshift'}")
    print("warming up…", end="", flush=True)
    analyzer.warmup()
    print(" ready. Ctrl+C to stop.\n")

    print(f"{'t':>6}  {'R':>6} {'G':>6} {'B':>6}  {'raw CCT':>9} {'target':>7} "
          f"{'applied':>8}  warm{'':<{BAR_WIDTH - 8}}cool")
    print("-" * (56 + BAR_WIDTH))

    readings = []
    applies = 0
    last_applied = None
    last_apply_time = 0.0
    start = time.time()
    try:
        while args.duration is None or (time.time() - start) < args.duration:
            elapsed = time.time() - start
            try:
                image = analyzer.capture_image()
            except RuntimeError as e:
                print(f"{elapsed:6.1f}  capture failed: {e}")
                time.sleep(args.interval)
                continue

            arr = np.asarray(image, dtype=np.float64)
            r, g, b = arr.reshape(-1, 3).mean(axis=0)
            raw = analyzer.estimate_color_temperature(image)
            target = analyzer.clamp_temperature(raw)
            readings.append(raw)

            note = "-"
            if not args.dry_run:
                smoothed = analyzer.smooth_temperature(target)
                # Two guards against thrashing: the value must actually have
                # moved (smooth_temperature enforces the hysteresis threshold),
                # and Redshift is a process spawn, so rate-limit it too.
                due = (time.time() - last_apply_time) >= args.min_apply_interval
                if smoothed != last_applied and due:
                    if analyzer.set_temperature(smoothed):
                        last_applied = smoothed
                        last_apply_time = time.time()
                        applies += 1
                        note = f"{smoothed}K"
                    else:
                        note = "FAILED"
                elif smoothed != last_applied:
                    note = "wait"      # change pending, throttled
                else:
                    note = "="         # already there

            print(f"{elapsed:6.1f}  {r:6.1f} {g:6.1f} {b:6.1f}  {raw:9.0f} {target:7d} "
                  f"{note:>8}  |{bar_for(raw):<{BAR_WIDTH}}|", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print()
    finally:
        analyzer.release()

    if readings:
        print("-" * (56 + BAR_WIDTH))
        print(f"{len(readings)} samples | min {min(readings):.0f}K | "
              f"max {max(readings):.0f}K | swing {max(readings) - min(readings):.0f}K")
        if not args.dry_run:
            print(f"{applies} Redshift applies | display left at "
                  f"{last_applied if last_applied is not None else 'unchanged'}"
                  f"{'K' if last_applied is not None else ''} "
                  f"(reset with: python main.py --reset-tone)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
