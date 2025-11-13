#!/bin/bash
# DigitalOcean Docker Startup Script for TensorDock
# This script runs on a DigitalOcean droplet with Docker pre-installed (Docker 1-Click App)
# It pulls the TensorDock Docker image and runs it with proper configuration
# Expected startup time: 30-60 seconds (vs 5-10 minutes with full installation)

set -o pipefail
LOG_FILE="/var/log/tensordock-docker-setup.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== TensorDock Docker Setup Started at $(date) ==="

# Default values if not set
DOCKER_IMAGE="${DOCKER_IMAGE:-bluestarburst/tensordock-do:latest}"
TURN_USERNAME="${TURN_USERNAME:-user}"
PUBLIC_IPADDR="${PUBLIC_IPADDR:-auto}"
PYTHON_PORT="${PYTHON_PORT:-8765}"
TURN_PORT="${TURN_PORT:-50000}"
JUPYTER_PORT="${JUPYTER_PORT:-8888}"
CONTAINER_NAME="tensordock-container"

# Logging function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

log "Starting TensorDock Docker container setup"

# Wait for Docker to be ready
log "Waiting for Docker to be ready..."
MAX_ATTEMPTS=30
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if docker info >/dev/null 2>&1; then
        log "Docker is ready"
        break
    fi
    log "Waiting for Docker... attempt $((ATTEMPT + 1))/$MAX_ATTEMPTS"
    sleep 2
    ATTEMPT=$((ATTEMPT + 1))
done

if ! docker info >/dev/null 2>&1; then
    log "ERROR: Docker is not available"
    exit 1
fi

# Stop and remove existing container if it exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log "Stopping and removing existing container..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
fi

# Set up TURN server environment variables if needed
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

# Export port mappings for DigitalOcean (no VAST_* variables, use direct ports)
export VAST_TCP_PORT_70000="${VAST_TCP_PORT_70000:-$PYTHON_PORT}"
export VAST_UDP_PORT_70001="${VAST_UDP_PORT_70001:-$TURN_PORT}"
export VAST_TCP_PORT_70002="${VAST_TCP_PORT_70002:-$JUPYTER_PORT}"

# Pull Docker image
log "Pulling Docker image: $DOCKER_IMAGE"
if ! docker pull "$DOCKER_IMAGE"; then
    log "ERROR: Failed to pull Docker image: $DOCKER_IMAGE"
    exit 1
fi

# Configure firewall FIRST, before starting container
# This ensures ports are open before the container tries to bind to them
if command -v ufw >/dev/null 2>&1; then
    log "Configuring firewall rules to expose ports..."
    
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
    log "Firewall status:"
    ufw status verbose
else
    log "WARNING: ufw not found, ports may not be exposed. Consider configuring DigitalOcean Cloud Firewall via API."
fi

# Run Docker container
log "Starting Docker container: $CONTAINER_NAME"
log "Port mappings:"
log "  Python server: $PYTHON_PORT/tcp"
log "  Jupyter: $JUPYTER_PORT/tcp"
log "  TURN server: $TURN_PORT/udp"

docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p "${PYTHON_PORT}:8765/tcp" \
    -p "${JUPYTER_PORT}:8888/tcp" \
    -p "${TURN_PORT}:50000/udp" \
    -e USER_ID="${USER_ID:-}" \
    -e INSTANCE_ID="${INSTANCE_ID:-}" \
    -e RESOURCE_TYPE="${RESOURCE_TYPE:-}" \
    -e START_TURN="${START_TURN:-true}" \
    -e MONITOR_API_KEY="${MONITOR_API_KEY:-}" \
    -e FIREBASE_FUNCTIONS_URL="${FIREBASE_FUNCTIONS_URL:-}" \
    -e JUPYTER_TOKEN="${JUPYTER_TOKEN:-}" \
    -e TURN_USERNAME="${TURN_USERNAME:-user}" \
    -e TURN_PASSWORD="${TURN_PASSWORD:-}" \
    -e PUBLIC_IPADDR="${PUBLIC_IPADDR:-}" \
    -e PYTHON_PORT="${PYTHON_PORT:-8765}" \
    -e TURN_PORT="${TURN_PORT:-50000}" \
    -e JUPYTER_PORT="${JUPYTER_PORT:-8888}" \
    -e VAST_TCP_PORT_70000="${VAST_TCP_PORT_70000:-$PYTHON_PORT}" \
    -e VAST_UDP_PORT_70001="${VAST_UDP_PORT_70001:-$TURN_PORT}" \
    -e VAST_TCP_PORT_70002="${VAST_TCP_PORT_70002:-$JUPYTER_PORT}" \
    -e GITHUB_REPO="${GITHUB_REPO:-}" \
    -e GITHUB_BRANCH="${GITHUB_BRANCH:-main}" \
    "$DOCKER_IMAGE" || {
    log "ERROR: Failed to start Docker container"
    exit 1
}

# Wait a moment for container to start
sleep 2

# Verify container is running
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log "✅ Docker container is running"
    log "Container status:"
    docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
else
    log "ERROR: Docker container failed to start"
    log "Container logs:"
    docker logs "$CONTAINER_NAME" 2>&1 | tail -50 || true
    exit 1
fi

log "=== TensorDock Docker Setup Completed at $(date) ==="
log "Container is running. Check logs with: docker logs $CONTAINER_NAME"

# Explicitly exit with success code to ensure cloud-init reports success
exit 0

