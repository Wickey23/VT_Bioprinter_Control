#!/usr/bin/env bash
set -u

echo "=== USB devices ==="
lsusb || true

echo
echo "=== Candidate serial devices ==="
for pattern in /dev/ttyUSB* /dev/ttyACM*; do
  for dev in $pattern; do
    [[ -e "$dev" ]] && ls -l "$dev"
  done
done

echo
echo "=== Stable serial aliases ==="
if [[ -d /dev/serial/by-id ]]; then
  ls -l /dev/serial/by-id/
else
  echo "/dev/serial/by-id not present."
fi

echo
echo "Copy this output into HARDWARE_PROFILE.md."
