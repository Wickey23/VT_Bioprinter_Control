#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Run this as the normal Pi user, not root."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
PIP="$SCRIPT_DIR/.venv/bin/pip"

if [[ ! -x "$PYTHON" ]]; then
  echo "Project virtual environment is missing. Run complete_setup.sh first."
  exit 2
fi

echo "=== VT Bioprinter controller update validation ==="

cd "$REPO_DIR"
echo "[1/6] Pulling main..."
git pull --ff-only

echo "[2/6] Syncing Python dependencies..."
"$PIP" install -r "$SCRIPT_DIR/requirements.txt"

echo "[3/6] Compiling controller Python..."
"$PYTHON" -m py_compile   "$SCRIPT_DIR/webapp/app.py"   "$SCRIPT_DIR/webapp/realsense.py"   "$SCRIPT_DIR/webapp/calibration.py"   "$SCRIPT_DIR/webapp/print_plan.py"   "$SCRIPT_DIR/webapp/bioprint.py"   "$SCRIPT_DIR/webapp/experiments.py"   "$SCRIPT_DIR/webapp/quality.py"   "$SCRIPT_DIR/webapp/vision.py"   "$SCRIPT_DIR/controller_self_test.py"

echo "[4/6] Running offline self-tests..."
cd "$SCRIPT_DIR"
"$PYTHON" controller_self_test.py

echo "[5/6] Refreshing network helper and restarting web controller..."
sudo install -m 0755 "$SCRIPT_DIR/network_helper.sh" /usr/local/sbin/vt-bioprinter-network
sudo systemctl restart vt-bioprinter-web.service
sleep 2
sudo systemctl --no-pager --full is-active vt-bioprinter-web.service

echo "[6/6] Health checks..."
curl -fsS http://127.0.0.1:8080/api/health
echo
curl -fsS -H "X-Bioprinter-Token: enter" http://127.0.0.1:8080/api/camera/status
echo

echo
echo "Controller update validated."
echo "Open http://vt-3dprinter.local:8080 and refresh the browser."
