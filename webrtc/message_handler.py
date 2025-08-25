"""
WebRTC message handling and routing.
"""
import json
import datetime
from typing import Any, Dict, Callable, Set

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
            self.readyState = "open"

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log


class WebRTCMessageHandler(LoggerMixin):
    """Handles incoming WebRTC messages and routes them to appropriate handlers."""
    
    def __init__(self):
        super().__init__()
        self.action_listeners: Dict[str, Set[Callable]] = {}
        self.client_id: int = None
    
    def set_client_id(self, client_id: int):
        """Set the client ID for this message handler."""
        self.client_id = client_id
    
    def add_listener(self, action: str, callback: Callable):
        """Add a listener for a specific action."""
        if action not in self.action_listeners:
            self.action_listeners[action] = set()
        self.action_listeners[action].add(callback)
    
    def remove_listener(self, action: str, callback: Callable):
        """Remove a listener for a specific action."""
        if action in self.action_listeners:
            self.action_listeners[action].discard(callback)
    
    def handle_message(self, message: str, data_channel: RTCDataChannel):
        """Handle incoming WebRTC message."""
        try:
            debug_log(f"🔵 [WebRTC] Message received from client {self.client_id}", {
                "message_length": len(message) if hasattr(message, '__len__') else 'unknown',
                "message_type": type(message).__name__,
                "timestamp": datetime.datetime.now().isoformat()
            })
            
            data = json.loads(message)
            
            debug_log(f"🔵 [WebRTC] Parsed message data", {
                "action": data.get('action'),
                "client_id": self.client_id,
                "message_keys": list(data.keys()),
                "timestamp": datetime.datetime.now().isoformat()
            })
            
            # Route message to appropriate handler
            action = data.get('action')
            if action:
                self._route_message(action, data, data_channel)
            else:
                self.log_warning(f"Message missing action field", data)
                
        except json.JSONDecodeError as e:
            self.log_error(f"Failed to parse message as JSON", {
                "error": str(e),
                "message": message[:200] if hasattr(message, '__len__') else str(message)[:200]
            })
        except Exception as e:
            self.log_error(f"Error handling message", {
                "error": str(e),
                "error_type": type(e).__name__,
                "message": message[:200] if hasattr(message, '__len__') else str(message)[:200]
            })
    
    def _route_message(self, action: str, data: Dict[str, Any], data_channel: RTCDataChannel):
        """Route message to appropriate handler based on action."""
        
        # Find exact match first
        listeners = self.action_listeners.get(action)
        
        # If no exact match and it's an HTTP response, try pattern matching
        if not listeners and action.startswith('http_response_'):
            for action_key, action_listeners in self.action_listeners.items():
                if action_key == 'sudo_http_response' or action_key == action:
                    listeners = action_listeners
                    break
        
        if listeners:
            self._call_listeners(action, data, listeners)
        else:
            self.log_warning(f"No listeners found for action", {
                "action": action,
                "available_actions": list(self.action_listeners.keys())
            })
    
    def _call_listeners(self, action: str, data: Dict[str, Any], listeners: Set[Callable]):
        """Call all listeners for an action with processed message data."""
        
        # Process message data based on action type
        if action == 'kernel':
            message_data = self._process_kernel_message(data)
        elif action == 'kernel_message':
            # Handle kernel_message action specifically
            message_data = data
            debug_log(f"🔵 [WebRTC] Kernel message received", {
                "action": action,
                "has_data": 'data' in data,
                "message_keys": list(data.keys())
            })
        elif action == 'events':
            message_data = data.get('data')
        elif action == 'sudo_http_request':
            # CRITICAL: For HTTP requests, preserve the full message structure
            # Don't extract just the 'data' field, keep url, method, headers, msgId
            message_data = data
            debug_log(f"🔵 [WebRTC] HTTP request - preserving full message structure", {
                "action": action,
                "has_url": 'url' in data,
                "has_method": 'method' in data,
                "has_headers": 'headers' in data,
                "has_msgId": 'msgId' in data,
                "has_data": 'data' in data,
                "message_keys": list(data.keys())
            })
        elif action == 'canvas_data':
            # Reduce logging for canvas data (mouse movements)
            message_data = data
            # Only log every 100th canvas message to reduce spam
            if not hasattr(self, '_canvas_log_counter'):
                self._canvas_log_counter = 0
            self._canvas_log_counter += 1
            if self._canvas_log_counter % 100 == 0:
                debug_log(f"🎨 [WebRTC] Canvas data (logged every 100th)", {
                    "action": action,
                    "count": self._canvas_log_counter,
                    "message_keys": list(data.keys())
                })
        elif data.get('data'):
            message_data = data['data']
        else:
            # Messages without data property (like execution_complete)
            message_data = {k: v for k, v in data.items() if k != 'action'}
        
        # Add client_id to message data for action processing
        if hasattr(self, 'client_id') and self.client_id is not None:
            message_data['client_id'] = self.client_id
        
        debug_log(f"🔵 [WebRTC] Calling listeners for action", {
            "action": action,
            "listener_count": len(listeners),
            "message_data": message_data,
            "client_id": getattr(self, 'client_id', None)
        })
        
        # Call all listeners
        for callback in listeners:
            try:
                callback(message_data)
            except Exception as e:
                self.log_error(f"Error in listener callback", {
                    "action": action,
                    "error": str(e),
                    "error_type": type(e).__name__
                })
    
    def _process_kernel_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process kernel message data."""
        try:
            kernel_data = data.get('data')
            if isinstance(kernel_data, str):
                message_data = json.loads(kernel_data)
                debug_log(f"🔵 [WebRTC] Kernel message parsed", {
                    "msg_type": message_data.get('header', {}).get('msg_type'),
                    "msg_id": message_data.get('header', {}).get('msg_id'),
                    "parent_header": message_data.get('parent_header'),
                    "content": message_data.get('content'),
                    "metadata": message_data.get('metadata'),
                    "buffers": message_data.get('buffers')
                })
                return message_data
            else:
                return kernel_data
        except Exception as e:
            self.log_error(f"Error parsing kernel message", {
                "error": str(e),
                "data": data
            })
            raise
    
    def get_available_actions(self) -> list:
        """Get list of available actions."""
        return list(self.action_listeners.keys())
    
    def get_listener_count(self, action: str) -> int:
        """Get number of listeners for an action."""
        return len(self.action_listeners.get(action, set()))
