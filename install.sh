#!/usr/bin/env bash
set -e

SERVICE_NAME="spotify-display"
REPO_DIR="$HOME/e-ink_display"
VENV_DIR="$REPO_DIR/venv"

echo "[*] Using repo dir: $REPO_DIR"
cd "$REPO_DIR"

# 1) Create venv if missing
if [ ! -d "$VENV_DIR" ]; then
  echo "[*] Creating virtualenv at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

# 2) Install requirements
echo "[*] Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r requirements.txt

# 3) Install systemd unit
echo "[*] Installing systemd service template..."
sudo cp "$REPO_DIR/spotify-display@.service" /etc/systemd/system/

# 4) Reload systemd, enable + start instance for this user
echo "[*] Enabling and starting ${SERVICE_NAME}@$USER.service"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}@$USER.service"
sudo systemctl restart "${SERVICE_NAME}@$USER.service"

echo "[✓] Done. Service: ${SERVICE_NAME}@$USER.service is running."
