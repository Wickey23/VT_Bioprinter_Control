#!/usr/bin/env bash
set -euo pipefail

HOTSPOT_NAME="VT-Bioprinter-Setup"
WAIT_SECONDS="${VT_BIOPRINTER_HOTSPOT_WAIT:-25}"

sleep "$WAIT_SECONDS"

ACTIVE_WIFI="$(nmcli -t -f NAME,TYPE connection show --active | awk -F: '$2=="802-11-wireless"{print $1}' | head -n 1 || true)"

if [[ -n "$ACTIVE_WIFI" ]]; then
  exit 0
fi

nmcli connection up "$HOTSPOT_NAME"
