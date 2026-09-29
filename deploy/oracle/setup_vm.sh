#!/usr/bin/env bash
# One-shot setup for the trading bot on an Oracle Cloud Always-Free VM
# (Ubuntu 22.04/24.04, ARM or x86). Run as the default 'ubuntu' user:
#   bash setup_vm.sh
set -euo pipefail

REPO_URL="git@github.com:mohanmac/proactive_agentic_dt.git"
REPO_HTTPS="https://github.com/mohanmac/proactive_agentic_dt.git"
APP_DIR="$HOME/proactive_agentic_dt"

echo "== 1/5 System packages =="
sudo apt-get update -y
sudo apt-get install -y python3.12 python3.12-venv git curl || \
  sudo apt-get install -y python3 python3-venv git curl

echo "== 2/5 Clone repo =="
if [ ! -d "$APP_DIR" ]; then
  git clone "$REPO_HTTPS" "$APP_DIR"
fi
cd "$APP_DIR"

echo "== 3/5 Python venv + dependencies =="
PY=$(command -v python3.12 || command -v python3)
"$PY" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "== 4/5 .env =="
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo ">>> EDIT $APP_DIR/.env NOW with your real values:"
  echo ">>>   KITE_API_KEY, KITE_API_SECRET, ENABLE_LIVE_TRADING=true"
  echo ">>> then re-run this script to finish."
  exit 0
fi

echo "== 5/5 systemd service (auto-start on boot, restart on crash) =="
sudo tee /etc/systemd/system/agentic-dashboard.service >/dev/null <<UNIT
[Unit]
Description=Zerodha intraday bot dashboard (Streamlit)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/streamlit run ui/dashboard.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now agentic-dashboard

echo ""
echo "Done. Dashboard: http://$(hostname -I | awk '{print $1}'):8501"
echo "Recommended: install Tailscale for private access from anywhere:"
echo "  curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
