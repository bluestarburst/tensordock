"""
Main entry point for the tensordock module.
Run with: python -m tensordock
"""
import asyncio
import sys
import os

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Import and run the modular server
from server_modular import main

if __name__ == "__main__":
    asyncio.run(main())
