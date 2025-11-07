#!/bin/bash

# Script to view supervisor logs in the unified container
# Usage: ./view-supervisor-logs.sh [program_name] [options]

LOG_DIR="/var/log/supervisor"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# List all log files
list_logs() {
    echo -e "${GREEN}📁 Log files in $LOG_DIR:${NC}"
    echo ""
    ls -lh "$LOG_DIR" 2>/dev/null || echo "Log directory not found or not accessible"
}

# Check process status
show_status() {
    echo -e "${GREEN}📊 Supervisor Process Status:${NC}"
    echo ""
    if command -v supervisorctl >/dev/null 2>&1; then
        # Must specify config file to use Unix socket instead of HTTP
        supervisorctl -c /etc/supervisor/conf.d/supervisord.conf status
    else
        echo "supervisorctl not found. Checking processes manually..."
        ps aux | grep -E "(jupyter|python.*run_modular|turnserver|monitor_service|sshd)" | grep -v grep
    fi
}

# View specific log
view_log() {
    local program=$1
    local log_file="$LOG_DIR/${program}.log"
    
    if [ ! -f "$log_file" ]; then
        echo -e "${YELLOW}⚠️  Log file not found: $log_file${NC}"
        echo "Available log files:"
        ls -lh "$LOG_DIR"/*.log 2>/dev/null | awk '{print $9}' | xargs -n1 basename
        return 1
    fi
    
    echo -e "${GREEN}📄 Viewing log: $log_file${NC}"
    echo ""
    
    if [ "$2" = "-f" ] || [ "$2" = "--follow" ]; then
        tail -f "$log_file"
    else
        tail -n 100 "$log_file"
    fi
}

# Main script
if [ $# -eq 0 ]; then
    # No arguments - show status and list logs
    show_status
    echo ""
    list_logs
    echo ""
    echo -e "${BLUE}Usage:${NC}"
    echo "  $0 status                    # Show process status"
    echo "  $0 logs                      # List all log files"
    echo "  $0 <program>                 # View last 100 lines of program log"
    echo "  $0 <program> -f              # Follow program log (real-time)"
    echo ""
    echo -e "${BLUE}Available programs:${NC}"
    echo "  jupyter, python_server, turn_server, monitor, ssh, supervisord"
    echo ""
    echo -e "${BLUE}Examples:${NC}"
    echo "  $0 monitor -f                # Follow monitor service logs"
    echo "  $0 jupyter                   # View last 100 lines of Jupyter log"
    echo "  $0 python_server -f          # Follow Python server logs"
    echo ""
    echo -e "${YELLOW}Note:${NC} If supervisorctl fails, use direct log files:"
    echo "  tail -f /var/log/supervisor/monitor.log"
elif [ "$1" = "status" ]; then
    show_status
elif [ "$1" = "logs" ]; then
    list_logs
else
    view_log "$1" "$2"
fi
