#!/usr/bin/env python3
"""
Simple launcher for the modular TensorDock server.
This script sets up the Python path correctly and runs the server.
"""
import sys
import os

# Get the directory containing this script
script_dir = os.path.dirname(os.path.abspath(__file__))

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
