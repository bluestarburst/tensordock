#!/bin/bash

# Script to view TensorDock server logs
LOGS_DIR="logs"

if [ ! -d "$LOGS_DIR" ]; then
    echo "❌ Logs directory not found. Run the server first to generate logs."
    exit 1
fi

echo "📁 Available log files in $LOGS_DIR:"
echo ""

# List all log files with timestamps
for log_file in "$LOGS_DIR"/*.log; do
    if [ -f "$log_file" ]; then
        filename=$(basename "$log_file")
        size=$(du -h "$log_file" | cut -f1)
        modified=$(stat -f "%Sm" "$log_file" 2>/dev/null || stat -c "%y" "$log_file" 2>/dev/null)
        echo "📄 $filename ($size, modified: $modified)"
    fi
done

echo ""
echo "🔍 To view a specific log file, use:"
echo "   tail -f logs/tensordock_server.log    # View server logs in real-time"
echo "   tail -f logs/server_YYYYMMDD_HHMMSS.log  # View specific server run"
echo "   tail -f logs/jupyter_YYYYMMDD_HHMMSS.log  # View specific jupyter run"
echo ""
echo "📊 To view the latest server log:"
echo "   tail -n 50 logs/tensordock_server.log"
echo ""
echo "🔄 To follow logs in real-time:"
echo "   tail -f logs/tensordock_server.log"
