#!/bin/bash
# RunPod Template Startup Script
# This script is executed when the RunPod template starts
# It receives environment variables from RunPod and executes the startup script

set -e

# Log file
LOG_FILE="/tmp/runpod-template-start.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== RunPod Template Startup at $(date) ==="
echo "Template version: 1.0"
echo "RunPod Pod ID: ${RUNPOD_POD_ID:-not-set}"

# Check if STARTUP_SCRIPT environment variable is provided
if [ -z "$STARTUP_SCRIPT" ]; then
    echo "ERROR: STARTUP_SCRIPT environment variable not provided"
    echo ""
    echo "Available environment variables:"
    env | grep -E "(USER_ID|RESOURCE_TYPE|FIREBASE_CREDENTIALS|START_TURN|JUPYTER_TOKEN|CONTROL_PLANE_IMAGE|USER_CONTAINER_IMAGE|STARTUP_SCRIPT)" || true
    echo ""
    echo "This template requires STARTUP_SCRIPT to be passed by the RunPod provider."
    exit 1
fi

# Write the startup script to a file
STARTUP_SCRIPT_FILE="/tmp/tensordock-startup.sh"
echo "$STARTUP_SCRIPT" > "$STARTUP_SCRIPT_FILE"
chmod +x "$STARTUP_SCRIPT_FILE"

echo "TensorDock startup script received"
echo "Script length: $(wc -c < "$STARTUP_SCRIPT_FILE") bytes"
echo "Script preview (first 500 chars):"
head -c 500 "$STARTUP_SCRIPT_FILE"
echo ""
echo ""

echo "Executing TensorDock startup script..."
echo "---"

# Execute the startup script (don't use exec, so we can log completion)
"$STARTUP_SCRIPT_FILE"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "---"
    echo "TensorDock startup script completed successfully"
else
    echo "---"
    echo "ERROR: TensorDock startup script failed with exit code $EXIT_CODE"
    exit $EXIT_CODE
fi

