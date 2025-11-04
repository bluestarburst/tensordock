#!/usr/bin/env python3
"""
Simple launcher for the modular TensorDock server.
This script sets up the Python path correctly and runs the server.
"""
import sys
import os
import datetime
import tempfile

# Get the directory containing this script
script_dir = os.path.dirname(os.path.abspath(__file__))

# Determine log directory: prefer TD_LOG_DIR env, otherwise tmpfs fallback
log_dir_env = os.environ.get("TD_LOG_DIR")
if log_dir_env:
    logs_dir = log_dir_env
else:
    logs_dir = os.path.join(tempfile.gettempdir(), "tensordock-logs")

# Create logs directory if it doesn't exist
os.makedirs(logs_dir, exist_ok=True)

# Create a timestamped log file for this run
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(logs_dir, f"server_run_{timestamp}.log")

# Redirect stdout and stderr to the log file
class Logger:
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, 'a', encoding='utf-8')
    
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()
    
    def flush(self):
        self.terminal.flush()
        self.log.flush()

# Redirect stdout and stderr
sys.stdout = Logger(log_file)
sys.stderr = Logger(log_file)

# Add the script directory to Python path
sys.path.insert(0, script_dir)

# Now we can import our modules
try:
    from server_modular import main
    import asyncio

    print("🚀 Starting Modular TensorDock Server...")
    print("🔗 WebRTC Bridge: Ready for Jupyter communication")   
    print("🌐 HTTP Proxy: Integrated for API requests")   
    print("📡 WebSocket Bridge: Ready for kernel messages")   
    print("⚙️  Message Routing: Action processor configured")   
    print(f"📁 Working directory: {script_dir}")
    print(f"🐍 Python path: {sys.path[0]}")
    print(f"📝 All output will be logged to: {log_file}")

    # Run the server
    asyncio.run(main())

except ImportError as e:
    print(f"❌ Import error: {e}")
    print("💡 Make sure you're running this from the tensordock directory")
    print("💡 Try: cd tensordock && python run_modular.py")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error starting server: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
