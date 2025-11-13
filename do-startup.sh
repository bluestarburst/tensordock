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
# Use a high ephemeral port (50000) to avoid conflicts with system services
# Port 3478 is commonly used by system coturn services
TURN_PORT="${TURN_PORT:-50000}"
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
  python3 python3-dev python3-venv python3-pip git curl build-essential pkg-config \
  libffi-dev libssl-dev libnss3 libglu1-mesa libgl1 \
  libavcodec-dev libavformat-dev libavutil-dev libswscale-dev libavfilter-dev libavdevice-dev \
  libopus0 libsrtp2-1 ffmpeg ca-certificates \
  supervisor lsof || {
  echo "WARNING: Some packages failed to install, continuing..."
}

# Install coturn separately (may fail on some systems, but we'll try)
apt-get install -y --no-install-recommends coturn || {
  echo "WARNING: coturn installation failed, TURN server may not work"
}

# Stop and disable system coturn service if it exists (it might be using port 3478)
# We'll run coturn via supervisor instead
if systemctl list-units --full -a | grep -q 'coturn.service'; then
  echo "Stopping system coturn service to free up port 3478..."
  systemctl stop coturn 2>/dev/null || true
  systemctl disable coturn 2>/dev/null || true
  systemctl mask coturn 2>/dev/null || true
fi

# Check if port 3478 is in use and kill any process using it
# This ensures we can use our chosen TURN port without conflicts
if command -v lsof >/dev/null 2>&1; then
  if lsof -i :3478 >/dev/null 2>&1; then
    echo "Port 3478 is in use, attempting to free it..."
    lsof -ti :3478 | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
elif command -v fuser >/dev/null 2>&1; then
  if fuser 3478/udp >/dev/null 2>&1 || fuser 3478/tcp >/dev/null 2>&1; then
    echo "Port 3478 is in use, attempting to free it..."
    fuser -k 3478/udp 2>/dev/null || true
    fuser -k 3478/tcp 2>/dev/null || true
    sleep 1
  fi
fi

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

echo "Installing Python dependencies..."
# Use --break-system-packages for Python 3.12+ or --ignore-installed for older versions
# This prevents conflicts with system-installed packages like pexpect
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -gt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -ge 12 ]); then
  echo "Python 3.12+ detected, using --break-system-packages flag"
  pip3 install --no-cache-dir --break-system-packages -r "$APP_DIR/requirements.txt" || {
    echo "ERROR: Failed to install Python dependencies"
    exit 1
  }
else
  echo "Python < 3.12 detected, using --ignore-installed flag"
  pip3 install --no-cache-dir --ignore-installed -r "$APP_DIR/requirements.txt" || {
    echo "ERROR: Failed to install Python dependencies"
    exit 1
  }
fi

echo "Creating directories..."
mkdir -p /var/log/supervisor /tmp/tensordock-logs "$APP_DIR/logs" \
  /tmp/.local/share /tmp/.config /tmp/.cache \
  /tmp/jupyter-runtime /tmp/jupyter-data /tmp/jupyter-config

echo "Setting up file permissions..."
# Verify users exist before chown operations
if ! id appuser >/dev/null 2>&1; then
  echo "ERROR: appuser does not exist"
  exit 1
fi

if ! id watcher >/dev/null 2>&1; then
  echo "ERROR: watcher user does not exist"
  exit 1
fi

# Set ownership for tmp directories first (smaller, faster)
chown -R appuser:appuser /tmp/tensordock-logs \
  /tmp/.local/share /tmp/.config /tmp/.cache \
  /tmp/jupyter-runtime /tmp/jupyter-data /tmp/jupyter-config 2>&1 || {
  echo "WARNING: Failed to chown tmp directories, continuing..."
}

# Set ownership for log directory
chown -R appuser:appuser "$APP_DIR/logs" 2>&1 || {
  echo "WARNING: Failed to chown log directory, continuing..."
}

