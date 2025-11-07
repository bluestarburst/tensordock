#!/bin/bash

# Quick script to show all relevant environment variables
# Run this inside the container: bash /app/show-env-vars.sh

echo "=== Environment Variables Debug ==="
echo ""

echo "Core Variables:"
echo "  USER_ID: ${USER_ID:-<not set>}"
echo "  INSTANCE_ID: ${INSTANCE_ID:-<not set>}"
echo "  RESOURCE_TYPE: ${RESOURCE_TYPE:-<not set>}"
echo "  FIREBASE_FUNCTIONS_URL: ${FIREBASE_FUNCTIONS_URL:-<not set>}"
echo "  MONITOR_API_KEY: ${MONITOR_API_KEY:+<set>} ${MONITOR_API_KEY:-<not set>}"
echo ""

echo "VastAI Port Mapping Variables (Identity Ports):"
echo "  VAST_TCP_PORT_70000 (Python server, internal: 8765): ${VAST_TCP_PORT_70000:-<not set>}"
echo "  VAST_UDP_PORT_70001 (TURN server, internal: 3478): ${VAST_UDP_PORT_70001:-<not set>}"
echo "  VAST_TCP_PORT_70002 (Jupyter, internal: 8888): ${VAST_TCP_PORT_70002:-<not set>}"
echo "  VAST_TCP_PORT_22 (SSH, internal: 22): ${VAST_TCP_PORT_22:-<not set>}"
echo ""

echo "Network Variables:"
echo "  PUBLIC_IPADDR: ${PUBLIC_IPADDR:-<not set>}"
echo ""

echo "Service Configuration:"
echo "  START_TURN: ${START_TURN:-<not set>}"
echo "  JUPYTER_TOKEN: ${JUPYTER_TOKEN:+<set>} ${JUPYTER_TOKEN:-<not set>}"
echo "  TURN_USERNAME: ${TURN_USERNAME:-<not set>}"
echo "  TURN_PASSWORD: ${TURN_PASSWORD:+<set>} ${TURN_PASSWORD:-<not set>}"
echo ""

echo "All VAST_* variables:"
env | grep "^VAST_" | sort || echo "  No VAST_* variables found"
echo ""

echo "To see ALL environment variables, run: env | sort"

