#!/usr/bin/env bash
set -euo pipefail

echo "VT Bioprinter Raspberry Pi setup"
if [[ $EUID -eq 0 ]]; then
  echo "Run this as the normal Pi user, not root."
  exit 1
fi

sudo apt update
sudo apt full-upgrade -y
sudo apt install -y git python3 python3-pip python3-venv screen minicom usbutils

sudo usermod -aG dialout "$USER"

echo
echo "Base packages installed."
echo "Reboot before serial testing so the dialout group takes effect:"
echo "  sudo reboot"