# Create TURN server database directory (SQLite is optional but prevents errors)
# TURN server uses static credentials, so DB is not required, but creating it prevents warnings
mkdir -p /var/lib/turn
chown -R appuser:appuser /var/lib/turn 2>&1 || {
  echo "WARNING: Failed to create/chown TURN database directory, continuing..."
}
chmod 755 /var/lib/turn 2>&1 || true

# Only chown Python files and directories, not the entire repo (faster)
# This avoids hanging on large git repositories with many files
echo "Setting ownership for Python files and directories..."
# Chown directories first (faster, fewer operations)
find "$APP_DIR" -type d -exec chown appuser:appuser {} \; 2>&1 | grep -v "Permission denied" | head -5 || true
# Then chown Python files
find "$APP_DIR" -type f -name "*.py" ! -name "monitor_service.py" -exec chown appuser:appuser {} \; 2>&1 | grep -v "Permission denied" | head -5 || true
echo "File ownership setup completed"

# Set ownership for monitor_service.py specifically
chown watcher:watcher "$APP_DIR/monitor_service.py" 2>&1 || {
  echo "WARNING: Failed to chown monitor_service.py"
}
chmod 750 "$APP_DIR/monitor_service.py" 2>&1 || {
  echo "WARNING: Failed to chmod monitor_service.py"
}

cp "$APP_DIR/supervisord.conf" "$SUPERVISOR_CONF"

PYTHON_BIN=$(command -v python3)
JUPYTER_BIN=$(command -v jupyter)

# Update Python and Jupyter binary paths
if [ -n "$PYTHON_BIN" ]; then
  sed -i "s|/usr/local/bin/python|$PYTHON_BIN|g" "$SUPERVISOR_CONF"
  sed -i "s|/usr/bin/python3|$PYTHON_BIN|g" "$SUPERVISOR_CONF"
fi

if [ -n "$JUPYTER_BIN" ]; then
  sed -i "s|/usr/local/bin/jupyter|$JUPYTER_BIN|g" "$SUPERVISOR_CONF"
fi

# Update directory paths from /app to DigitalOcean path
echo "Updating supervisord.conf paths..."
sed -i "s|directory=/app|directory=$APP_DIR|g" "$SUPERVISOR_CONF"
sed -i "s|/app/|$APP_DIR/|g" "$SUPERVISOR_CONF"

echo "Setting up supervisor socket directory..."
rm -f /var/run/supervisor.sock
mkdir -p /var/run
chmod 1777 /var/run

# Verify watcher group exists before chown
if getent group watcher >/dev/null 2>&1; then
  chown root:watcher /var/run 2>&1 || {
    echo "WARNING: Failed to chown /var/run to root:watcher"
  }
else
  echo "WARNING: watcher group does not exist, skipping chown of /var/run"
fi

if [ -z "$JUPYTER_TOKEN" ]; then
  JUPYTER_TOKEN=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32 || echo "token-$(date +%s)")
fi

TURN_PASSWORD=$(openssl rand -base64 32 2>/dev/null | tr -dc 'a-zA-Z0-9' | head -c 32)
if [ -z "$TURN_PASSWORD" ]; then
  TURN_PASSWORD=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32)
fi

# Create runtime.env file with all environment variables
# Note: VAST_* port variables are used by monitor_service.py to update Firebase session ports
# For DigitalOcean, ports use identity mapping (internal = external) since there's no port forwarding
# The monitor service will read these and report: internal=8765, external=8765 (for example)
echo "Setting up environment variables:"
echo "  PYTHON_PORT=$PYTHON_PORT"
echo "  TURN_PORT=$TURN_PORT (using high ephemeral port to avoid conflicts)"
echo "  JUPYTER_PORT=$JUPYTER_PORT"

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
if getent group watcher >/dev/null 2>&1; then
  chown root:watcher /opt/tensordock/runtime.env 2>&1 || {
    echo "WARNING: Failed to chown runtime.env"
  }
else
  echo "WARNING: watcher group does not exist, skipping chown of runtime.env"
fi

