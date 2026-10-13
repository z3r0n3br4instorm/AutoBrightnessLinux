"""ztMETRO backend: brightness and colour temperature through the shell.

The Galaxy S9 under mainline has no backlight device for brightnessctl and no
gamma table for Redshift. ztMETRO does both itself, in its renderer, and takes
them as lines on its control pipe::

    brightness 10..100
    tone <Kelvin>        6500 is neutral

This module is used whenever that pipe exists; nothing else changes.
"""

import os
import stat


def ctl_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "ztmetro.ctl")


def available() -> bool:
    try:
        return stat.S_ISFIFO(os.stat(ctl_path()).st_mode)
    except OSError:
        return False


def send(command: str) -> bool:
    """Write one line to the shell. Never blocks: no shell, no write."""
    try:
        fd = os.open(ctl_path(), os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        os.write(fd, (command + "\n").encode())
        return True
    except OSError:
        return False
    finally:
        os.close(fd)
