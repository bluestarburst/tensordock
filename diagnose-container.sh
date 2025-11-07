#!/bin/bash

# Diagnostic script for unified container
# Run this inside the container to diagnose issues

echo "=== Container Diagnostics ==="
echo ""

echo "1. Supervisord process:"
if ps aux | grep -E "[s]upervisord" > /dev/null; then
    echo "  ✅ Supervisord is running"
    ps aux | grep -E "[s]upervisord"
else
    echo "  ❌ Supervisord is NOT running"
fi
echo ""

echo "2. Supervisor socket:"
if [ -S /var/run/supervisor.sock ]; then
    echo "  ✅ Socket exists"
    ls -la /var/run/supervisor.sock
else
    echo "  ❌ Socket not found at /var/run/supervisor.sock"
fi
echo ""

echo "3. Supervisor PID file:"
if [ -f /var/run/supervisord.pid ]; then
    echo "  ✅ PID file exists"
    cat /var/run/supervisord.pid
    echo "  PID file contents: $(cat /var/run/supervisord.pid)"
else
    echo "  ❌ PID file not found"
fi
echo ""

echo "4. Log directory:"
if [ -d /var/log/supervisor ]; then
    echo "  ✅ Log directory exists"
    ls -la /var/log/supervisor/
    if [ "$(ls -A /var/log/supervisor)" ]; then
        echo "  ✅ Log directory has files"
    else
        echo "  ⚠️  Log directory is empty"
    fi
else
    echo "  ❌ Log directory missing"
fi
echo ""

echo "5. Supervisor config:"
if [ -f /etc/supervisor/conf.d/supervisord.conf ]; then
    echo "  ✅ Config file exists"
    # Validate config
    if /usr/local/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf -t 2>&1; then
        echo "  ✅ Config file is valid"
    else
        echo "  ❌ Config file has errors (see above)"
    fi
else
    echo "  ❌ Config file missing"
fi
echo ""

echo "6. Environment variables:"
echo "  === Core Variables ==="
echo "  USER_ID: ${USER_ID:-<not set>}"
echo "  INSTANCE_ID: ${INSTANCE_ID:-<not set>}"
echo "  RESOURCE_TYPE: ${RESOURCE_TYPE:-<not set>}"
echo "  MONITOR_API_KEY: ${MONITOR_API_KEY:+<set (hidden)>} ${MONITOR_API_KEY:-<not set>}"
echo "  FIREBASE_FUNCTIONS_URL: ${FIREBASE_FUNCTIONS_URL:-<not set>}"
echo ""
echo "  === Port Mapping Variables (VastAI Identity Ports) ==="
echo "  VAST_TCP_PORT_70000 (Python server): ${VAST_TCP_PORT_70000:-<not set>}"
echo "  VAST_UDP_PORT_70001 (TURN server): ${VAST_UDP_PORT_70001:-<not set>}"
echo "  VAST_TCP_PORT_70002 (Jupyter): ${VAST_TCP_PORT_70002:-<not set>}"
echo "  VAST_TCP_PORT_22 (SSH): ${VAST_TCP_PORT_22:-<not set>}"
echo ""
echo "  === Network Variables ==="
echo "  PUBLIC_IPADDR: ${PUBLIC_IPADDR:-<not set>}"
echo ""
echo "  === Service Configuration ==="
echo "  START_TURN: ${START_TURN:-<not set>}"
echo "  JUPYTER_TOKEN: ${JUPYTER_TOKEN:+<set>} ${JUPYTER_TOKEN:-<not set>}"
echo "  TURN_USERNAME: ${TURN_USERNAME:-<not set>}"
echo "  TURN_PASSWORD: ${TURN_PASSWORD:+<set (hidden)>} ${TURN_PASSWORD:-<not set>}"
echo ""
echo "  === All Environment Variables (filtered) ==="
echo "  (Showing only relevant variables, use 'env | grep VAST' for all port vars)"
env | grep -E "^(USER_ID|INSTANCE_ID|RESOURCE_TYPE|MONITOR_API_KEY|FIREBASE_FUNCTIONS_URL|VAST_|PUBLIC_IPADDR|START_TURN|JUPYTER_TOKEN|TURN_)" | sort
echo ""

echo "7. PID 1 process (container entrypoint):"
ps aux | head -2
echo ""

echo "8. All Python processes:"
ps aux | grep python | grep -v grep || echo "  No Python processes found"
echo ""

echo "9. All supervisor-related processes:"
ps aux | grep -E "(supervisor|jupyter|turnserver|monitor)" | grep -v grep || echo "  No supervisor processes found"
echo ""

echo "10. Supervisor binary location:"
if command -v supervisord >/dev/null 2>&1; then
    echo "  ✅ Found at: $(which supervisord)"
else
    echo "  ❌ supervisord not found in PATH"
    echo "  Searching for supervisord..."
    find /usr -name supervisord 2>/dev/null || echo "  Not found"
fi
echo ""

echo "=== Recommendations ==="
echo ""
if ! ps aux | grep -E "[s]upervisord" > /dev/null; then
    echo "❌ Supervisord is not running. Try:"
    echo "  1. Check Docker logs: docker logs <container_name>"
    echo "  2. Try starting manually: /usr/local/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf -n"
    echo "  3. Check for errors in the output above"
fi

