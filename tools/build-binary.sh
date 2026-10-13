#!/bin/sh
# tools/build-binary.sh: compile AutoBrightness & OpenTone to a native program
# with Nuitka, so it starts without the interpreter compiling it first.
#
#   python -m venv --system-site-packages ~/.venvs/nuitka
#   ~/.venvs/nuitka/bin/pip install nuitka ordered-set     (and patchelf from the distro)
#   tools/build-binary.sh                     -> build/autobrightness.dist/autobrightness
#
# The camera and remote-sensor paths need OpenCV, numpy, Pillow and websockets;
# those are left out (NOFOLLOW) so the build stays small, and are picked up at
# run time only if a camera is ever used. On a machine with a webcam, empty
# NOFOLLOW to compile them in.
set -eu
cd "$(dirname "$0")/.."
PY=${PY:-$HOME/.venvs/nuitka/bin/python}
NOFOLLOW=${NOFOLLOW-cv2,numpy,PIL,websockets,zeroconf}
"$PY" -m nuitka --standalone --assume-yes-for-downloads --quiet \
	--output-dir=build --output-filename=autobrightness \
	${NOFOLLOW:+--nofollow-import-to=$NOFOLLOW} \
	--include-module=core.websocket_sensor --include-module=core.sensor_discovery \
	main.py
rm -rf build/autobrightness.dist
mv build/main.dist build/autobrightness.dist
ls -l build/autobrightness.dist/autobrightness
