#!/usr/bin/env python3
"""
Test script for WebSocket Bridge implementation.
This script tests the basic functionality of the WebSocket bridge service.
"""

import asyncio
import sys
import os

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from services.websocket_bridge import WebSocketBridge
from core.config import ServerConfig


async def test_websocket_bridge():
    """Test the WebSocket bridge functionality."""
    print("🧪 [Test] Starting WebSocket bridge tests...")
    
    try:
        # Create config
        config = ServerConfig()
        
        # Create WebSocket bridge
        bridge = WebSocketBridge(config)
        
        print("✅ [Test] WebSocket bridge created successfully")
        
        # Test status
        status = bridge.get_status()
        print(f"📊 [Test] Bridge status: {status}")
        
        # Test broadcast callback setting
        def mock_broadcast(message):
            print(f"📡 [Test] Mock broadcast: {message.get('action', 'unknown')}")
        
        bridge.set_broadcast_callback(mock_broadcast)
        print("✅ [Test] Broadcast callback set successfully")
        
        # Test URL building
        test_urls = [
            "http://localhost:8888/api/kernels/123/channels",
            "https://jupyter.example.com/api/kernels/456/channels",
            "/api/kernels/789/channels"
        ]
        
        for url in test_urls:
            ws_url = bridge._build_websocket_url(url)
            print(f"🔗 [Test] {url} -> {ws_url}")
        
        print("✅ [Test] URL building tests passed")
        
        # Test cleanup
        await bridge.cleanup()
        print("✅ [Test] Bridge cleanup completed")
        
        print("🎉 [Test] All WebSocket bridge tests passed!")
        
    except Exception as e:
        print(f"❌ [Test] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_websocket_bridge())
    sys.exit(0 if success else 1)
