#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Run this as the normal Pi user, not root."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
SRC_DIR="$HOME/librealsense"

echo "=== Intel RealSense D405 setup for VT Bioprinter ==="

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Bioprinter virtual environment not found. Run complete_setup.sh first."
  exit 2
fi

echo "[1/6] Installing build dependencies..."
sudo apt update
sudo apt install -y   build-essential cmake git pkg-config   libusb-1.0-0-dev libudev-dev libssl-dev   libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev   python3-dev python3-pybind11 pybind11-dev

echo "[2/6] Fetching librealsense..."
if [[ -d "$SRC_DIR/.git" ]]; then
  git -C "$SRC_DIR" fetch --all --tags
  git -C "$SRC_DIR" pull --ff-only
else
  git clone --depth 1 https://github.com/realsenseai/librealsense.git "$SRC_DIR"
fi

echo "[3/6] Installing RealSense USB permissions..."
sudo cp "$SRC_DIR/config/99-realsense-libusb.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "[4/6] Configuring ARM64 build..."
PYTHON="$VENV/bin/python"
PY_SITE="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"

cmake -S "$SRC_DIR" -B "$SRC_DIR/build-vt-bioprinter"   -DCMAKE_BUILD_TYPE=Release   -DBUILD_EXAMPLES=OFF   -DBUILD_GRAPHICAL_EXAMPLES=OFF   -DBUILD_TOOLS=ON   -DBUILD_PYTHON_BINDINGS=ON   -DBUILD_GLSL_EXTENSIONS=OFF   -DFORCE_RSUSB_BACKEND=ON   -DPYTHON_EXECUTABLE="$PYTHON"   -DPYTHON_INSTALL_DIR="$PY_SITE"

echo "[5/6] Building librealsense (this is the slow step on a Pi 4)..."
cmake --build "$SRC_DIR/build-vt-bioprinter" --parallel 2

echo "[6/6] Installing SDK and Python bindings..."
sudo cmake --install "$SRC_DIR/build-vt-bioprinter"
sudo ldconfig

# Some librealsense builds place the Python module in /usr/local/lib. If that
# happened instead of PYTHON_INSTALL_DIR, copy the module into this project's
# venv so the web service can import it without altering global Python.
if ! "$PYTHON" -c "import pyrealsense2" >/dev/null 2>&1; then
  FOUND="$(find /usr/local/lib "$SRC_DIR/build-vt-bioprinter" -type f \( -name 'pyrealsense2*.so' -o -name 'pyrsutils*.so' \) 2>/dev/null | head -n 1 || true)"
  if [[ -n "$FOUND" ]]; then
    FOUND_DIR="$(dirname "$FOUND")"
    cp -f "$FOUND_DIR"/pyrealsense2*.so "$PY_SITE"/ 2>/dev/null || true
    cp -f "$FOUND_DIR"/pyrsutils*.so "$PY_SITE"/ 2>/dev/null || true
  fi
fi

echo
if "$PYTHON" -c "import pyrealsense2 as rs; print('pyrealsense2 import OK')" ; then
  echo "RealSense Python bindings are ready."
else
  echo "Build completed, but pyrealsense2 is not importable from the project venv."
  echo "Send the final build output so the Python install path can be corrected."
  exit 3
fi

echo
echo "Connected USB devices:"
lsusb | grep -Ei 'realsense|8086:' || true

echo
echo "Restarting the VT Bioprinter web controller..."
sudo systemctl restart vt-bioprinter-web.service

echo
echo "RealSense setup complete."
echo "Open the Camera page in the bioprinter dashboard and press Refresh camera."
