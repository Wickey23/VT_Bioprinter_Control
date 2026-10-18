#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Run this as the normal Pi user, not root."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_DIR="$HOME/.config/vt-bioprinter"
TOKEN_FILE="$CONFIG_DIR/token"
SERVICE_NAME="vt-bioprinter-web.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
NETWORK_HELPER_TARGET="/usr/local/sbin/vt-bioprinter-network"
SUDOERS_PATH="/etc/sudoers.d/vt-bioprinter-network"

echo "=== Installing VT Bioprinter web controller ==="

cd "$REPO_DIR"
git pull --ff-only

echo "[1/7] Installing Python dependencies..."
if [[ ! -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$SCRIPT_DIR/.venv"
fi
"$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

echo "[2/7] Creating controller access key..."
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
if [[ ! -s "$TOKEN_FILE" ]]; then
  python3 - <<'PY' > "$TOKEN_FILE"
import secrets
print(secrets.token_urlsafe(24))
PY
fi
chmod 600 "$TOKEN_FILE"

echo "[3/7] Installing restricted network helper..."
sudo install -o root -g root -m 0755 "$SCRIPT_DIR/network_helper.sh" "$NETWORK_HELPER_TARGET"
printf '%s\n' "$USER ALL=(root) NOPASSWD: $NETWORK_HELPER_TARGET *" | sudo tee "$SUDOERS_PATH" >/dev/null
sudo chmod 0440 "$SUDOERS_PATH"
sudo visudo -cf "$SUDOERS_PATH" >/dev/null

echo "[4/7] Installing systemd service..."
sudo tee "$SERVICE_PATH" >/dev/null <<EOF
[Unit]
Description=VT Bioprinter Web Controller
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONUNBUFFERED=1
Environment=VT_BIOPRINTER_CONFIG_DIR=$CONFIG_DIR
Environment=VT_BIOPRINTER_NETWORK_HELPER=$NETWORK_HELPER_TARGET
ExecStart=$SCRIPT_DIR/.venv/bin/uvicorn webapp.app:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "[5/7] Enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

echo "[6/7] Service check..."
sleep 2
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true

echo "[7/7] Local health check..."
curl -fsS http://127.0.0.1:8080/api/health || true
echo

IP="$(hostname -I | awk '{print $1}')"
TOKEN="$(cat "$TOKEN_FILE")"

echo
echo "==============================================="
echo "VT Bioprinter web controller installed."
echo
echo "Open on this Pi/network:"
echo "  http://vt-3dprinter.local:8080"
if [[ -n "$IP" ]]; then
  echo "  http://$IP:8080"
fi
echo
echo "Controller access key:"
echo "  $TOKEN"
echo
echo "Keep this key private. The UI will ask for it once and store it in that browser."
echo "==============================================="
