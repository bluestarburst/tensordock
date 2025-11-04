#!/bin/bash

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

# Create timestamped log files with absolute paths
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
JUPYTER_LOG="$LOG_DIR/jupyter_${TIMESTAMP}.log"
SERVER_LOG="$LOG_DIR/server_${TIMESTAMP}.log"

# Try to start TURN server if available; log to app logs (not /var/log)
START_TURN="${START_TURN:-true}"
TURN_BINARY="${TURN_BINARY:-turnserver}"

if [ "$START_TURN" = "true" ]; then
  if ! command -v "$TURN_BINARY" >/dev/null 2>&1; then
    if [ -x /usr/bin/turnserver ]; then
      TURN_BINARY=/usr/bin/turnserver
    elif [ -x /usr/sbin/turnserver ]; then
      TURN_BINARY=/usr/sbin/turnserver
    fi
  fi
fi

if [ "$START_TURN" = "true" ] && command -v "$TURN_BINARY" >/dev/null 2>&1; then
  TURN_PORT="${TURN_PORT:-3478}"
  TURN_REALM="${TURN_REALM:-example.org}"
  TURN_USER="${TURN_USERNAME:-user}"
  TURN_PASS="${TURN_PASSWORD:-password}"
  TURN_LISTEN_IP="${TURN_LISTEN_IP:-0.0.0.0}"
  TURN_MIN_PORT="${TURN_MIN_PORT:-49152}"
  TURN_MAX_PORT="${TURN_MAX_PORT:-65535}"
  TURN_EXTERNAL_IP="${PUBLIC_IPADDR:-}"
  TURN_DB_PATH="${TURN_DB_PATH:-/tmp/turnserver.sqlite}"

  # Auto-detect external IP when PUBLIC_IPADDR=auto
  if [ "${PUBLIC_IPADDR:-}" = "auto" ]; then
    # Try DigitalOcean metadata
    META_IP=$(curl -fsS --max-time 2 http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address || true)
    if [ -n "$META_IP" ]; then
      TURN_EXTERNAL_IP="$META_IP"
    else
      # Fallback external service
      TURN_EXTERNAL_IP=$(curl -fsS --max-time 3 https://ifconfig.co 2>/dev/null || true)
    fi
  fi

  CMD=("$TURN_BINARY" -n -a --log-file=stdout --lt-cred-mech --fingerprint \
       --no-multicast-peers --no-cli --no-tlsv1 --no-tlsv1_1 \
       --realm="$TURN_REALM" --user="$TURN_USER:$TURN_PASS" \
       --listening-port="$TURN_PORT" --listening-ip="$TURN_LISTEN_IP" \
       --min-port="$TURN_MIN_PORT" --max-port="$TURN_MAX_PORT" \
       --userdb="$TURN_DB_PATH")
  if [ -n "$TURN_EXTERNAL_IP" ]; then
    CMD+=(--external-ip="$TURN_EXTERNAL_IP")
    export TURN_ADDRESS="${TURN_EXTERNAL_IP}:${TURN_PORT}?transport=udp"
  else
    export TURN_ADDRESS="${TURN_LISTEN_IP}:${TURN_PORT}?transport=udp"
  fi
  export VAST_UDP_PORT_70001="$TURN_PORT"
  export VAST_TCP_PORT_70000="${TURN_VAST_TCP_PORT:-8765}"
  echo "[INFO] Starting coturn on $TURN_LISTEN_IP:$TURN_PORT realm=$TURN_REALM min=$TURN_MIN_PORT max=$TURN_MAX_PORT external=$TURN_EXTERNAL_IP" \
    | tee -a "$LOG_DIR/coturn_${TIMESTAMP}.log"
  "${CMD[@]}" 2>&1 | tee -a "$LOG_DIR/coturn_${TIMESTAMP}.log" &
else
  echo "[WARN] turnserver binary not found or START_TURN=false; skipping TURN startup" | tee -a "$LOG_DIR/coturn_${TIMESTAMP}.log"
fi


# Start Jupyter Server in the background at port 8888 with logging (also stream to docker logs)
JUPYTER_TOKEN="${JUPYTER_TOKEN:-test}"
jupyter server --port=8888 --IdentityProvider.token="$JUPYTER_TOKEN" 2>&1 | tee -a "$JUPYTER_LOG" &

# Start the main server with logging (stream to docker logs)
python -u run_modular.py 2>&1 | tee -a "$SERVER_LOG"