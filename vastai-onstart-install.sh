#!/bin/bash
# VastAI Onstart Installation Script
# Installs all dependencies and sets up TensorDock on VastAI PyTorch template
# This script is idempotent - safe to run multiple times

set -euo pipefail

# Logging function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >&2
}

log "Starting TensorDock installation on VastAI PyTorch template"

# Diagnostic: Check initial state
log "=== Initial Diagnostic Information ==="
log "Current working directory: $(pwd)"
log "Current user: $(whoami)"
log "User ID: $(id -u)"
log "Checking if /app exists: $([ -d /app ] && echo 'YES' || echo 'NO')"
log "Checking if /app is writable: $([ -w /app ] && echo 'YES' || echo 'NO' 2>/dev/null || echo 'N/A (does not exist)')"
log "Root filesystem info:"
df -h / | tail -1
log "======================================"

# Export VAST_* environment variables (set by VastAI)
log "Exporting VastAI port environment variables..."
for var in $(env | grep -E '^VAST_' | cut -d= -f1); do
    export "$var"
    log "  Exported: $var"
done

# Set environment variables
export DEBIAN_FRONTEND=noninteractive
export PIP_NO_CACHE_DIR=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

# Update package lists
log "Updating package lists..."
apt-get update -qq || {
    log "WARNING: apt-get update failed, continuing anyway..."
}

# Install basic tools first
log "Installing basic tools (curl, git, procps)..."
apt-get install -y --no-install-recommends curl git procps || {
    log "ERROR: Failed to install basic tools"
    exit 1
}

# Configure APT to handle hash sum mismatches
log "Configuring APT for reliability..."
mkdir -p /etc/apt/apt.conf.d
cat > /etc/apt/apt.conf.d/99acquire-by-hash <<EOF
Acquire::By-Hash "yes";
Acquire::http::Pipeline-Depth 0;
Acquire::http::No-Cache true;
Acquire::BrokenProxy true;
Acquire::Check-Valid-Until false;
EOF

# Install supervisor via pip (more reliable than apt)
log "Installing supervisor via pip..."
if ! command -v supervisord >/dev/null 2>&1; then
    pip install --no-cache-dir supervisor || {
        log "ERROR: Failed to install supervisor"
        exit 1
    }
    log "Supervisor installed at: $(which supervisord)"
else
    log "Supervisor already installed at: $(which supervisord)"
fi