# Configure firewall FIRST, before any service validation or startup
# This ensures ports are open before services try to bind to them
if command -v ufw >/dev/null 2>&1; then
  echo "Configuring firewall rules to expose ports..."
  
  # 1. Allow SSH first (CRITICAL)
  ufw allow 22/tcp
  
  # 2. Allow application ports
  ufw allow $PYTHON_PORT/tcp   # Python server
  ufw allow $JUPYTER_PORT/tcp  # Jupyter
  ufw allow $TURN_PORT/udp      # TURN server
  
  # 3. Set ENABLED=yes in config file
  sed -i 's/^ENABLED=.*/ENABLED=yes/' /etc/ufw/ufw.conf
  
  # 4. Enable UFW systemd service
  systemctl enable ufw
  
  # 5. Enable and start UFW
  ufw --force enable
  systemctl start ufw
  
  # 6. Verify it's active
  echo "Firewall status:"
  ufw status verbose
else
  echo "WARNING: ufw not found, ports may not be exposed. Consider configuring DigitalOcean Cloud Firewall via API."
fi

# Export environment variables for supervisord validation
# These are needed because supervisord.conf references them via %(ENV_VAR_NAME)s
export VAST_TCP_PORT_70000="${VAST_TCP_PORT_70000:-$PYTHON_PORT}"
export VAST_UDP_PORT_70001="${VAST_UDP_PORT_70001:-$TURN_PORT}"
export VAST_TCP_PORT_70002="${VAST_TCP_PORT_70002:-$JUPYTER_PORT}"

# Basic validation - just check that config file exists and is readable
# Note: supervisord -t actually starts supervisord, which causes issues, so we skip full validation
echo "Checking supervisord configuration file..."
if [ ! -f "$SUPERVISOR_CONF" ]; then
  echo "ERROR: supervisord configuration file not found: $SUPERVISOR_CONF"
  exit 1
fi

if [ ! -r "$SUPERVISOR_CONF" ]; then
  echo "ERROR: supervisord configuration file is not readable: $SUPERVISOR_CONF"
  exit 1
fi

echo "✅ Supervisord configuration file exists and is readable"

# Now start supervisord AFTER firewall is configured
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
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

sed -i "s|@SUPERVISORD_BIN@|$SUPERVISORD_BIN|" /etc/systemd/system/tensordock-supervisor.service

echo "Reloading systemd daemon..."
systemctl daemon-reload || {
  echo "ERROR: systemctl daemon-reload failed"
  exit 1
}

echo "Enabling tensordock-supervisor.service..."
systemctl enable tensordock-supervisor.service || {
  echo "WARNING: Failed to enable tensordock-supervisor.service"
}

echo "Starting tensordock-supervisor.service..."
# Start the service - systemctl start should return immediately for Type=simple services
# Use timeout as a safety net, but it should return immediately
if timeout 5 systemctl start tensordock-supervisor.service 2>&1; then
  echo "✅ tensordock-supervisor.service started successfully"
else
  EXIT_CODE=$?
  if [ $EXIT_CODE -eq 124 ]; then
    echo "WARNING: systemctl start timed out (this shouldn't happen for Type=simple)"
  else
    echo "WARNING: systemctl start returned exit code: $EXIT_CODE"
  fi
  # Continue anyway - the service might still be starting
fi

# Give supervisord a moment to start, then verify it's running
sleep 2
if systemctl is-active --quiet tensordock-supervisor.service; then
  echo "✅ tensordock-supervisor.service is active and running"
else
  echo "WARNING: tensordock-supervisor.service is not active"
  echo "Checking service status..."
  systemctl status tensordock-supervisor.service --no-pager -l 2>&1 | head -20 || true
  echo "Checking recent journal logs..."
  journalctl -u tensordock-supervisor.service --no-pager -n 20 2>&1 | head -30 || true
fi

echo "=== TensorDock VM Setup Completed at $(date) ==="
echo "Setup script finished. Services should be starting via systemd."

# Explicitly exit with success code to ensure cloud-init reports success
exit 0

