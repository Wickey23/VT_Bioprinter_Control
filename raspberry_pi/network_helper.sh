#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"

case "$ACTION" in
  connect)
    SSID="${2:-}"
    if [[ -z "$SSID" ]]; then
      echo "SSID is required." >&2
      exit 2
    fi
    IFS= read -r PASSWORD || true

    if [[ -n "$PASSWORD" ]]; then
      nmcli device wifi connect "$SSID" password "$PASSWORD" ifname wlan0
    else
      nmcli device wifi connect "$SSID" ifname wlan0
    fi
    ;;

  forget)
    CONNECTION="${2:-}"
    if [[ -z "$CONNECTION" ]]; then
      echo "Connection name is required." >&2
      exit 2
    fi
    nmcli connection delete id "$CONNECTION"
    ;;

  *)
    echo "Usage: $0 {connect SSID|forget CONNECTION}" >&2
    exit 2
    ;;
esac