# Install coturn and openssh-server with retry logic
log "Installing coturn and openssh-server..."
success=false
for i in 1 2 3 4 5; do
    log "Installation attempt $i of 5..."
    apt-get clean
    rm -rf /var/lib/apt/lists/*
    apt-get update -o Acquire::CompressionTypes::Order::=gz -qq || true
    if apt-get install -y --no-install-recommends coturn openssh-server; then
        success=true
        log "Installation successful on attempt $i"
        break
    else
        log "Attempt $i failed, retrying in 10 seconds..."
        sleep 10
    fi
done

if [ "$success" != "true" ]; then
    log "ERROR: Failed to install coturn and openssh-server after 5 attempts"
    exit 1
fi

# Install multimedia libraries (optional, don't fail if unavailable)
log "Installing multimedia libraries (optional)..."
# Install basic multimedia libraries (these are commonly available across Ubuntu versions)
# Note: FFmpeg library versions vary by Ubuntu release, so we only install the most common ones
apt-get install -y --no-install-recommends \
    libopus0 libsrtp2-1 2>/dev/null || {
    log "WARNING: Some multimedia libraries failed to install (non-critical)"
}
# Try to install libvpx (version may vary: libvpx7 for older, libvpx9 for newer)
apt-get install -y --no-install-recommends libvpx9 2>/dev/null || \
apt-get install -y --no-install-recommends libvpx7 2>/dev/null || \
apt-get install -y --no-install-recommends libvpx6 2>/dev/null || {
    log "WARNING: libvpx not available (non-critical)"
}

# Clean up apt cache
rm -rf /var/lib/apt/lists/*

# Create users if they don't exist
log "Creating users..."

# Helper function to check if a UID is taken
uid_taken() {
    local uid=$1
    getent passwd "$uid" >/dev/null 2>&1
}

# Helper function to get username for a UID
get_username_for_uid() {
    local uid=$1
    getent passwd "$uid" | cut -d: -f1 2>/dev/null || echo "unknown"
}

# Helper function to find next available UID
find_available_uid() {
    local start_uid=$1
    local max_attempts=${2:-10}
    local uid=$start_uid
    local attempts=0
    
    while [ $attempts -lt $max_attempts ]; do
        if ! uid_taken "$uid"; then
            echo "$uid"
            return 0
        fi
        uid=$((uid + 1))
        attempts=$((attempts + 1))
    done
    return 1
}

# Check if appuser exists
if ! id appuser >/dev/null 2>&1; then
    # Check if UID 1000 is already taken by another user
    if uid_taken 1000; then
        EXISTING_USER=$(get_username_for_uid 1000)
        log "UID 1000 is already taken by user: $EXISTING_USER"
        # Find next available UID starting from 1002
        AVAILABLE_UID=$(find_available_uid 1002 20)
        if [ -n "$AVAILABLE_UID" ]; then
            if useradd -m -u "$AVAILABLE_UID" -s /bin/bash appuser; then
                log "Created user: appuser (UID $AVAILABLE_UID, UID 1000 was taken by $EXISTING_USER)"
            else
                log "ERROR: Failed to create appuser with UID $AVAILABLE_UID"
                exit 1
            fi
        else
            log "ERROR: Could not find available UID for appuser"
            exit 1
        fi
    else
        # UID 1000 is available, use it
        if useradd -m -u 1000 -s /bin/bash appuser; then
            log "Created user: appuser (UID 1000)"
        else
            log "ERROR: Failed to create appuser with UID 1000"
            exit 1
        fi
    fi
else
    log "User appuser already exists (UID: $(id -u appuser))"
fi

# Check if watcher exists
if ! id watcher >/dev/null 2>&1; then
    # Check if UID 1001 is already taken
    if uid_taken 1001; then
        EXISTING_USER=$(get_username_for_uid 1001)
        log "UID 1001 is already taken by user: $EXISTING_USER"
        # Find next available UID starting from 1002 (but skip if it's appuser's UID)
        APPUSER_UID=$(id -u appuser 2>/dev/null || echo "")
        AVAILABLE_UID=$(find_available_uid 1002 20)
        # If the found UID is appuser's UID, try next one
        while [ -n "$AVAILABLE_UID" ] && [ "$AVAILABLE_UID" = "$APPUSER_UID" ]; do
            AVAILABLE_UID=$(find_available_uid $((AVAILABLE_UID + 1)) 20)
        done
        if [ -n "$AVAILABLE_UID" ]; then
            if useradd -m -u "$AVAILABLE_UID" -s /bin/bash watcher; then
                log "Created user: watcher (UID $AVAILABLE_UID, UID 1001 was taken by $EXISTING_USER)"
            else
                log "ERROR: Failed to create watcher with UID $AVAILABLE_UID"
                exit 1
            fi
        else
            log "ERROR: Could not find available UID for watcher"
            exit 1
        fi
    else
        if useradd -m -u 1001 -s /bin/bash watcher; then
            log "Created user: watcher (UID 1001)"
        else
            log "ERROR: Failed to create watcher with UID 1001"
            exit 1
        fi
    fi
else
    log "User watcher already exists (UID: $(id -u watcher))"
fi

# Create app directory
log "Setting up application directory..."
if ! mkdir -p /app; then
    log "ERROR: Failed to create /app directory"
    exit 1
fi

if ! cd /app; then
    log "ERROR: Failed to change to /app directory"
    exit 1
fi

log "Application directory created successfully at: $(pwd)"
log "Current directory contents:"
ls -la /app/ 2>/dev/null || log "  (directory is empty or cannot list)"

# Download application code from GitHub
log "Downloading application code from GitHub..."
GITHUB_REPO="https://github.com/bluestarburst/tensordock.git"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"

if [ -d "/app/.git" ]; then
    log "Git repository already exists, pulling latest changes..."
    cd /app
    git fetch origin || true
    git reset --hard "origin/${GITHUB_BRANCH}" || true
else
    log "Cloning repository from ${GITHUB_REPO} (branch: ${GITHUB_BRANCH})..."
    rm -rf /app/* /app/.* 2>/dev/null || true
    
    # Verify /app directory exists before cloning
    if [ ! -d "/app" ]; then
        log "ERROR: /app directory does not exist before git clone"
        exit 1
    fi
    
    if ! git clone --depth 1 --branch "${GITHUB_BRANCH}" "${GITHUB_REPO}" /app; then
        log "ERROR: Failed to clone repository"
        log "Checking /app directory state:"
        ls -la /app/ 2>/dev/null || log "  /app directory does not exist or is not accessible"
        exit 1
    fi
    
    # Verify clone succeeded
    if [ ! -d "/app/.git" ]; then
        log "ERROR: Git clone completed but .git directory not found"
        log "Checking /app directory contents:"
        ls -la /app/ 2>/dev/null || log "  /app directory does not exist or is not accessible"
        exit 1
    fi
    
    log "Repository cloned successfully"
    log "Verifying /app directory contents:"
    ls -la /app/ | head -20
fi

# Remove control-plane directory if it exists
if [ -d "/app/control-plane" ]; then
    log "Removing control-plane directory..."
    rm -rf /app/control-plane
fi

# Install build dependencies for Python packages (especially PyAV/av)
log "Installing build dependencies for Python packages..."
apt-get update -qq || true

# Install essential build tools (required)
apt-get install -y --no-install-recommends \
    pkg-config \
    python3-dev \
    build-essential 2>/dev/null || {
    log "ERROR: Failed to install essential build tools"
    exit 1
}

# Install FFmpeg development libraries (required for PyAV)
# Try to install dev packages, fallback gracefully if not available
log "Installing FFmpeg development libraries..."
apt-get install -y --no-install-recommends \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    libavfilter-dev \
    libavdevice-dev 2>/dev/null || {
    log "WARNING: FFmpeg dev packages may not be available, PyAV may fail to build"
    log "Attempting to install without version numbers..."
    # Try without version-specific names (Ubuntu 24.04 may use different naming)
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libavcodec-dev \
        libavformat-dev 2>/dev/null || {
        log "WARNING: FFmpeg libraries not available - PyAV installation may fail"
    }
}

# Install Python dependencies
log "Installing Python dependencies..."
if [ -f "/app/requirements.txt" ]; then
    # Use --break-system-packages for Python 3.12+ to handle system-installed packages
    # and --ignore-installed to avoid conflicts with system packages
    pip install --no-cache-dir --break-system-packages --ignore-installed -r /app/requirements.txt || {
        log "ERROR: Failed to install Python dependencies"
        exit 1
    }
    log "Python dependencies installed successfully"
else
    log "WARNING: requirements.txt not found, skipping Python dependency installation"
fi

# Create log directories
log "Creating log directories..."
mkdir -p /var/log/supervisor /app/logs /tmp/tensordock-logs
mkdir -p /var/run
chmod 1777 /var/run

# Set up directories for non-root users
export XDG_DATA_HOME="/tmp/.local/share"
export XDG_CONFIG_HOME="/tmp/.config"
export XDG_CACHE_HOME="/tmp/.cache"
export JUPYTER_RUNTIME_DIR="/tmp/jupyter-runtime"
export JUPYTER_DATA_DIR="/tmp/jupyter-data"
export JUPYTER_CONFIG_DIR="/tmp/jupyter-config"
export TD_LOG_DIR="/tmp/tensordock-logs"

mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" \
         "$JUPYTER_RUNTIME_DIR" "$JUPYTER_DATA_DIR" "$JUPYTER_CONFIG_DIR"

# Copy supervisord.conf
log "Setting up supervisord configuration..."
SUPERVISORD_CONF=""
if [ -f "/app/supervisord.conf" ]; then
    SUPERVISORD_CONF="/app/supervisord.conf"
    log "Found supervisord.conf at /app/supervisord.conf"
elif [ -f "/app/tensordock/supervisord.conf" ]; then
    SUPERVISORD_CONF="/app/tensordock/supervisord.conf"
    log "Found supervisord.conf at /app/tensordock/supervisord.conf"
else
    log "ERROR: supervisord.conf not found in /app or /app/tensordock"
    log "Checking /app directory contents:"
    ls -la /app/ | head -20
    if [ -d "/app/tensordock" ]; then
        log "Checking /app/tensordock directory contents:"
        ls -la /app/tensordock/ | head -20
    fi
    exit 1
fi

if [ -n "$SUPERVISORD_CONF" ]; then
    mkdir -p /etc/supervisor/conf.d
    cp "$SUPERVISORD_CONF" /etc/supervisor/conf.d/supervisord.conf
    chown root:root /etc/supervisor/conf.d/supervisord.conf
    chmod 644 /etc/supervisor/conf.d/supervisord.conf
    log "Supervisord configuration copied from $SUPERVISORD_CONF"
fi

# Set proper file ownership and permissions
log "Setting file ownership and permissions..."
chown watcher:watcher /app/monitor_service.py 2>/dev/null || true
chmod 750 /app/monitor_service.py 2>/dev/null || true
chown -R appuser:appuser /app/logs 2>/dev/null || true
find /app -type f -name "*.py" ! -name "monitor_service.py" -exec chown appuser:appuser {} \; 2>/dev/null || true
find /app -type d ! -path "/app" -exec chown appuser:appuser {} \; 2>/dev/null || true
chmod -R 755 /app 2>/dev/null || true
chmod 750 /app/monitor_service.py 2>/dev/null || true
chown -R watcher:watcher /var/log/supervisor 2>/dev/null || true
chmod 755 /app/start.sh 2>/dev/null || true

# Make diagnostic scripts executable
chmod +x /app/diagnose-container.sh /app/show-env-vars.sh 2>/dev/null || true

# Configure SSH server
log "Configuring SSH server..."
mkdir -p /var/run/sshd
if ! grep -q "^PermitRootLogin yes" /etc/ssh/sshd_config 2>/dev/null; then
    echo 'root:root' | chpasswd
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config || true
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config || true
    echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config || true
    log "SSH server configured"
fi

# Set up TURN server environment variables
log "Setting up TURN server configuration..."
if [ -z "${TURN_USERNAME:-}" ]; then
    export TURN_USERNAME="user"
fi

if [ -z "${TURN_PASSWORD:-}" ]; then
    export TURN_PASSWORD=$(openssl rand -base64 32 2>/dev/null || echo "password")
    log "Generated TURN password"
fi

# Auto-detect public IP if needed
if [ "${PUBLIC_IPADDR:-}" = "auto" ] || [ -z "${PUBLIC_IPADDR:-}" ]; then
    log "Auto-detecting public IP address..."
    # Try DigitalOcean metadata
    META_IP=$(curl -fsS --max-time 2 http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address 2>/dev/null || true)
    if [ -n "$META_IP" ]; then
        export PUBLIC_IPADDR="$META_IP"
        log "Detected public IP from metadata: $PUBLIC_IPADDR"
    else
        # Fallback to external service
        export PUBLIC_IPADDR=$(curl -fsS --max-time 3 https://ifconfig.co 2>/dev/null || true)
        if [ -n "$PUBLIC_IPADDR" ]; then
            log "Detected public IP from ifconfig.co: $PUBLIC_IPADDR"
        else
            log "WARNING: Could not detect public IP address"
        fi
    fi
fi

# Verify supervisor installation
if ! command -v supervisord >/dev/null 2>&1; then
    log "ERROR: supervisord not found in PATH"
    exit 1
fi

SUPERVISORD_PATH=$(which supervisord)
log "Supervisord found at: $SUPERVISORD_PATH"

# Set default empty values for VAST_* environment variables if not set
# Supervisord requires these variables to exist when parsing the config file
# Even if empty, they must be defined for %(ENV_VAR_NAME)s syntax to work
export VAST_TCP_PORT_70000="${VAST_TCP_PORT_70000:-}"
export VAST_UDP_PORT_70001="${VAST_UDP_PORT_70001:-}"
export VAST_TCP_PORT_70002="${VAST_TCP_PORT_70002:-}"
export VAST_TCP_PORT_22="${VAST_TCP_PORT_22:-}"

# Start supervisord as PID 1
log "Starting supervisord..."
log "Environment variables:"
log "  USER_ID: ${USER_ID:-<not set>}"
log "  INSTANCE_ID: ${INSTANCE_ID:-<not set>}"
log "  RESOURCE_TYPE: ${RESOURCE_TYPE:-<not set>}"
log "  START_TURN: ${START_TURN:-<not set>}"
log "  PUBLIC_IPADDR: ${PUBLIC_IPADDR:-<not set>}"
log "  VAST_TCP_PORT_70000: ${VAST_TCP_PORT_70000:-<not set>}"
log "  VAST_UDP_PORT_70001: ${VAST_UDP_PORT_70001:-<not set>}"
log "  VAST_TCP_PORT_70002: ${VAST_TCP_PORT_70002:-<not set>}"
log "  VAST_TCP_PORT_22: ${VAST_TCP_PORT_22:-<not set>}"

exec "$SUPERVISORD_PATH" -c /etc/supervisor/conf.d/supervisord.conf -n



