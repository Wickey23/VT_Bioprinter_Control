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
HOTSPOT_FALLBACK_TARGET="/usr/local/sbin/vt-bioprinter-hotspot-fallback"
HOTSPOT_SERVICE_NAME="vt-bioprinter-hotspot-fallback.service"
HOTSPOT_SERVICE_PATH="/etc/systemd/system/$HOTSPOT_SERVICE_NAME"
SUDOERS_PATH="/etc/sudoers.d/vt-bioprinter-network"

HOTSPOT_NAME="VT-Bioprinter-Setup"
HOTSPOT_PASSWORD="bioprinter"
HOTSPOT_IP="10.42.0.1/24"

echo "=== Installing VT Bioprinter web controller ==="

cd "$REPO_DIR"
git pull --ff-only

echo "[1/9] Installing Python dependencies..."
if [[ ! -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$SCRIPT_DIR/.venv"
fi
"$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

echo "[2/9] Configuring simple local controller key..."
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
printf '%s\n' 'enter' > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

echo "[3/9] Installing restricted network helpers..."
sudo install -o root -g root -m 0755 "$SCRIPT_DIR/network_helper.sh" "$NETWORK_HELPER_TARGET"
sudo install -o root -g root -m 0755 "$SCRIPT_DIR/hotspot_fallback.sh" "$HOTSPOT_FALLBACK_TARGET"
printf '%s\n' "$USER ALL=(root) NOPASSWD: $NETWORK_HELPER_TARGET *" | sudo tee "$SUDOERS_PATH" >/dev/null
sudo chmod 0440 "$SUDOERS_PATH"
sudo visudo -cf "$SUDOERS_PATH" >/dev/null

echo "[4/9] Creating direct-access Wi-Fi profile..."
if sudo nmcli -t -f NAME connection show | grep -Fxq "$HOTSPOT_NAME"; then
  echo "Hotspot profile already exists; refreshing settings."
else
  sudo nmcli connection add type wifi ifname wlan0 con-name "$HOTSPOT_NAME" ssid "$HOTSPOT_NAME"
fi

sudo nmcli connection modify "$HOTSPOT_NAME" \
  connection.autoconnect no \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  ipv4.method shared \
  ipv4.addresses "$HOTSPOT_IP" \
  ipv6.method disabled \
  802-11-wireless-security.key-mgmt wpa-psk \
  802-11-wireless-security.psk "$HOTSPOT_PASSWORD"

echo "[5/9] Installing automatic hotspot fallback..."
sudo tee "$HOTSPOT_SERVICE_PATH" >/dev/null <<EOF
[Unit]
Description=VT Bioprinter fallback setup hotspot
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
ExecStart=$HOTSPOT_FALLBACK_TARGET

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable "$HOTSPOT_SERVICE_NAME"

echo "[6/9] Installing web-controller service..."
sudo tee "$SERVICE_PATH" >/dev/null <<EOF
[Unit]
Description=VT Bioprinter Web Controller
After=network.target
Wants=network.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONUNBUFFERED=1
Environment=VT_BIOPRINTER_CONFIG_DIR=$CONFIG_DIR
Environment=VT_BIOPRINTER_NETWORK_HELPER=$NETWORK_HELPER_TARGET
Environment=LD_LIBRARY_PATH=/usr/local/lib
ExecStart=$SCRIPT_DIR/.venv/bin/uvicorn webapp.app:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "[7/9] Enabling and restarting web controller..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "[8/9] Service check..."
sleep 2
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true

echo "[9/9] Local health check..."
curl -fsS http://127.0.0.1:8080/api/health || true
echo

IP="$(hostname -I | awk '{print $1}')"

echo
echo "===================================================="
echo "VT Bioprinter controller installed."
echo
echo "NORMAL NETWORK ACCESS"
echo "  http://vt-3dprinter.local:8080"
if [[ -n "$IP" ]]; then
  echo "  http://$IP:8080"
fi
echo
echo "CONTROLLER ACCESS KEY"
echo "  enter"
echo
echo "DIRECT / FALLBACK WI-FI"
echo "  Wi-Fi name: $HOTSPOT_NAME"
echo "  Wi-Fi password: $HOTSPOT_PASSWORD"
echo "  Controller URL: http://10.42.0.1:8080"
echo
echo "If no normal Wi-Fi is active after boot, the Pi will"
echo "automatically start the setup hotspot after about 25 seconds."
echo "The Network page can also turn hotspot mode on or off manually."
echo
echo "REALSENSE D405"
echo "  Camera USB detection works immediately."
echo "  For depth frames/sensing, run:"
echo "    bash $SCRIPT_DIR/install_realsense.sh"
echo "===================================================="
