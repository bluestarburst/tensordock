#!/bin/bash
# DigitalOcean Startup Script for TensorDock
# This script sets up TensorDock services directly on a DigitalOcean droplet VM
# Expected environment variables:
#   USER_ID, INSTANCE_ID, RESOURCE_TYPE, START_TURN, MONITOR_API_KEY, FIREBASE_FUNCTIONS_URL
#   JUPYTER_TOKEN, TURN_USERNAME, TURN_PASSWORD, PUBLIC_IPADDR
#   GITHUB_REPO, GITHUB_BRANCH

set -o pipefail
LOG_FILE="/var/log/tensordock-setup.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== TensorDock VM Setup Started at $(date) ==="

# Default values if not set
TURN_USERNAME="${TURN_USERNAME:-user}"
PUBLIC_IPADDR="${PUBLIC_IPADDR:-auto}"
PYTHON_PORT="${PYTHON_PORT:-8765}"
TURN_PORT="${TURN_PORT:-3478}"
JUPYTER_PORT="${JUPYTER_PORT:-8888}"
GITHUB_REPO="${GITHUB_REPO:-https://github.com/bluestarburst/tensordock.git}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
APP_ROOT="/opt/tensordock"
REPO_DIR="$APP_ROOT/repo"
APP_DIR="$REPO_DIR"
SUPERVISOR_CONF="/etc/supervisor/conf.d/supervisord.conf"

wait_for_network() {
  local max_attempts=30
  local attempt=0
  while [ $attempt -lt $max_attempts ]; do
    if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
      echo "Network is available"
      return 0
    fi
    echo "Waiting for network... attempt $((attempt + 1))/$max_attempts"
    sleep 2
    attempt=$((attempt + 1))
  done
  echo "Warning: Network check timeout, continuing anyway"
  return 0
}

wait_for_network

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# Fix any broken packages first
apt-get --fix-broken install -y || true

# Install essential packages first
apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip git curl build-essential pkg-config \
  libffi-dev libssl-dev libnss3 libglu1-mesa libgl1 \
  libavcodec-dev libavformat-dev libavutil-dev libswscale-dev libavfilter-dev libavdevice-dev \
  libopus0 libsrtp2-1 ffmpeg ca-certificates \
  supervisor || {
  echo "WARNING: Some packages failed to install, continuing..."
}

# Install coturn separately (may fail on some systems, but we'll try)
apt-get install -y --no-install-recommends coturn || {
  echo "WARNING: coturn installation failed, TURN server may not work"
}

pip3 install --upgrade pip setuptools wheel
pip3 install --no-cache-dir supervisor

for username in appuser watcher; do
  if ! id "$username" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$username"
  fi
done

mkdir -p "$APP_ROOT" "$REPO_DIR"

if [ -d "$REPO_DIR/.git" ]; then
  echo "Updating existing TensorDock repository..."
  git -C "$REPO_DIR" fetch --depth 1 origin "$GITHUB_BRANCH" || true
  git -C "$REPO_DIR" checkout "$GITHUB_BRANCH" || true
  git -C "$REPO_DIR" reset --hard "origin/$GITHUB_BRANCH" || true
else
  echo "Cloning TensorDock repository..."
  git clone --depth 1 --branch "$GITHUB_BRANCH" "$GITHUB_REPO" "$REPO_DIR"
fi

if [ ! -d "$APP_DIR" ]; then
  echo "ERROR: TensorDock repository directory not found at $APP_DIR"
  exit 1
fi

if [ ! -f "$APP_DIR/requirements.txt" ]; then
  echo "ERROR: TensorDock requirements.txt not found in repository"
  exit 1
fi

if [ ! -f "$APP_DIR/supervisord.conf" ]; then
  echo "ERROR: TensorDock supervisord.conf not found in repository"
  exit 1
fi

pip3 install --no-cache-dir -r "$APP_DIR/requirements.txt"

