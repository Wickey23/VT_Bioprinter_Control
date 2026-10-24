#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"
HOTSPOT_NAME="VT-Bioprinter-Setup"

hotspot_up() {
  nmcli connection up "$HOTSPOT_NAME"
}

hotspot_down() {
  nmcli connection down "$HOTSPOT_NAME" >/dev/null 2>&1 || true
}

case "$ACTION" in
  connect)
    SSID="${2:-}"
    if [[ -z "$SSID" ]]; then
      echo "SSID is required." >&2
      exit 2
    fi
    if [[ "$SSID" == "$HOTSPOT_NAME" ]]; then
      echo "Use hotspot-on to activate the setup network." >&2
      exit 2
    fi

    IFS= read -r PASSWORD || true
    hotspot_down

    set +e
    if [[ -n "$PASSWORD" ]]; then
      nmcli device wifi connect "$SSID" password "$PASSWORD" ifname wlan0
      RC=$?
    else
      nmcli device wifi connect "$SSID" ifname wlan0
      RC=$?
    fi
    set -e

    if [[ $RC -ne 0 ]]; then
      echo "Wi-Fi connection failed; restoring setup hotspot." >&2
      hotspot_up >/dev/null 2>&1 || true
      exit $RC
    fi

    # Keep every successfully joined network as a reusable fallback profile.
    # NetworkManager will choose the highest-priority available profile.
    nmcli connection modify "$SSID" connection.autoconnect yes connection.autoconnect-retries 3 >/dev/null 2>&1 || true
    ;;

  forget)
    CONNECTION="${2:-}"
    if [[ -z "$CONNECTION" ]]; then
      echo "Connection name is required." >&2
      exit 2
    fi
    if [[ "$CONNECTION" == "$HOTSPOT_NAME" ]]; then
      echo "The setup hotspot profile cannot be forgotten from the dashboard." >&2
      exit 2
    fi
    nmcli connection delete id "$CONNECTION"
    ;;

  set-priority)
    CONNECTION="${2:-}"
    PRIORITY="${3:-}"
    if [[ -z "$CONNECTION" || -z "$PRIORITY" ]]; then
      echo "Connection name and priority are required." >&2
      exit 2
    fi
    if [[ "$CONNECTION" == "$HOTSPOT_NAME" ]]; then
      echo "Setup hotspot priority is managed separately." >&2
      exit 2
    fi
    if ! [[ "$PRIORITY" =~ ^-?[0-9]+$ ]] || (( PRIORITY < -999 || PRIORITY > 999 )); then
      echo "Priority must be an integer from -999 to 999." >&2
      exit 2
    fi
    nmcli connection modify "$CONNECTION" connection.autoconnect yes connection.autoconnect-priority "$PRIORITY" connection.autoconnect-retries 3
    ;;

  activate)
    CONNECTION="${2:-}"
    if [[ -z "$CONNECTION" ]]; then
      echo "Connection name is required." >&2
      exit 2
    fi
    if [[ "$CONNECTION" == "$HOTSPOT_NAME" ]]; then
      echo "Use hotspot-on to activate the setup network." >&2
      exit 2
    fi
    hotspot_down
    nmcli connection up "$CONNECTION"
    ;;

  hotspot-on)
    hotspot_up
    ;;

  hotspot-off)
    hotspot_down
    nmcli device wifi rescan ifname wlan0 >/dev/null 2>&1 || true
    ;;

  hotspot-status)
    ACTIVE="$(nmcli -t -f NAME connection show --active | head -n 1 || true)"
    if nmcli -t -f NAME connection show --active | grep -Fxq "$HOTSPOT_NAME"; then
      echo "active"
    else
      echo "inactive"
    fi
    ;;

  *)
    echo "Usage: $0 {connect SSID|forget CONNECTION|set-priority CONNECTION PRIORITY|activate CONNECTION|hotspot-on|hotspot-off|hotspot-status}" >&2
    exit 2
    ;;
esac
