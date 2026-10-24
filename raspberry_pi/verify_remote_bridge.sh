#!/usr/bin/env bash
set -euo pipefail

REMOTE_URL_FILE="${VT_BIOPRINTER_REMOTE_URL_FILE:-/etc/vt-bioprinter/remote-url}"
TOKEN_FILE="${VT_BIOPRINTER_TOKEN_FILE:-$HOME/.config/vt-bioprinter/token}"

if [[ ! -f "$REMOTE_URL_FILE" ]]; then
  echo "Remote URL is not configured."
  echo "Run: sudo bash raspberry_pi/install_remote_access.sh https://<your-pi-hostname>"
  exit 2
fi

if [[ ! -f "$TOKEN_FILE" ]]; then
  echo "Controller token file not found at $TOKEN_FILE" >&2
  exit 3
fi

REMOTE_URL="$(tr -d '\r\n' < "$REMOTE_URL_FILE")"
TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"

if [[ -z "$REMOTE_URL" || -z "$TOKEN" ]]; then
  echo "Remote URL or controller token is empty." >&2
  exit 4
fi

echo "Checking cloudflared service..."
if systemctl is-active --quiet cloudflared.service; then
  echo "cloudflared: active"
else
  echo "cloudflared: NOT ACTIVE"
fi

echo "Checking remote controller endpoint..."
HTTP_CODE="$(curl -sS -o /tmp/vt-bioprinter-remote-status.json -w '%{http_code}' \
  -H "X-Bioprinter-Token: $TOKEN" \
  "$REMOTE_URL/api/status" || true)"

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "Remote controller check failed (HTTP $HTTP_CODE)." >&2
  cat /tmp/vt-bioprinter-remote-status.json 2>/dev/null || true
  exit 5
fi

echo "Remote controller: reachable"
echo "Device URL: $REMOTE_URL"
echo
echo "Vercel pairing value:"
echo "  BIOPRINTER_DEVICE_URL=$REMOTE_URL"
echo
echo "The controller token should be stored in Vercel as BIOPRINTER_DEVICE_TOKEN."
echo "Do not expose the token in browser JavaScript."
