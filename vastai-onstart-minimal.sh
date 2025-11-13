#!/bin/bash
# VastAI Minimal Onstart Script
# This script only handles runtime configuration since all dependencies are pre-baked in the Docker image
# Expected startup time: 30-60 seconds (vs 5-10+ minutes with full installation)

set -euo pipefail

# Logging function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >&2
}

log "Starting TensorDock minimal setup (pre-baked image)"

# Export VAST_* environment variables (set by VastAI)
# These are automatically set by Vast AI when ports are exposed via -p flags
log "Exporting VastAI port environment variables..."
for var in $(env | grep -E '^VAST_' | cut -d= -f1); do
    export "$var"
    log "  Exported: $var=${!var}"
done

# Persist VAST_* and other important environment variables to /etc/environment
# This makes them available in Jupyter sessions
log "Persisting environment variables to /etc/environment..."
env | grep -E '^(VAST_|USER_ID|INSTANCE_ID|RESOURCE_TYPE|MONITOR_API_KEY|FIREBASE_FUNCTIONS_URL|START_TURN|JUPYTER_TOKEN|TURN_USERNAME|TURN_PASSWORD|PUBLIC_IPADDR|GITHUB_REPO|GITHUB_BRANCH)=' >> /etc/environment || {
    log "WARNING: Failed to write to /etc/environment (non-critical)"
}

# Set up TURN server environment variables if needed
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

# Optional: Pull latest code from GitHub if GITHUB_REPO is set
# This allows code updates without rebuilding the image
if [ -n "${GITHUB_REPO:-}" ] && [ -n "${GITHUB_BRANCH:-}" ]; then
    log "Pulling latest code from ${GITHUB_REPO} (branch: ${GITHUB_BRANCH})..."
    if [ -d "/app/.git" ]; then
        cd /app
        git fetch origin || true
        git reset --hard "origin/${GITHUB_BRANCH}" || true
        log "Code updated from GitHub"
    else
        log "WARNING: /app/.git not found, skipping git pull (using pre-baked code)"
    fi
fi

# Detect Python and Jupyter paths (in case they differ from defaults)
log "Detecting Python and Jupyter paths..."
PYTHON3_PATH=""
JUPYTER_PATH=""

# Try common Python3 paths
for path in /usr/bin/python3 /usr/local/bin/python3 /usr/bin/python /usr/local/bin/python; do
    if [ -f "$path" ] && "$path" --version >/dev/null 2>&1; then
        PYTHON3_PATH="$path"
        log "Found Python3 at: $PYTHON3_PATH"
        break
    fi
done

# Try common Jupyter paths
for path in /usr/local/bin/jupyter /usr/bin/jupyter "$(which jupyter 2>/dev/null)"; do
    if [ -n "$path" ] && [ -f "$path" ] && "$path" --version >/dev/null 2>&1; then
        JUPYTER_PATH="$path"
        log "Found Jupyter at: $JUPYTER_PATH"
        break
    fi
done

# Fallback: use python3 from PATH if available
if [ -z "$PYTHON3_PATH" ]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON3_PATH=$(which python3)
        log "Found Python3 via PATH: $PYTHON3_PATH"
    else
        log "ERROR: Could not find Python3"
        exit 1
    fi
fi

# Fallback: use jupyter from PATH if available
if [ -z "$JUPYTER_PATH" ]; then
    if command -v jupyter >/dev/null 2>&1; then
        JUPYTER_PATH=$(which jupyter)
        log "Found Jupyter via PATH: $JUPYTER_PATH"
    else
        log "WARNING: Could not find Jupyter, will use /usr/local/bin/jupyter as fallback"
        JUPYTER_PATH="/usr/local/bin/jupyter"
    fi
fi

# Update supervisord.conf with detected paths if they differ from defaults
# Only update if paths are different to avoid unnecessary changes
if [ -n "$PYTHON3_PATH" ] && [ "$PYTHON3_PATH" != "/usr/local/bin/python" ]; then
    log "Updating Python path in supervisord.conf: $PYTHON3_PATH"
    sed -i "s|/usr/local/bin/python|$PYTHON3_PATH|g" /etc/supervisor/conf.d/supervisord.conf
    sed -i "s|/usr/bin/python3|$PYTHON3_PATH|g" /etc/supervisor/conf.d/supervisord.conf
fi

if [ -n "$JUPYTER_PATH" ] && [ "$JUPYTER_PATH" != "/usr/local/bin/jupyter" ]; then
    log "Updating Jupyter path in supervisord.conf: $JUPYTER_PATH"
    sed -i "s|/usr/local/bin/jupyter|$JUPYTER_PATH|g" /etc/supervisor/conf.d/supervisord.conf
fi

# Remove VAST_TCP_PORT_22 from monitor service environment (SSH removed, no longer needed)
# This is a workaround for old Docker images that still have this reference
if grep -q 'VAST_TCP_PORT_22' /etc/supervisor/conf.d/supervisord.conf; then
    log "Removing VAST_TCP_PORT_22 from monitor service environment..."
    sed -i 's/,VAST_TCP_PORT_22="%(ENV_VAST_TCP_PORT_22)s"//g' /etc/supervisor/conf.d/supervisord.conf
fi

# Set default empty values for VAST_* environment variables if not set
# Supervisord requires these variables to exist when parsing the config file
# Even if empty, they must be defined for %(ENV_VAR_NAME)s syntax to work
export VAST_TCP_PORT_70000="${VAST_TCP_PORT_70000:-}"
export VAST_UDP_PORT_70001="${VAST_UDP_PORT_70001:-}" # TODO: For some reason vast ai exports all available udp ports and leaves none for identity port mapping.
export VAST_TCP_PORT_70002="${VAST_TCP_PORT_70002:-}"

# Clean up supervisor socket if it exists from previous run
# This ensures supervisord can create it fresh with correct permissions
if [ -S /var/run/supervisor.sock ]; then
    log "Removing existing supervisor socket to ensure correct permissions..."
    rm -f /var/run/supervisor.sock
fi

# Ensure socket directory exists and has correct permissions
mkdir -p /var/run
chmod 1777 /var/run

# Verify supervisor installation
if ! command -v supervisord >/dev/null 2>&1; then
    log "ERROR: supervisord not found in PATH"
    exit 1
fi

SUPERVISORD_PATH=$(which supervisord)
log "Supervisord found at: $SUPERVISORD_PATH"

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

exec "$SUPERVISORD_PATH" -c /etc/supervisor/conf.d/supervisord.conf -n

