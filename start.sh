#!/bin/bash

# Supervisor handles all process management, but we still need to set up
# environment variables and directories for the processes

# Create logs directory on tmpfs (container mounts /tmp as tmpfs and is writable by non-root)
LOG_DIR="/tmp/tensordock-logs"
mkdir -p "$LOG_DIR"
export TD_LOG_DIR="$LOG_DIR"

# Writable config/cache/runtime directories on tmpfs for non-root user
export XDG_DATA_HOME="/tmp/.local/share"
export XDG_CONFIG_HOME="/tmp/.config"
export XDG_CACHE_HOME="/tmp/.cache"
export JUPYTER_RUNTIME_DIR="/tmp/jupyter-runtime"
export JUPYTER_DATA_DIR="/tmp/jupyter-data"
export JUPYTER_CONFIG_DIR="/tmp/jupyter-config"
mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" \
         "$JUPYTER_RUNTIME_DIR" "$JUPYTER_DATA_DIR" "$JUPYTER_CONFIG_DIR"

# Set up TURN server environment variables if needed
# These will be used by supervisor's turn_server program
if [ -z "$TURN_USERNAME" ]; then
  export TURN_USERNAME="user"
fi

if [ -z "$TURN_PASSWORD" ]; then
  # Generate a secure password if not provided
  export TURN_PASSWORD=$(openssl rand -base64 32 2>/dev/null || echo "password")
fi

if [ -z "$PUBLIC_IPADDR" ]; then
  export PUBLIC_IPADDR=""
fi

  # Auto-detect external IP when PUBLIC_IPADDR=auto
  if [ "${PUBLIC_IPADDR:-}" = "auto" ]; then
    # Try DigitalOcean metadata
    META_IP=$(curl -fsS --max-time 2 http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address || true)
    if [ -n "$META_IP" ]; then
    export PUBLIC_IPADDR="$META_IP"
    else
      # Fallback external service
    export PUBLIC_IPADDR=$(curl -fsS --max-time 3 https://ifconfig.co 2>/dev/null || true)
    fi
  fi

# Supervisor will handle starting all processes
# This script is kept for environment setup but supervisor is the main entry point
# If called directly (not via supervisor), start supervisor
# Note: supervisor is installed via pip, so it's in /usr/local/bin
if [ "$1" != "supervisor" ]; then
  exec /usr/local/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf -n
fi
