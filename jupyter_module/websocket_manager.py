"""
WebSocket management for Jupyter integration.
Handles WebSocket connections, message processing, and reconnection logic.
"""

import asyncio
import json
import datetime
from typing import Optional, Dict, Any, Callable, List
from websockets.client import connect

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log
from core.config import ServerConfig


class WebSocketManager(LoggerMixin):
    """Manages WebSocket connections to Jupyter server."""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.kernel_ws = None
        self.event_ws = None
        
        # Connection state
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5  # seconds
        
        # Message handling
        self.message_handlers: Dict[str, Callable] = {}
        self.message_queue = asyncio.Queue()
        self.response_queue = asyncio.Queue()
        
        # Task management
        self.message_consumer_task = None
        self.response_consumer_task = None
        self.ping_task = None
        self.reconnect_task = None
        
        # WebRTC broadcast callback for sending messages to frontend
        self.broadcast_callback = None
        
        # Message processing state
        self.processing_messages = False
    
    async def connect(self, ws_url: str, extra_headers: Dict[str, str] = None) -> bool:
        """Connect to a WebSocket URL."""
        try:
            debug_log(f"🔌 [WebSocket] Connecting to WebSocket", {
                "ws_url": ws_url,
                "has_headers": bool(extra_headers)
            })
            print(f"🔌 [WebSocket] Connecting to: {ws_url}")
            
            # Create WebSocket connection
            self.kernel_ws = await connect(
                ws_url,
                extra_headers=extra_headers or {},
                ping_interval=None,  # We'll handle pings manually
                ping_timeout=None
            )
            
            self.connected = True
            self.reconnect_attempts = 0
            
            debug_log(f"✅ [WebSocket] Connected successfully")
            print(f"✅ [WebSocket] Connected successfully")
            
            # Start message processing tasks
            self.message_consumer_task = asyncio.create_task(self._message_consumer())
            self.response_consumer_task = asyncio.create_task(self._response_consumer())
            self.ping_task = asyncio.create_task(self._ping_loop())
            
            return True
            
        except Exception as e:
            debug_log(f"❌ [WebSocket] Connection failed", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            print(f"❌ [WebSocket] Connection failed: {e}")
            self.connected = False
            return False
    
    async def _message_consumer(self):
        """Process messages from the message queue."""
        self.processing_messages = True
        
        while self.processing_messages and self.connected:
            try:
                # Get message from queue
                message = await self.message_queue.get()
                
                if message is None:  # Shutdown signal
                    break
                
                # Process the message
                await self._handle_message(message)
                self.message_queue.task_done()
                
            except asyncio.CancelledError:
                debug_log(f"📥 [WebSocket] Message consumer cancelled")
                print(f"📥 [WebSocket] Message consumer cancelled")
                break
            except Exception as e:
                debug_log(f"❌ [WebSocket] Error in message consumer", {
                    "error": str(e),
                    "error_type": type(e).__name__
                })
                print(f"❌ [WebSocket] Error in message consumer: {e}")
                # Don't break the loop on individual message errors
                if self.message_queue.qsize() > 0:
                    self.message_queue.task_done()
        
        self.processing_messages = False
        debug_log(f"📥 [WebSocket] Message consumer stopped")
        print(f"📥 [WebSocket] Message consumer stopped")
    
    async def _response_consumer(self):
        """Process messages from the response queue and send them to the frontend via WebRTC."""
        debug_log(f"📤 [WebSocket] Response consumer started")
        print(f"📤 [WebSocket] Response consumer started")
        
        while self.connected:
            try:
                # Get message from response queue
                message = await self.response_queue.get()
                
                if message is None:  # Shutdown signal
                    break
                
                debug_log(f"📤 [WebSocket] Processing message from response queue", {
                    "message_type": type(message).__name__,
                    "has_header": bool(message.get('header')),
                    "header_keys": list(message.get('header', {}).keys()) if message.get('header') else [],
                    "message_keys": list(message.keys()) if isinstance(message, dict) else []
                })
                print(f"📤 [WebSocket] Processing message from response queue: {type(message).__name__}")
                
                # CRITICAL: Send kernel message back to frontend via WebRTC
                await self._send_kernel_message_to_frontend(message)
                
                self.response_queue.task_done()
                
            except asyncio.CancelledError:
                debug_log(f"📤 [WebSocket] Response consumer cancelled")
                print(f"📤 [WebSocket] Response consumer cancelled")
                break
            except Exception as e:
                debug_log(f"❌ [WebSocket] Error in response consumer", {
                    "error": str(e),
                    "error_type": type(e).__name__
                })
                print(f"❌ [WebSocket] Error in response consumer: {e}")
                # Don't break the loop on individual message errors
                if self.response_queue.qsize() > 0:
                    self.response_queue.task_done()
        
        debug_log(f"📤 [WebSocket] Response consumer stopped")
        print(f"📤 [WebSocket] Response consumer stopped")
    
    async def _send_kernel_message_to_frontend(self, message: Dict[str, Any]):
        """Send a kernel message to the frontend via WebRTC."""
        try:
            # Extract message details for logging
            msg_type = message.get('header', {}).get('msg_type', 'unknown')
            msg_id = message.get('header', {}).get('msg_id', 'unknown')
            channel = message.get('channel', 'unknown')
            
            debug_log(f"📤 [WebSocket] Sending kernel message to frontend", {
                "msg_type": msg_type,
                "msg_id": msg_id,
                "channel": channel,
                "message_size": len(json.dumps(message))
            })
            print(f"📤 [WebSocket] Sending kernel message to frontend: {msg_type} (ID: {msg_id})")
            
            # CRITICAL: Send via WebRTC action system
            if hasattr(self, 'broadcast_callback') and self.broadcast_callback:
                # Create the WebRTC message structure
                webrtc_message = {
                    'action': 'kernel_message',
                    'data': message,
                    'msg_type': msg_type,
                    'msg_id': msg_id,
                    'channel': channel,
                    'timestamp': datetime.datetime.now().isoformat()
                }
                
                debug_log(f"📤 [WebSocket] WebRTC message structure", {
                    "action": webrtc_message['action'],
                    "has_data": bool(webrtc_message['data']),
                    "data_type": type(webrtc_message['data']).__name__,
                    "data_keys": list(webrtc_message['data'].keys()) if isinstance(webrtc_message['data'], dict) else [],
                    "webrtc_keys": list(webrtc_message.keys())
                })
                print(f"📤 [WebSocket] WebRTC message structure: action={webrtc_message['action']}, data_type={type(webrtc_message['data']).__name__}")
                
                await self.broadcast_callback(webrtc_message)
                
                debug_log(f"✅ [WebSocket] Kernel message sent to frontend via WebRTC", {
                    "msg_type": msg_type,
                    "msg_id": msg_id
                })
                print(f"✅ [WebSocket] Kernel message sent to frontend: {msg_type}")
            else:
                debug_log(f"⚠️ [WebSocket] No broadcast callback available for kernel message", {
                    "msg_type": msg_type,
                    "msg_id": msg_id
                })
                print(f"⚠️ [WebSocket] No broadcast callback available for kernel message: {msg_type}")
                
        except Exception as e:
            debug_log(f"❌ [WebSocket] Failed to send kernel message to frontend", {
                "error": str(e),
                "error_type": type(e).__name__,
                "msg_type": message.get('header', {}).get('msg_type', 'unknown')
            })
            print(f"❌ [WebSocket] Failed to send kernel message to frontend: {e}")
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message."""
        try:
            # Parse message
            msg = json.loads(message)
            msg_type = msg.get('header', {}).get('msg_type', 'unknown')
            msg_id = msg.get('header', {}).get('msg_id', 'unknown')
            
            debug_log(f"📥 [WebSocket] Message received", {
                "msg_type": msg_type,
                "msg_id": msg_id,
                "message_length": len(message)
            })
            
            print(f"📥 [WebSocket] Message received: {msg_type} (ID: {msg_id})")
            
            # CRITICAL: Handle kernel_info_reply to track status transitions
            if msg_type == 'kernel_info_reply':
                debug_log(f"🎯 [WebSocket] Kernel info reply received", {
                    "msg_id": msg_id,
                    "timestamp": datetime.datetime.now().isoformat()
                })
                print(f"🎯 [WebSocket] Kernel info reply received!")
                print(f"🎯 [WebSocket] Message ID: {msg_id}")
                
                # Store in response queue for processing
                await self.response_queue.put(msg)
                
            # CRITICAL: Handle status messages to track execution state
            elif msg_type == 'status':
                execution_state = msg.get('content', {}).get('execution_state', 'unknown')
                debug_log(f"📊 [WebSocket] Status message received", {
                    "execution_state": execution_state,
                    "msg_id": msg_id
                })
                print(f"📊 [WebSocket] Status message: execution_state = {execution_state}")
                
                # Store in response queue for processing
                await self.response_queue.put(msg)
                
            else:
                # Store other messages in response queue
                await self.response_queue.put(msg)
            
            # Call message handlers if registered
            if msg_type in self.message_handlers:
                try:
                    await self.message_handlers[msg_type](msg)
                except Exception as e:
                    debug_log(f"❌ [WebSocket] Error in message handler", {
                        "msg_type": msg_type,
                        "error": str(e)
                    })
                    print(f"❌ [WebSocket] Error in message handler for {msg_type}: {e}")
            
        except json.JSONDecodeError as e:
            debug_log(f"❌ [WebSocket] JSON decode error", {
                "error": str(e),
                "message_preview": message[:200]
            })
            print(f"❌ [WebSocket] JSON decode error: {e}")
        except Exception as e:
            debug_log(f"❌ [WebSocket] Message handling error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            print(f"❌ [WebSocket] Message handling error: {e}")
    
    async def _emit_status_update(self, status: str):
        """Emit a status update event."""
        try:
            debug_log(f"📊 [WebSocket] Emitting status update", {
                "status": status,
                "timestamp": datetime.datetime.now().isoformat()
            })
            print(f"📊 [WebSocket] Emitting status update: {status}")
            
            # Store in response queue for processing
            # Note: No fake kernel_status_update action - only real JupyterLab messages
            await self.response_queue.put({
                'status': status,
                'timestamp': datetime.datetime.now().isoformat()
            })
            
        except Exception as e:
            debug_log(f"❌ [WebSocket] Error emitting status update", {
                "error": str(e),
                "status": status
            })
            print(f"❌ [WebSocket] Error emitting status update: {e}")
    
    async def _process_message(self, message: str):
        """Process a single message."""
        try:
            # Parse JSON message
            msg = json.loads(message)
            
            # Extract message metadata
            msg_type = msg.get('header', {}).get('msg_type', 'unknown')
            msg_id = msg.get('header', {}).get('msg_id', 'unknown')
            parent_msg_id = msg.get('parent_header', {}).get('msg_id', 'none')
            
            debug_log(f"📥 [WebSocket] Message parsed", {
                "msg_type": msg_type,
                "msg_id": msg_id,
                "parent_msg_id": parent_msg_id,
                "content_keys": list(msg.get('content', {}).keys()) if msg.get('content') else [],
                "channel": msg.get('channel', 'unknown')
            })
            
            # Store in response queue for processing
            await self.response_queue.put(msg)
            
            # Call message handlers if registered
            if msg_type in self.message_handlers:
                try:
                    await self.message_handlers[msg_type](msg)
                except Exception as e:
                    debug_log(f"❌ [WebSocket] Message handler error", {
                        "msg_type": msg_type,
                        "error": str(e),
                        "error_type": type(e).__name__
                    })
            
        except json.JSONDecodeError as e:
            debug_log(f"❌ [WebSocket] JSON decode error", {
                "error": str(e),
                "message_preview": message[:200] + "..." if len(message) > 200 else message
            })
        except Exception as e:
            debug_log(f"❌ [WebSocket] Message processing error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _ping_loop(self):
        """Keep WebSocket connection alive with pings."""
        while self.connected and self.kernel_ws and self.kernel_ws.open:
            try:
                await self.kernel_ws.ping()
                await asyncio.sleep(10)  # Ping every 10 seconds
            except Exception as e:
                debug_log(f"❌ [WebSocket] Ping failed", {
                    "error": str(e),
                    "error_type": type(e).__name__
                })
                break
    
    async def listen_for_messages(self, message_callback: Callable = None):
        """Listen for incoming WebSocket messages."""
        if not self.kernel_ws:
            raise Exception("WebSocket not connected")
        
        debug_log(f"👂 [WebSocket] Starting message listener")
        
        try:
            while self.connected and self.kernel_ws and self.kernel_ws.open:
                try:
                    message = await self.kernel_ws.recv()
                    
                    debug_log(f"📡 [WebSocket] Raw message received", {
                        "message_type": type(message).__name__,
                        "message_length": len(message) if hasattr(message, '__len__') else 'unknown'
                    })
                    
                    # Filter out binary messages and control frames
                    if isinstance(message, bytes):
                        debug_log(f"📡 [WebSocket] Binary message received, skipping", {
                            "length": len(message)
                        })
                        continue
                    
                    # Only process text messages
                    if isinstance(message, str):
                        debug_log(f"📡 [WebSocket] Text message queued", {
                            "message_length": len(message),
                            "message_preview": message[:100] + "..." if len(message) > 100 else message
                        })
                        
                        # Add to message queue for processing
                        await self.message_queue.put(message)
                        
                        # Call callback if provided
                        if message_callback:
                            try:
                                await message_callback(message)
                            except Exception as e:
                                debug_log(f"❌ [WebSocket] Message callback error", {
                                    "error": str(e),
                                    "error_type": type(e).__name__
                                })
                    else:
                        debug_log(f"📡 [WebSocket] Non-text message received, skipping", {
                            "message_type": type(message).__name__
                        })
                        
                except Exception as e:
                    debug_log(f"❌ [WebSocket] Error receiving message", {
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "ws_status": "open" if self.kernel_ws and self.kernel_ws.open else "closed"
                    })
                    
                    # Check for connection close errors
                    if "1005" in str(e) or "closed" in str(e).lower():
                        debug_log(f"🔌 [WebSocket] Connection closed, will reconnect")
                        self.connected = False
                        break
                    elif "timeout" in str(e).lower():
                        debug_log(f"⏰ [WebSocket] Timeout, will reconnect")
                        self.connected = False
                        break
                    
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            debug_log(f"❌ [WebSocket] Fatal error in message listener", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            self.connected = False
        
        # Start reconnection if needed
        if not self.connected:
            await self._start_reconnection()
    
    async def _start_reconnection(self):
        """Start reconnection process."""
        if self.reconnect_task:
            self.reconnect_task.cancel()
        
        self.reconnect_task = asyncio.create_task(self._reconnect_loop())
    
    async def _reconnect_loop(self):
        """Attempt to reconnect to WebSocket."""
        while not self.connected and self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            
            debug_log(f"🔄 [WebSocket] Reconnection attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}")
            
            try:
                # Wait before attempting reconnection
                delay = min(self.reconnect_delay * self.reconnect_attempts, 30)
                await asyncio.sleep(delay)
                
                # Attempt reconnection (this would need the original connection parameters)
                debug_log(f"🔄 [WebSocket] Reconnection not implemented, stopping attempts")
                break
                
            except Exception as e:
                debug_log(f"❌ [WebSocket] Reconnection error", {
                    "attempt": self.reconnect_attempts,
                    "error": str(e),
                    "error_type": type(e).__name__
                })
        
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            debug_log(f"❌ [WebSocket] Max reconnection attempts reached")
    
    async def send_message(self, message: Dict[str, Any]) -> bool:
        """Send a message through the WebSocket."""
        if not self.connected or not self.kernel_ws:
            debug_log(f"❌ [WebSocket] Cannot send message, not connected")
            return False
        
        try:
            # CRITICAL FIX: Ensure message is properly formatted
            if isinstance(message, str):
                # If it's already a string, send it directly
                message_str = message
                debug_log(f"📤 [WebSocket] Sending string message directly", {
                    "message_length": len(message_str),
                    "message_preview": message_str[:100]
                })
                print(f"📤 [WebSocket] Sending string message directly: {message_str[:100]}...")
            else:
                # If it's a dict, convert to JSON string
                message_str = json.dumps(message)
                debug_log(f"📤 [WebSocket] Message sent", {
                    "msg_type": message.get('header', {}).get('msg_type', 'unknown'),
                    "msg_id": message.get('header', {}).get('msg_id', 'unknown'),
                    "message_length": len(message_str)
                })
                print(f"📤 [WebSocket] Message sent: {message.get('header', {}).get('msg_type', 'unknown')}")
            
            await self.kernel_ws.send(message_str)
            return True
            
        except Exception as e:
            debug_log(f"❌ [WebSocket] Failed to send message", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            print(f"❌ [WebSocket] Failed to send message: {e}")
            return False
    
    def add_message_handler(self, msg_type: str, handler: Callable):
        """Add a message handler for a specific message type."""
        self.message_handlers[msg_type] = handler
        
        debug_log(f"➕ [WebSocket] Message handler added", {
            "msg_type": msg_type,
            "total_handlers": len(self.message_handlers)
        })
    
    def remove_message_handler(self, msg_type: str):
        """Remove a message handler for a specific message type."""
        if msg_type in self.message_handlers:
            del self.message_handlers[msg_type]
            
            debug_log(f"➖ [WebSocket] Message handler removed", {
                "msg_type": msg_type,
                "total_handlers": len(self.message_handlers)
            })
    
    def get_status(self) -> Dict[str, Any]:
        """Get current WebSocket status."""
        return {
            'connected': self.connected,
            'reconnect_attempts': self.reconnect_attempts,
            'max_reconnect_attempts': self.max_reconnect_attempts,
            'processing_messages': self.processing_messages,
            'message_queue_size': self.message_queue.qsize(),
            'response_queue_size': self.response_queue.qsize(),
            'total_handlers': len(self.message_handlers)
        }
    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        # CRITICAL FIX: More robust connection checking
        if not self.kernel_ws:
            return False
        
        try:
            # Check if WebSocket is open and healthy
            if hasattr(self.kernel_ws, 'open'):
                return self.kernel_ws.open and self.connected
            else:
                # Fallback for different WebSocket implementations
                return self.connected
        except Exception as e:
            debug_log(f"⚠️ [WebSocket] Error checking connection status", {
                "error": str(e)
            })
            print(f"⚠️ [WebSocket] Error checking connection status: {e}")
            return False
    
    async def check_connection_health(self):
        """Check WebSocket connection health and reconnect if needed."""
        try:
            if not self.is_connected():
                debug_log(f"⚠️ [WebSocket] Connection unhealthy, attempting reconnection")
                print(f"⚠️ [WebSocket] Connection unhealthy, attempting reconnection")
                
                # Try to reconnect
                success = await self._reconnect()
                if success:
                    debug_log(f"✅ [WebSocket] Reconnection successful")
                    print(f"✅ [WebSocket] Reconnection successful")
                else:
                    debug_log(f"❌ [WebSocket] Reconnection failed")
                    print(f"❌ [WebSocket] Reconnection failed")
                    
        except Exception as e:
            debug_log(f"❌ [WebSocket] Error in connection health check", {
                "error": str(e)
            })
            print(f"❌ [WebSocket] Error in connection health check: {e}")
    
    async def disconnect(self):
        """Disconnect the WebSocket."""
        debug_log(f"🔌 [WebSocket] Disconnecting WebSocket")
        
        self.connected = False
        self.processing_messages = False
        
        # Cancel tasks
        if self.message_consumer_task:
            self.message_consumer_task.cancel()
        
        if self.response_consumer_task:
            self.response_consumer_task.cancel()
        
        if self.ping_task:
            self.ping_task.cancel()
        
        if self.reconnect_task:
            self.reconnect_task.cancel()
        
        # Close WebSocket
        if self.kernel_ws:
            await self.kernel_ws.close()
            self.kernel_ws = None
        
        debug_log(f"🔌 [WebSocket] WebSocket disconnected")
    
    async def cleanup(self):
        """Clean up WebSocket resources."""
        await self.disconnect()
        
        # Clear queues
        while not self.message_queue.empty():
            try:
                self.message_queue.get_nowait()
                self.message_queue.task_done()
            except:
                pass
        
        while not self.response_queue.empty():
            try:
                self.response_queue.get_nowait()
                self.response_queue.task_done()
            except:
                pass
        
        debug_log(f"🧹 [WebSocket] WebSocket cleanup completed")

    def set_broadcast_callback(self, callback: Callable):
        """Set the callback for broadcasting messages to the frontend via WebRTC."""
        self.broadcast_callback = callback
        debug_log(f"📡 [WebSocket] Broadcast callback set")
        print(f"📡 [WebSocket] Broadcast callback set")

    async def _reconnect(self):
        """Attempt to reconnect the WebSocket."""
        try:
            debug_log(f"🔄 [WebSocket] Attempting to reconnect", {
                "attempt": self.reconnect_attempts + 1,
                "max_attempts": self.max_reconnect_attempts
            })
            print(f"🔄 [WebSocket] Attempting to reconnect (attempt {self.reconnect_attempts + 1})")
            
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                debug_log(f"❌ [WebSocket] Max reconnection attempts reached")
                print(f"❌ [WebSocket] Max reconnection attempts reached")
                return False
            
            self.reconnect_attempts += 1
            
            # Wait before reconnecting
            await asyncio.sleep(self.reconnect_delay)
            
            # Try to reconnect
            if self.kernel_ws:
                try:
                    await self.kernel_ws.close()
                except:
                    pass
            
            # Reconnect logic would go here
            # For now, we'll just mark as disconnected
            self.connected = False
            debug_log(f"❌ [WebSocket] Reconnection not implemented yet")
            print(f"❌ [WebSocket] Reconnection not implemented yet")
            return False
            
        except Exception as e:
            debug_log(f"❌ [WebSocket] Reconnection error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            print(f"❌ [WebSocket] Reconnection error: {e}")
            return False
    
    async def reconnect(self, ws_url: str, extra_headers: Dict[str, str] = None) -> bool:
        """Reconnect to a WebSocket URL."""
        try:
            debug_log(f"🔄 [WebSocket] Reconnecting to WebSocket", {
                "ws_url": ws_url,
                "has_headers": bool(extra_headers)
            })
            print(f"🔄 [WebSocket] Reconnecting to: {ws_url}")
            
            # Close existing connection
            if self.kernel_ws:
                try:
                    await self.kernel_ws.close()
                except:
                    pass
                self.kernel_ws = None
            
            # Reset connection state
            self.connected = False
            self.processing_messages = False
            
            # Attempt new connection
            success = await self.connect(ws_url, extra_headers)
            
            if success:
                debug_log(f"✅ [WebSocket] Reconnection successful")
                print(f"✅ [WebSocket] Reconnection successful")
                self.reconnect_attempts = 0
            else:
                debug_log(f"❌ [WebSocket] Reconnection failed")
                print(f"❌ [WebSocket] Reconnection failed")
            
            return success
            
        except Exception as e:
            debug_log(f"❌ [WebSocket] Reconnection error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            print(f"❌ [WebSocket] Reconnection error: {e}")
            return False
