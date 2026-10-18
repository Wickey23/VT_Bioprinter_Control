#!/usr/bin/env bash
set -euo pipefail

echo "=== VT Bioprinter Raspberry Pi final host setup ==="

if [[ $EUID -eq 0 ]]; then
  echo "Run this as the normal Pi user, not root."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "[1/6] Installing base packages..."
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv screen minicom usbutils

echo "[2/6] Adding $USER to serial-access group..."
sudo usermod -aG dialout "$USER"

echo "[3/6] Creating Python virtual environment..."
python3 -m venv "$SCRIPT_DIR/.venv"
"$SCRIPT_DIR/.venv/bin/python" -m pip install --upgrade pip
"$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

echo "[4/6] Making project scripts executable..."
chmod +x "$SCRIPT_DIR/install.sh" "$SCRIPT_DIR/detect_printer.sh" "$SCRIPT_DIR/complete_setup.sh"

echo "[5/6] Host health check..."
echo "Hostname: $(hostname)"
echo "Kernel: $(uname -r)"
echo "Architecture: $(uname -m)"
echo "Disk:"
df -h / | tail -n 1
echo "Network addresses:"
hostname -I || true
echo "SSH service:"
systemctl is-enabled ssh 2>/dev/null || true
systemctl is-active ssh 2>/dev/null || true
echo "Raspberry Pi Connect services:"
systemctl --user --no-pager --type=service 2>/dev/null | grep -i connect || true

echo "[6/6] Repository status..."
git -C "$REPO_DIR" status --short || true
git -C "$REPO_DIR" log -1 --oneline || true

echo
echo "==============================================="
echo "Pi host software is prepared."
echo "A reboot is recommended so dialout membership is active:"
echo "  sudo reboot"
echo
echo "After reboot, in the lab connect ONLY the Creality controller by USB and run:"
echo "  cd ~/VT_Bioprinter_Control/raspberry_pi"
echo "  ./detect_printer.sh"
echo "  ./.venv/bin/python printer_probe.py"
echo "==============================================="
