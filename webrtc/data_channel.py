"""
Data channel management for WebRTC connections.
"""
import json
import datetime
from typing import Dict, Optional, Callable, Any

# Make aiortc import optional for testing
try:
    from aiortc import RTCDataChannel
    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False
    # Create mock class for testing
    class RTCDataChannel:
        def __init__(self):
            self.label = "mock-channel"
            self.ordered = True
            self.protocol = ""
            self.readyState = "open"
            self.bufferedAmount = 0
        
        def on(self, event):
            def decorator(func):
                return func
            return decorator
        
        def send(self, data):
            pass

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log


class DataChannelManager(LoggerMixin):
    """Manages WebRTC data channels and their lifecycle."""
    
    def __init__(self):
        super().__init__()
        self.data_channels: Dict[int, RTCDataChannel] = {}
        self.message_handlers: Dict[int, Callable] = {}
        self.close_handlers: Dict[int, Callable] = {}
    
    def add_channel(self, client_id: int, channel: RTCDataChannel, 
                   message_handler: Callable, close_handler: Callable):
        """Add a new data channel."""
        self.log_info(f"Adding data channel", {
            "client_id": client_id,
            "channel_label": channel.label,
            "total_channels": len(self.data_channels)
        })
        
        self.data_channels[client_id] = channel
        self.message_handlers[client_id] = message_handler
        self.close_handlers[client_id] = close_handler
        
        # Set up channel event handlers
        self._setup_channel_handlers(client_id, channel)
    
    def remove_channel(self, client_id: int):
        """Remove a data channel."""
        if client_id in self.data_channels:
            self.log_info(f"Removing data channel", {
                "client_id": client_id,
                "total_channels": len(self.data_channels)
            })
            
            del self.data_channels[client_id]
            del self.message_handlers[client_id]
            del self.close_handlers[client_id]
    
    def _setup_channel_handlers(self, client_id: int, channel: RTCDataChannel):
        """Set up event handlers for a data channel."""
        
        @channel.on("message")
        async def on_message(message):
            """Handle incoming messages on the data channel."""
            if client_id in self.message_handlers:
                handler = self.message_handlers[client_id]
                try:
                    result = handler(message, channel)
                    # If handler returns a coroutine, await it
                    import asyncio
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    self.log_error("Error handling data channel message", {
                        "client_id": client_id,
                        "error": str(e),
                        "error_type": type(e).__name__
                    })
        
        @channel.on("close")
        def on_close():
            """Handle data channel closure."""
            self.log_info(f"Data channel closed", {
                "client_id": client_id,
                "total_channels": len(self.data_channels)
            })
            
            if client_id in self.close_handlers:
                self.close_handlers[client_id]()
            
            self.remove_channel(client_id)
    
    def send_message(self, client_id: int, message: Dict[str, Any]) -> bool:
        """Send a message to a specific client."""
        if client_id not in self.data_channels:
            self.log_warning(f"Cannot send message: client not found", {
                "client_id": client_id,
                "available_clients": list(self.data_channels.keys())
            })
            return False
        
        try:
            channel = self.data_channels[client_id]
            message_str = json.dumps(message)
            
            debug_log(f"📤 [DataChannel] Sending message to client", {
                "client_id": client_id,
                "action": message.get('action'),
                "message_length": len(message_str),
                "timestamp": datetime.datetime.now().isoformat()
            })
            
            channel.send(message_str)
            return True
            
        except Exception as e:
            self.log_error(f"Failed to send message to client", {
                "client_id": client_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    def broadcast_message(self, message: Dict[str, Any], exclude_client_id: Optional[int] = None) -> int:
        """Broadcast a message to all clients except the excluded one."""
        sent_count = 0
        
        debug_log(f"📤 [DataChannel] Broadcasting message", {
            "action": message.get('action'),
            "exclude_client_id": exclude_client_id,
            "total_clients": len(self.data_channels),
            "message_keys": list(message.keys()),
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        for client_id, channel in self.data_channels.items():
            if client_id != exclude_client_id:
                if self.send_message(client_id, message):
                    sent_count += 1
        
        debug_log(f"📤 [DataChannel] Broadcast completed", {
            "sent_count": sent_count,
            "total_clients": len(self.data_channels)
        })
        
        return sent_count
    
    def get_channel_info(self, client_id: int) -> Optional[Dict[str, Any]]:
        """Get information about a specific data channel."""
        if client_id not in self.data_channels:
            return None
        
        channel = self.data_channels[client_id]
        return {
            "client_id": client_id,
            "label": channel.label,
            "ordered": channel.ordered,
            "protocol": channel.protocol,
            "ready_state": channel.readyState,
            "buffered_amount": channel.bufferedAmount
        }
    
    def get_all_channels_info(self) -> Dict[int, Dict[str, Any]]:
        """Get information about all data channels."""
        return {
            client_id: self.get_channel_info(client_id)
            for client_id in self.data_channels.keys()
        }
    
    def is_client_connected(self, client_id: int) -> bool:
        """Check if a client is connected."""
        return client_id in self.data_channels
    
    def get_connected_clients(self) -> list:
        """Get list of connected client IDs."""
        return list(self.data_channels.keys())
    
    def get_channel_count(self) -> int:
        """Get total number of data channels."""
        return len(self.data_channels)
