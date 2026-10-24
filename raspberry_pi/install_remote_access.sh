#!/usr/bin/env bash
set -euo pipefail

# One-time Cloudflare Tunnel service setup for the VT Bioprinter controller.
#
# Prerequisites:
#   1. cloudflared is installed on the Raspberry Pi.
#   2. A remotely-managed Cloudflare Tunnel exists.
#   3. The tunnel has a Published Application route whose service is
#      http://localhost:8080.
#
# Usage:
#   sudo bash install_remote_access.sh https://bioprinter.example.com
#
# The script securely prompts for the tunnel token instead of placing it in
# shell history. The token is passed only to cloudflared's service installer.

PUBLIC_URL="${1:-}"
CONFIG_DIR="/etc/vt-bioprinter"
URL_FILE="$CONFIG_DIR/remote-url"

if [[ -z "$PUBLIC_URL" ]]; then
  echo "Usage: sudo bash install_remote_access.sh https://bioprinter.example.com" >&2
  exit 2
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed." >&2
  echo "Install cloudflared using Cloudflare's current Linux instructions, then rerun this script." >&2
  exit 3
fi

read -r -s -p "Cloudflare Tunnel token: " TUNNEL_TOKEN
echo
if [[ -z "$TUNNEL_TOKEN" ]]; then
  echo "Tunnel token cannot be empty." >&2
  exit 2
fi

# If an old service exists, remove it before installing the new token.
if systemctl list-unit-files cloudflared.service >/dev/null 2>&1; then
  cloudflared service uninstall >/dev/null 2>&1 || true
fi

cloudflared service install "$TUNNEL_TOKEN"
unset TUNNEL_TOKEN

mkdir -p "$CONFIG_DIR"
printf '%s\n' "$PUBLIC_URL" > "$URL_FILE"
chmod 0644 "$URL_FILE"

systemctl enable cloudflared.service
systemctl restart cloudflared.service

echo "Remote access configured."
echo "Public URL: $PUBLIC_URL"
systemctl --no-pager --full status cloudflared.service | sed -n '1,12p'