mkdir -p /var/log/supervisor /tmp/tensordock-logs "$APP_DIR/logs" \
  /tmp/.local/share /tmp/.config /tmp/.cache \
  /tmp/jupyter-runtime /tmp/jupyter-data /tmp/jupyter-config

chown -R appuser:appuser "$APP_DIR" /tmp/tensordock-logs \
  /tmp/.local/share /tmp/.config /tmp/.cache /tmp/jupyter-runtime /tmp/jupyter-data /tmp/jupyter-config || true
chown watcher:watcher "$APP_DIR/monitor_service.py" 2>/dev/null || true
chmod 750 "$APP_DIR/monitor_service.py" 2>/dev/null || true

cp "$APP_DIR/supervisord.conf" "$SUPERVISOR_CONF"

PYTHON_BIN=$(command -v python3)
JUPYTER_BIN=$(command -v jupyter)

if [ -n "$PYTHON_BIN" ]; then
  sed -i "s|/usr/local/bin/python|$PYTHON_BIN|g" "$SUPERVISOR_CONF"
  sed -i "s|/usr/bin/python3|$PYTHON_BIN|g" "$SUPERVISOR_CONF"
fi

if [ -n "$JUPYTER_BIN" ]; then
  sed -i "s|/usr/local/bin/jupyter|$JUPYTER_BIN|g" "$SUPERVISOR_CONF"
fi

rm -f /var/run/supervisor.sock
mkdir -p /var/run
chmod 1777 /var/run
chown root:watcher /var/run 2>/dev/null || true

if [ -z "$JUPYTER_TOKEN" ]; then
  JUPYTER_TOKEN=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32 || echo "token-$(date +%s)")
fi

TURN_PASSWORD=$(openssl rand -base64 32 2>/dev/null | tr -dc 'a-zA-Z0-9' | head -c 32)
if [ -z "$TURN_PASSWORD" ]; then
  TURN_PASSWORD=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32)
fi

cat <<ENVFILE >/opt/tensordock/runtime.env
USER_ID="$USER_ID"
INSTANCE_ID="$INSTANCE_ID"
RESOURCE_TYPE="$RESOURCE_TYPE"
START_TURN="$START_TURN"
MONITOR_API_KEY="$MONITOR_API_KEY"
FIREBASE_FUNCTIONS_URL="$FIREBASE_FUNCTIONS_URL"
JUPYTER_TOKEN="$JUPYTER_TOKEN"
TURN_USERNAME="$TURN_USERNAME"
TURN_PASSWORD="$TURN_PASSWORD"
PUBLIC_IPADDR="$PUBLIC_IPADDR"
VAST_TCP_PORT_70000="$PYTHON_PORT"
VAST_UDP_PORT_70001="$TURN_PORT"
VAST_TCP_PORT_70002="$JUPYTER_PORT"
ENVFILE

chmod 640 /opt/tensordock/runtime.env
chown root:watcher /opt/tensordock/runtime.env || true

SUPERVISORD_BIN=$(command -v supervisord || true)
if [ -z "$SUPERVISORD_BIN" ]; then
  echo "ERROR: supervisord not found in PATH"
  exit 1
fi

cat <<'SERVICE' >/etc/systemd/system/tensordock-supervisor.service
[Unit]
Description=TensorDock Supervisor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/opt/tensordock/runtime.env
WorkingDirectory=/opt/tensordock/repo
ExecStart=@SUPERVISORD_BIN@ -c /etc/supervisor/conf.d/supervisord.conf -n
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

sed -i "s|@SUPERVISORD_BIN@|$SUPERVISORD_BIN|" /etc/systemd/system/tensordock-supervisor.service

systemctl daemon-reload
systemctl enable --now tensordock-supervisor.service

if command -v ufw >/dev/null 2>&1; then
  echo "Configuring firewall rules..."
  ufw allow $PYTHON_PORT/tcp || true
  ufw allow $JUPYTER_PORT/tcp || true
  ufw allow $TURN_PORT/udp || true
  ufw --force enable || true
fi

echo "=== TensorDock VM Setup Completed at $(date) ==="

