"""
WebSocket Bridge Service for TensorDock.
Handles all WebSocket functionality via WebRTC, including:
- Real WebSocket connections to Jupyter server
- Bidirectional message routing between frontend and Jupyter
- Complete JupyterLab protocol implementation
- Connection lifecycle management
"""

import asyncio
import json
import datetime
import uuid
from typing import Dict, Any, Optional, Callable, Set, List
from websockets.client import connect
from websockets.exceptions import WebSocketException

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log
from core.config import ServerConfig


class WebSocketBridge(LoggerMixin):
    """Complete WebSocket bridge that handles all WebSocket functionality via WebRTC."""
    
    def __init__(self, config: ServerConfig):
        super().__init__()
        self.config = config
        
        # WebSocket connections to Jupyter server
        self.jupyter_connections: Dict[str, Any] = {}  # kernel_id -> WebSocket connection
        
        # Frontend WebRTC connections
        self.frontend_connections: Dict[str, Dict[str, Any]] = {}  # instance_id -> connection info
        
        # Message routing and state
        self.message_handlers: Dict[str, Callable] = {}
        self.pending_messages: Dict[str, Dict[str, Any]] = {}  # msg_id -> message info
        self.message_queues: Dict[str, asyncio.Queue] = {}  # kernel_id -> message queue
        
        # Connection management
        self.connection_states: Dict[str, str] = {}  # instance_id -> connection state
        self.reconnect_tasks: Dict[str, asyncio.Task] = {}
        
        # Broadcast callback for sending messages to frontend
        self.broadcast_callback: Optional[Callable] = None
        
        # Task management
        self.message_processor_tasks: Dict[str, asyncio.Task] = {}
        self.cleanup_task: Optional[asyncio.Task] = None
        
        debug_log(f"🔌 [WebSocketBridge] WebSocket bridge initialized")
    
    def set_broadcast_callback(self, callback: Callable):
        """Set the broadcast callback for sending messages to frontend."""
        self.broadcast_callback = callback
        debug_log(f"🔌 [WebSocketBridge] Broadcast callback set")
    
    async def connect_kernel(self, instance_id: str, kernel_id: str, url: str = None) -> bool:
        """Connect to a Jupyter kernel via WebSocket for all channels."""
        try:
            debug_log(f"🔌 [WebSocketBridge] Starting kernel connection", {
                "instance_id": instance_id,
                "kernel_id": kernel_id,
                "url": url,
                "existing_connections": len(self.jupyter_connections),
                "existing_frontend_connections": len(self.frontend_connections)
            })
            
            # Use default URL if none provided
            if url is None:
                url = "http://localhost:8888"
            
            debug_log(f"🔌 [WebSocketBridge] Connecting to kernel", {
                "kernel_id": kernel_id,
                "instance_id": instance_id,
                "url": url
            })
            
            # CRITICAL: Check if kernel exists before trying to connect
            # If kernel doesn't exist, we need to create it first
            kernel_exists = await self._check_kernel_exists(kernel_id, "http://localhost:8888")
            if not kernel_exists:
                debug_log(f"⚠️ [WebSocketBridge] Kernel {kernel_id} doesn't exist, attempting to create it", {
                    "kernel_id": kernel_id,
                    "instance_id": instance_id
                })
                
                # Try to create the kernel
                kernel_created = await self._create_kernel(kernel_id, "http://localhost:8888")
                if not kernel_created:
                    debug_log(f"❌ [WebSocketBridge] Failed to create kernel {kernel_id}", {
                        "kernel_id": kernel_id,
                        "instance_id": instance_id
                    })
                    return False
                
                debug_log(f"✅ [WebSocketBridge] Successfully created kernel {kernel_id}", {
                    "kernel_id": kernel_id,
                    "instance_id": instance_id
                })
            
            # Connect to Jupyter kernel using single WebSocket endpoint
            # This endpoint handles all channels (shell, iopub, stdin, control)
            ws_url = self._build_websocket_url(url, kernel_id)
            
            # Create WebSocket connection to Jupyter server
            headers = self.config.get_jupyter_headers()
            
            debug_log(f"🔌 [WebSocketBridge] Attempting WebSocket connection", {
                "ws_url": ws_url,
                "headers": headers,
                "instance_id": instance_id,
                "kernel_id": kernel_id
            })
            
            try:
                websocket = await connect(
                    ws_url,
                    extra_headers=headers or {},
                    ping_interval=None,
                    ping_timeout=None
                )
                
                debug_log(f"✅ [WebSocketBridge] WebSocket connection established", {
                    "ws_url": ws_url,
                    "instance_id": instance_id,
                    "kernel_id": kernel_id
                })
                
                # Store single connection that handles all channels
                self.jupyter_connections[kernel_id] = {
                    'websocket': websocket,
                    'url': ws_url,
                    'connected_at': datetime.datetime.now(),
                    'instance_ids': [instance_id],
                    'connection_type': 'websocket_single'
                }
                
                debug_log(f"📝 [WebSocketBridge] Jupyter connection stored", {
                    "kernel_id": kernel_id,
                    "jupyter_connections": self.jupyter_connections,
                    "total_jupyter_connections": len(self.jupyter_connections)
                })
                
                # Store frontend connection info
                self.frontend_connections[instance_id] = {
                    'kernel_id': kernel_id,
                    'session_id': None,  # Will be set when frontend sends session info
                    'connected_at': datetime.datetime.now(),
                    'status': 'connected',
                    'channels': ['shell', 'iopub', 'stdin', 'control']  # All channels available
                }
                
                debug_log(f"📝 [WebSocketBridge] Frontend connection stored", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id,
                    "frontend_connections": self.frontend_connections,
                    "total_connections": len(self.frontend_connections)
                })
                
                # Update connection state
                self.connection_states[instance_id] = 'connected'
                
                # Create message queue for this kernel
                if kernel_id not in self.message_queues:
                    self.message_queues[kernel_id] = asyncio.Queue()
                
                # Start message processor for this kernel
                if kernel_id not in self.message_processor_tasks:
                    self.message_processor_tasks[kernel_id] = asyncio.create_task(
                        self._process_kernel_messages(kernel_id)
                    )
                
                # Start listening for messages from Jupyter (single connection handles all channels)
                asyncio.create_task(self._listen_jupyter_messages(kernel_id, websocket))
                
                debug_log(f"✅ [WebSocketBridge] Kernel connected successfully", {
                    "kernel_id": kernel_id,
                    "instance_id": instance_id,
                    "ws_url": ws_url,
                    "channels": ['shell', 'iopub', 'stdin', 'control']
                })
                
                return True
                
            except Exception as ws_error:
                debug_log(f"❌ [WebSocketBridge] WebSocket connection failed", {
                    "kernel_id": kernel_id,
                    "instance_id": instance_id,
                    "error": str(ws_error),
                    "error_type": type(ws_error).__name__,
                    "ws_url": ws_url
                })
                return False
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Failed to connect to kernel", {
                "kernel_id": kernel_id,
                "instance_id": instance_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            
            # Update connection state
            self.connection_states[instance_id] = 'failed'
            
            return False
    
    async def _check_kernel_exists(self, kernel_id: str, base_url: str) -> bool:
        """Check if a kernel exists on the Jupyter server."""
        try:
            import aiohttp
            
            # CRITICAL: Extract the actual Jupyter base URL from the WebRTC URL
            # The base_url parameter contains the WebRTC URL, we need to extract the Jupyter server URL
            jupyter_base_url = "http://localhost:8888"  # Default Jupyter server URL
            
            # Build the kernel info URL
            kernel_url = f"{jupyter_base_url}/api/kernels/{kernel_id}"
            
            debug_log(f"🔍 [WebSocketBridge] Checking if kernel exists", {
                "kernel_id": kernel_id,
                "jupyter_url": kernel_url,
                "original_base_url": base_url
            })
            
            # Make HTTP request to check kernel info
            async with aiohttp.ClientSession() as session:
                headers = self.config.get_jupyter_headers()
                async with session.get(kernel_url, headers=headers) as response:
                    if response.status == 200:
                        debug_log(f"✅ [WebSocketBridge] Kernel {kernel_id} exists", {
                            "kernel_id": kernel_id,
                            "status": response.status
                        })
                        return True
                    elif response.status == 404:
                        debug_log(f"❌ [WebSocketBridge] Kernel {kernel_id} does not exist", {
                            "kernel_id": kernel_id,
                            "status": response.status
                        })
                        return False
                    else:
                        debug_log(f"⚠️ [WebSocketBridge] Unexpected status checking kernel", {
                            "kernel_id": kernel_id,
                            "status": response.status,
                            "response_text": await response.text()
                        })
                        return False
                        
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error checking kernel existence", {
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    async def _create_kernel(self, kernel_id: str, base_url: str) -> bool:
        """Create a new kernel on the Jupyter server."""
        try:
            import aiohttp
            
            # CRITICAL: Extract the actual Jupyter base URL from the WebRTC URL
            # The base_url parameter contains the WebRTC URL, we need to extract the Jupyter server URL
            jupyter_base_url = "http://localhost:8888"  # Default Jupyter server URL
            
            # Build the kernels creation URL
            kernels_url = f"{jupyter_base_url}/api/kernels"
            
            debug_log(f"📝 [WebSocketBridge] Creating kernel", {
                "kernel_id": kernel_id,
                "jupyter_url": kernels_url,
                "original_base_url": base_url
            })
            
            # Create kernel with Python3 (default)
            kernel_data = {
                "name": "python3"
            }
            
            # Make HTTP request to create kernel
            async with aiohttp.ClientSession() as session:
                headers = self.config.get_jupyter_headers()
                headers['Content-Type'] = 'application/json'
                
                async with session.post(kernels_url, headers=headers, json=kernel_data) as response:
                    if response.status == 201:
                        response_data = await response.json()
                        created_kernel_id = response_data.get('id')
                        
                        debug_log(f"✅ [WebSocketBridge] Successfully created kernel", {
                            "requested_id": kernel_id,
                            "created_id": created_kernel_id,
                            "status": response.status,
                            "response": response_data
                        })
                        
                        # Update kernel_id to use the actual created ID
                        if created_kernel_id and created_kernel_id != kernel_id:
                            debug_log(f"🔄 [WebSocketBridge] Kernel ID changed from {kernel_id} to {created_kernel_id}", {
                                "old_id": kernel_id,
                                "new_id": created_kernel_id
                            })
                            kernel_id = created_kernel_id
                        
                        return True
                    else:
                        response_text = await response.text()
                        debug_log(f"❌ [WebSocketBridge] Failed to create kernel", {
                            "kernel_id": kernel_id,
                            "status": response.status,
                            "response": response_text
                        })
                        return False
                        
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error creating kernel", {
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    def _get_target_channel(self, msg_type: str) -> str:
        """Determine which Jupyter channel a message should be sent to."""
        # Map message types to channels based on JupyterLab protocol
        channel_mapping = {
            # Shell channel (execution requests, kernel info, etc.)
            'execute_request': 'shell',
            'kernel_info_request': 'shell',
            'complete_request': 'shell',
            'inspect_request': 'shell',
            'history_request': 'shell',
            'is_complete_request': 'shell',
            'comm_info_request': 'shell',
            'comm_msg': 'shell',
            'comm_close': 'shell',
            
            # Control channel (interrupt, restart, shutdown)
            'interrupt_request': 'control',
            'restart_request': 'control',
            'shutdown_request': 'control',
            
            # Stdin channel (user input)
            'input_request': 'stdin',
            
            # Iopub channel (output, status updates)
            'execute_input': 'iopub',
            'execute_result': 'iopub',
            'stream': 'iopub',
            'error': 'iopub',
            'status': 'iopub',
            'clear_output': 'iopub',
            'display_data': 'iopub',
            'update_display_data': 'iopub',
            'comm_open': 'iopub',
            'comm_msg': 'iopub',
            'comm_close': 'iopub'
        }
        
        return channel_mapping.get(msg_type, 'shell')  # Default to shell channel
    
    async def disconnect_kernel(self, instance_id: str, kernel_id: str) -> bool:
        """Disconnect a kernel connection."""
        try:
            debug_log(f"🔌 [WebSocketBridge] Disconnecting kernel", {
                "instance_id": instance_id,
                "kernel_id": kernel_id
            })
            
            # Remove frontend connection
            if instance_id in self.frontend_connections:
                del self.frontend_connections[instance_id]
            
            # Remove connection state
            if instance_id in self.connection_states:
                del self.connection_states[instance_id]
            
            # Check if this was the last instance for this kernel
            if kernel_id in self.jupyter_connections:
                kernel_info = self.jupyter_connections[kernel_id]
                if instance_id in kernel_info['instance_ids']:
                    kernel_info['instance_ids'].remove(instance_id)
                
                # If no more instances, close the WebSocket connection
                if not kernel_info['instance_ids']:
                    await self._close_jupyter_connection(kernel_id)
            
            debug_log(f"✅ [WebSocketBridge] Kernel disconnected", {
                "instance_id": instance_id,
                "kernel_id": kernel_id
            })
            
            return True
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Failed to disconnect kernel", {
                "instance_id": instance_id,
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    async def send_message(self, instance_id: str, kernel_id: str, data: Any) -> bool:
        """Send a message from frontend to Jupyter server."""
        try:
            # Auto-connect if no connection exists
            if kernel_id not in self.jupyter_connections:
                debug_log(f"🔄 [WebSocketBridge] No connection for kernel, attempting auto-connect", {
                    "kernel_id": kernel_id,
                    "instance_id": instance_id
                })
                
                # Try to auto-connect to the kernel
                success = await self.connect_kernel(instance_id, kernel_id)
                if not success:
                    debug_log(f"❌ [WebSocketBridge] Auto-connect failed for kernel", {
                        "kernel_id": kernel_id,
                        "instance_id": instance_id
                    })
                    return False
                
                debug_log(f"✅ [WebSocketBridge] Auto-connect successful for kernel", {
                    "kernel_id": kernel_id,
                    "instance_id": instance_id
                })
            
            connection_info = self.jupyter_connections[kernel_id]
            websocket = connection_info.get('websocket')
            connection_type = connection_info.get('connection_type', 'websocket_multi_channel')
            
            # Log what we're sending
            msg_type = data.get('header', {}).get('msg_type', 'unknown') if isinstance(data, dict) else 'unknown'
            msg_id = data.get('header', {}).get('msg_id', 'unknown') if isinstance(data, dict) else 'unknown'
            
            if connection_type == 'websocket_single' and websocket:
                # Determine which channel to send to based on message type
                target_channel = self._get_target_channel(msg_type)
                
                # Store message as pending for response matching
                if msg_id != 'unknown':
                    self.pending_messages[msg_id] = {
                        'instance_id': instance_id,
                        'kernel_id': kernel_id,
                        'msg_type': msg_type,
                        'timestamp': datetime.datetime.now(),
                        'target_channel': target_channel
                    }
                    
                    debug_log(f"📝 [WebSocketBridge] Message stored as pending", {
                        "msg_id": msg_id,
                        "instance_id": instance_id,
                        "kernel_id": kernel_id,
                        "msg_type": msg_type
                    })
                
                # Send via WebSocket to specific channel
                debug_log(f"📤 [WebSocketBridge] Sending message via WebSocket to {target_channel} channel", {
                    "msg_id": msg_id,
                    "instance_id": instance_id,
                    "kernel_id": kernel_id,
                    "msg_type": msg_type,
                    "target_channel": target_channel
                })
                
                await websocket.send(json.dumps(data))
                
            else:
                debug_log(f"❌ [WebSocketBridge] No valid connection type or WebSocket", {
                    "connection_type": connection_type,
                    "has_websocket": bool(websocket)
                })
                return False
            
            debug_log(f"📤 [WebSocketBridge] Message sent to Jupyter", {
                "msg_id": msg_id,
                "instance_id": instance_id,
                "kernel_id": kernel_id,
                "msg_type": msg_type,
                "connection_type": connection_type,
                "target_channel": target_channel if 'target_channel' in locals() else 'unknown'
            })
            
            return True
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error sending message", {
                "kernel_id": kernel_id,
                "instance_id": instance_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    async def _listen_jupyter_messages(self, kernel_id: str, websocket):
        """Listen for messages from Jupyter server for a specific channel."""
        try:
            debug_log(f"👂 [WebSocketBridge] Listening for messages from kernel channel", {
                "kernel_id": kernel_id
            })
            
            async for message in websocket:
                try:
                    # Parse message
                    if isinstance(message, str):
                        data = json.loads(message)
                    else:
                        data = message
                    
                    # Process message - determine the correct channel based on message type
                    channel = self._get_target_channel(data.get('header', {}).get('msg_type', 'unknown'))
                    await self._handle_jupyter_message(kernel_id, data, channel)
                    
                except json.JSONDecodeError as e:
                    debug_log(f"❌ [WebSocketBridge] Failed to parse Jupyter message", {
                        "kernel_id": kernel_id,
                        "error": str(e)
                    })
                except Exception as e:
                    debug_log(f"❌ [WebSocketBridge] Error handling Jupyter message", {
                        "kernel_id": kernel_id,
                        "error": str(e),
                        "error_type": type(e).__name__
                    })
                    
        except WebSocketException as e:
            debug_log(f"🔌 [WebSocketBridge] WebSocket connection closed", {
                "kernel_id": kernel_id,
                "error": str(e)
            })
            
            # Mark connection as disconnected
            if kernel_id in self.jupyter_connections:
                self.jupyter_connections[kernel_id]['websocket'] = None
            
            # Notify frontend
            await self._notify_connection_status(kernel_id, 'disconnected')
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error in Jupyter message listener", {
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _handle_jupyter_message(self, kernel_id: str, message: Dict[str, Any], channel: str = 'shell'):
        """Handle incoming message from Jupyter server."""
        try:
            # Extract message details
            msg_type = message.get('header', {}).get('msg_type', 'unknown')
            msg_id = message.get('header', {}).get('msg_id', 'unknown')
            parent_header = message.get('parent_header', {})
            parent_msg_id = parent_header.get('msg_id') if parent_header else None
            
            debug_log(f"📥 [WebSocketBridge] Jupyter message received", {
                "kernel_id": kernel_id,
                "channel": channel,
                "msg_type": msg_type,
                "msg_id": msg_id,
                "parent_msg_id": parent_msg_id
            })
            
            # Check if this is a response to a pending message
            # Jupyter responses often have a different msg_id but reference the parent_msg_id
            response_to_msg_id = None
            if msg_id in self.pending_messages:
                response_to_msg_id = msg_id
            elif parent_msg_id and parent_msg_id in self.pending_messages:
                response_to_msg_id = parent_msg_id
            
            if response_to_msg_id:
                await self._handle_response(response_to_msg_id, message)
                return
            
            # Handle different message types
            if msg_type == 'status':
                await self._handle_status_update(kernel_id, message)
            elif msg_type == 'kernel_info_reply':
                await self._handle_kernel_info(kernel_id, message)
            else:
                # Forward other messages to frontend
                await self._forward_to_frontend(kernel_id, message, channel)
                
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error handling Jupyter message", {
                "kernel_id": kernel_id,
                "channel": channel,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _handle_response(self, msg_id: str, response: Dict[str, Any]):
        """Handle response to a pending message."""
        try:
            pending_msg = self.pending_messages[msg_id]
            kernel_id = pending_msg['kernel_id']
            
            # Create a reverse mapping from kernel_id to instance_id
            kernel_to_instance = {}
            for frontend_instance_id, frontend_info in self.frontend_connections.items():
                if frontend_info.get('kernel_id'):
                    kernel_to_instance[frontend_info['kernel_id']] = frontend_instance_id
            
            # Find the correct instance ID for this kernel
            instance_id = kernel_to_instance.get(kernel_id)
            
            if not instance_id:
                debug_log(f"⚠️ [WebSocketBridge] No frontend instance found for response", {
                    "msg_id": msg_id,
                    "kernel_id": kernel_id,
                    "available_instances": list(self.frontend_connections.keys()),
                    "kernel_to_instance_mapping": kernel_to_instance
                })
                return
            
            debug_log(f"📥 [WebSocketBridge] Response received", {
                "msg_id": msg_id,
                "instance_id": instance_id,
                "kernel_id": kernel_id,
                "response_type": response.get('header', {}).get('msg_type', 'unknown')
            })
            
            # Send response to frontend
            if self.broadcast_callback:
                await self.broadcast_callback({
                    'action': 'websocket_message',
                    'instanceId': instance_id,  # Use the actual instance ID
                    'kernelId': kernel_id,
                    'data': response,
                    'timestamp': datetime.datetime.now().isoformat()
                })
            
            # Remove from pending messages
            del self.pending_messages[msg_id]
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error handling response", {
                "msg_id": msg_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _handle_status_update(self, kernel_id: str, message: Dict[str, Any]):
        """Handle kernel status update message."""
        try:
            execution_state = message.get('content', {}).get('execution_state', 'unknown')
            
            debug_log(f"📊 [WebSocketBridge] Status update", {
                "kernel_id": kernel_id,
                "status": execution_state
            })
            
            # Forward status update to frontend
            await self._forward_to_frontend(kernel_id, message, 'iopub')
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error handling status update", {
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _handle_kernel_info(self, kernel_id: str, message: Dict[str, Any]):
        """Handle kernel info reply message."""
        try:
            debug_log(f"ℹ️ [WebSocketBridge] Kernel info received", {
                "kernel_id": kernel_id,
                "msg_id": message.get('header', {}).get('msg_id')
            })
            
            # Forward to all frontend instances
            await self._forward_to_frontend(kernel_id, message, 'shell') # Assuming kernel_info_reply is typically shell
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error handling kernel info", {
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _forward_to_frontend(self, kernel_id: str, message: Dict[str, Any], channel: str = 'shell'):
        """Forward message from Jupyter to frontend via WebRTC."""
        try:
            
            # Find the correct instance ID for this kernel
            instance_id = None
            
            # CRITICAL: Jupyter messages have a session field, not kernel_id
            # We need to map by session ID, not kernel ID
            session_id = message.get('header', {}).get('session')
            if session_id:
                debug_log(f"🔍 [WebSocketBridge] Message has session ID: {session_id}")
                
                # Look for a frontend connection that matches this session
                for frontend_instance_id, frontend_info in self.frontend_connections.items():
                    if frontend_info.get('session_id') == session_id:
                        instance_id = frontend_instance_id
                        debug_log(f"🔍 [WebSocketBridge] Found instance {instance_id} for session {session_id}")
                        break
                
                if not instance_id:
                    debug_log(f"⚠️ [WebSocketBridge] No frontend instance found for session {session_id}")
                    # Fall back to kernel_id mapping
                    pass
            
            # Fallback: Create a reverse mapping from kernel_id to instance_id
            if not instance_id:
                kernel_to_instance = {}
                for frontend_instance_id, frontend_info in self.frontend_connections.items():
                    if frontend_info.get('kernel_id'):
                        kernel_to_instance[frontend_info['kernel_id']] = frontend_instance_id
                        debug_log(f"🔍 [WebSocketBridge] Mapping kernel {frontend_info['kernel_id']} to instance {frontend_instance_id}")
                
                debug_log(f"🔍 [WebSocketBridge] Kernel to instance mapping", {
                    "kernel_id": kernel_id,
                    "kernel_to_instance": kernel_to_instance,
                    "target_instance_id": kernel_to_instance.get(kernel_id),
                    "all_kernel_ids": list(kernel_to_instance.keys())
                })
                
                # Look up the instance ID for this kernel
                instance_id = kernel_to_instance.get(kernel_id)
            
            if not instance_id:
                debug_log(f"⚠️ [WebSocketBridge] No frontend instance found for kernel", {
                    "kernel_id": kernel_id,
                    "available_instances": list(self.frontend_connections.keys()),
                    "frontend_connections": self.frontend_connections,
                    "kernel_to_instance_mapping": kernel_to_instance
                })
                return
            
            # Add channel information to the message
            message_with_channel = {
                'action': 'websocket_message',
                'instanceId': instance_id,  # Use the actual instance ID
                'kernelId': kernel_id,
                'data': message,
                'channel': channel,
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            # debug_log(f"📤 [WebSocketBridge] Prepared message for frontend", {
            #     "message_structure": message_with_channel,
            #     "instanceId": instance_id,
            #     "kernelId": kernel_id,
            #     "channel": channel
            # })
            
            # Broadcast to all connected frontend instances
            if self.broadcast_callback:
                await self.broadcast_callback(message_with_channel)
                
                debug_log(f"📤 [WebSocketBridge] Message forwarded to frontend", {
                    "kernel_id": kernel_id,
                    "instance_id": instance_id,
                    "instance_count": len(self.frontend_connections),
                    "msg_type": message.get('header', {}).get('msg_type', 'unknown'),
                    "channel": channel,
                    "message_structure": message_with_channel
                })
            else:
                debug_log(f"⚠️ [WebSocketBridge] No broadcast callback available", {
                    "kernel_id": kernel_id,
                    "instance_id": instance_id,
                    "channel": channel
                })
                
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error forwarding message to frontend", {
                "kernel_id": kernel_id,
                "channel": channel,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _notify_connection_status(self, kernel_id: str, status: str):
        """Notify frontend of connection status change."""
        try:
            if kernel_id not in self.jupyter_connections:
                return
            
            instance_ids = self.jupyter_connections[kernel_id]['instance_ids']
            
            for instance_id in instance_ids:
                if self.broadcast_callback:
                    await self.broadcast_callback({
                        'action': 'websocket_connected' if status == 'connected' else 'websocket_closed',
                        'instanceId': instance_id,
                        'kernelId': kernel_id,
                        'timestamp': datetime.datetime.now().isoformat()
                    })
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error notifying connection status", {
                "kernel_id": kernel_id,
                "status": status,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    def update_session_id(self, instance_id: str, session_id: str):
        """Update the session ID for a frontend connection."""
        try:
            if instance_id in self.frontend_connections:
                self.frontend_connections[instance_id]['session_id'] = session_id
                debug_log(f"📝 [WebSocketBridge] Updated session ID for instance {instance_id}: {session_id}")
            else:
                debug_log(f"⚠️ [WebSocketBridge] Instance {instance_id} not found when updating session ID")
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error updating session ID", {
                "instance_id": instance_id,
                "session_id": session_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _process_kernel_messages(self, kernel_id: str):
        """Process messages from the message queue for a kernel."""
        try:
            if kernel_id not in self.message_queues:
                return
            
            queue = self.message_queues[kernel_id]
            
            while True:
                try:
                    # Get message from queue
                    message = await queue.get()
                    
                    if message is None:  # Shutdown signal
                        break
                    
                    # Process message
                    await self._process_message(kernel_id, message)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    debug_log(f"❌ [WebSocketBridge] Error processing message", {
                        "kernel_id": kernel_id,
                        "error": str(e),
                        "error_type": type(e).__name__
                    })
                    
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error in message processor", {
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _process_message(self, kernel_id: str, message: Dict[str, Any]):
        """Process a single message for a kernel."""
        try:
            # Extract message details
            instance_id = message.get('instanceId')
            data = message.get('data')
            
            if not instance_id or not data:
                debug_log(f"⚠️ [WebSocketBridge] Invalid message format", {
                    "kernel_id": kernel_id,
                    "message_keys": list(message.keys())
                })
                return
            
            # Send message to Jupyter server
            success = await self.send_message(instance_id, kernel_id, data)
            
            if success:
                debug_log(f"✅ [WebSocketBridge] Message processed successfully", {
                    "kernel_id": kernel_id,
                    "instance_id": instance_id
                })
            else:
                debug_log(f"❌ [WebSocketBridge] Failed to process message", {
                    "kernel_id": kernel_id,
                    "instance_id": instance_id
                })
                
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error processing message", {
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _close_jupyter_connection(self, kernel_id: str):
        """Close WebSocket connection to Jupyter server."""
        try:
            if kernel_id in self.jupyter_connections:
                websocket = self.jupyter_connections[kernel_id]['websocket']
                if websocket:
                    await websocket.close()
                
                del self.jupyter_connections[kernel_id]
                
                debug_log(f"🔌 [WebSocketBridge] Jupyter connection closed", {
                    "kernel_id": kernel_id
                })
                
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error closing Jupyter connection", {
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    def _build_websocket_url(self, url: str, kernel_id: str = None, channel: str = None) -> str:
        """Build WebSocket URL from HTTP URL."""
        if url.startswith('http://'):
            base_url = url.replace('http://', 'ws://')
        elif url.startswith('https://'):
            base_url = url.replace('https://', 'wss://')
        else:
            # Assume localhost if no protocol
            base_url = f"ws://localhost:8888"
        
        # Add kernel WebSocket endpoint
        if not base_url.endswith('/'):
            base_url += '/'
        
        if kernel_id:
            # Use the standard Jupyter kernel WebSocket endpoint
            # This single endpoint handles all channels (shell, iopub, stdin, control)
            ws_url = f"{base_url}api/kernels/{kernel_id}/channels"
        else:
            ws_url = f"{base_url}api/kernels"
        
        debug_log(f"🔗 [WebSocketBridge] Built WebSocket URL", {
            "base_url": base_url,
            "kernel_id": kernel_id,
            "channel": channel,
            "ws_url": ws_url
        })
        
        return ws_url
    
    def get_status(self) -> Dict[str, Any]:
        """Get WebSocket bridge status."""
        return {
            'jupyter_connections': len(self.jupyter_connections),
            'frontend_connections': len(self.frontend_connections),
            'pending_messages': len(self.pending_messages),
            'connection_states': dict(self.connection_states),
            'active_processors': len(self.message_processor_tasks)
        }
    
    async def cleanup(self):
        """Clean up WebSocket bridge resources."""
        debug_log(f"🧹 [WebSocketBridge] Cleaning up WebSocket bridge")
        
        try:
            # Cancel all message processor tasks
            for task in self.message_processor_tasks.values():
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            
            # Close all Jupyter connections
            for kernel_id in list(self.jupyter_connections.keys()):
                await self._close_jupyter_connection(kernel_id)
            
            # Clear all data structures
            self.jupyter_connections.clear()
            self.frontend_connections.clear()
            self.connection_states.clear()
            self.pending_messages.clear()
            self.message_queues.clear()
            self.message_processor_tasks.clear()
            
            debug_log(f"🧹 [WebSocketBridge] WebSocket bridge cleanup completed")
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error during cleanup", {
                "error": str(e),
                "error_type": type(e).__name__
            })
