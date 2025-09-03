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
        
        # Connection management
        self.jupyter_connections: Dict[str, Dict[str, Any]] = {}  # kernel_id -> connection info
        self.frontend_connections: Dict[str, Dict[str, Any]] = {}  # instance_id -> connection info
        self.connection_states: Dict[str, str] = {}  # instance_id -> state
        
        # Message tracking
        self.pending_messages: Dict[str, Dict[str, Any]] = {}  # msg_id -> message info
        self.processed_messages: Set[str] = set()  # Track processed message IDs to prevent duplicates
        self.comm_message_tracker: Dict[str, Set[str]] = {}  # comm_id -> set of processed msg_ids
        self.most_recent_comm_messages: Dict[str, Dict[str, Any]] = {}  # kernel_id -> most recent comm message
        
        # ✅ CRITICAL FIX: Add missing message_queues attribute
        self.message_queues: Dict[str, asyncio.Queue] = {}  # instance_id -> message queue
        
        # ✅ CRITICAL FIX: Add missing message_processor_tasks attribute
        self.message_processor_tasks: Dict[str, asyncio.Task] = {}  # kernel_id -> message processor task
        
        # Broadcast callback
        self.broadcast_callback: Optional[Callable] = None
        
        # Start periodic cleanup task
        asyncio.create_task(self._periodic_cleanup())
        
        # Start connection health monitoring task
        asyncio.create_task(self._periodic_connection_health_check())
        
        debug_log(f"🔌 [WebSocketBridge] WebSocket bridge service initialized")
    
    async def _periodic_cleanup(self):
        """Periodic cleanup task to prevent memory leaks."""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes
                await self._cleanup_old_messages()
            except Exception as e:
                debug_log(f"❌ [WebSocketBridge] Error in periodic cleanup", {
                    "error": str(e),
                    "error_type": type(e).__name__
                })

    async def _periodic_connection_health_check(self):
        """Periodically check the health of all WebSocket connections."""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                current_time = datetime.datetime.now()
                stale_connections = []
                
                for kernel_id, connection_info in self.jupyter_connections.items():
                    websocket = connection_info.get('websocket')
                    connected_at = connection_info.get('connected_at')
                    
                    if websocket is None:
                        continue
                    
                    # Check if connection is too old (more than 1 hour)
                    if connected_at and (current_time - connected_at).total_seconds() > 3600:
                        debug_log(f"🕐 [WebSocketBridge] Connection is stale, marking for cleanup", {
                            "kernel_id": kernel_id,
                            "connected_at": connected_at.isoformat(),
                            "age_seconds": (current_time - connected_at).total_seconds()
                        })
                        stale_connections.append(kernel_id)
                        continue
                    
                    # Check if websocket is closed
                    if websocket.closed:
                        debug_log(f"🔌 [WebSocketBridge] WebSocket connection is closed, marking for cleanup", {
                            "kernel_id": kernel_id
                        })
                        stale_connections.append(kernel_id)
                        continue
                    
                    # Try to ping the connection
                    try:
                        pong_waiter = await websocket.ping()
                        await asyncio.wait_for(pong_waiter, timeout=5.0)
                        debug_log(f"💓 [WebSocketBridge] Connection health check passed", {
                            "kernel_id": kernel_id
                        })
                    except (asyncio.TimeoutError, Exception) as e:
                        debug_log(f"❌ [WebSocketBridge] Connection health check failed", {
                            "kernel_id": kernel_id,
                            "error": str(e)
                        })
                        stale_connections.append(kernel_id)
                
                # Clean up stale connections
                for kernel_id in stale_connections:
                    await self._cleanup_stale_connection(kernel_id)
                    
            except Exception as e:
                debug_log(f"❌ [WebSocketBridge] Error in periodic connection health check", {
                    "error": str(e),
                    "error_type": type(e).__name__
                })

    async def _cleanup_stale_connection(self, kernel_id: str):
        """Clean up a stale WebSocket connection."""
        try:
            if kernel_id in self.jupyter_connections:
                connection_info = self.jupyter_connections[kernel_id]
                websocket = connection_info.get('websocket')
                
                if websocket and not websocket.closed:
                    try:
                        await websocket.close(code=1000, reason="Connection cleanup")
                    except Exception as e:
                        debug_log(f"⚠️ [WebSocketBridge] Error closing websocket during cleanup", {
                            "kernel_id": kernel_id,
                            "error": str(e)
                        })
                
                # Remove connection
                del self.jupyter_connections[kernel_id]
                
                # Notify frontend instances
                instance_ids = connection_info.get('instance_ids', [])
                for instance_id in instance_ids:
                    if instance_id in self.frontend_connections:
                        await self._notify_connection_status(kernel_id, 'disconnected')
                
                debug_log(f"🧹 [WebSocketBridge] Stale connection cleaned up", {
                    "kernel_id": kernel_id
                })
                
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error cleaning up stale connection", {
                "kernel_id": kernel_id,
                "error": str(e)
            })
    
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
                    ping_interval=30,  # Send ping every 30 seconds
                    ping_timeout=10,   # Wait 10 seconds for pong response
                    close_timeout=10,  # Wait 10 seconds for close
                    max_size=2**20,    # 1MB max message size
                    max_queue=2**10    # 1024 messages max queue
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
            'comm_msg': 'shell',  # Frontend → Kernel: Shell channel
            'comm_close': 'shell',  # Frontend → Kernel: Shell channel
            
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
            'comm_open': 'iopub',  # Kernel → Frontend: IOPub channel
            'comm_msg': 'iopub',   # Kernel → Frontend: IOPub channel (for responses)
            'comm_close': 'iopub'  # Kernel → Frontend: IOPub channel
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
                    
                    # ✅ CRITICAL FIX: Clean up message tracking for this kernel
                    await self._cleanup_kernel_messages(kernel_id)
            
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
    
    async def send_message(self, instance_id: str, kernel_id: str, data: Any, channel: str = None) -> bool:
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
                # Use provided channel or determine based on message type
                target_channel = channel if channel else self._get_target_channel(msg_type)
                
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
                
                try:
                    # Encode message with channel information according to Jupyter WebSocket protocol
                    # The channel must be included in the message structure
                    message_with_channel = {
                        'channel': target_channel,  # Channel name must be encoded
                        'header': data.get('header', {}),
                        'parent_header': data.get('parent_header', {}),
                        'metadata': data.get('metadata', {}),
                        'content': data.get('content', {}),
                        'buffers': data.get('buffers', [])
                    }
                    
                    await websocket.send(json.dumps(message_with_channel))
                except Exception as send_error:
                    debug_log(f"❌ [WebSocketBridge] Failed to send message via WebSocket", {
                        "msg_id": msg_id,
                        "instance_id": instance_id,
                        "kernel_id": kernel_id,
                        "msg_type": msg_type,
                        "error": str(send_error),
                        "error_type": type(send_error).__name__
                    })
                    
                    # Mark connection as failed
                    if kernel_id in self.jupyter_connections:
                        self.jupyter_connections[kernel_id]['websocket'] = None
                    
                    # Notify frontend about connection failure
                    await self._notify_connection_status(kernel_id, 'failed')
                    return False
                
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
            
            # Start connection health monitoring
            health_task = asyncio.create_task(self._monitor_connection_health(kernel_id, websocket))
            
            try:
                async for message in websocket:
                    try:
                        # Parse message
                        if isinstance(message, str):
                            data = json.loads(message)
                        else:
                            data = message
                        
                        # Extract channel from message according to Jupyter WebSocket protocol
                        # The channel is encoded in the message structure
                        channel = data.get('channel', 'shell')  # Default to shell if not specified
                        
                        # Remove channel from data to get the actual Jupyter message
                        jupyter_message = {k: v for k, v in data.items() if k != 'channel'}
                        
                        await self._handle_jupyter_message(kernel_id, jupyter_message, channel)
                        
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
            finally:
                # Cancel health monitoring task
                health_task.cancel()
                try:
                    await health_task
                except asyncio.CancelledError:
                    pass
                    
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

    async def _monitor_connection_health(self, kernel_id: str, websocket):
        """Monitor WebSocket connection health and handle reconnection."""
        try:
            while True:
                await asyncio.sleep(60)  # Check every minute
                
                # Check if websocket is still open
                if websocket.closed:
                    debug_log(f"🔌 [WebSocketBridge] WebSocket connection closed, attempting reconnection", {
                        "kernel_id": kernel_id
                    })
                    break
                
                # Send a ping to check connection health
                try:
                    pong_waiter = await websocket.ping()
                    await asyncio.wait_for(pong_waiter, timeout=5.0)
                    debug_log(f"💓 [WebSocketBridge] Connection health check passed", {
                        "kernel_id": kernel_id
                    })
                except asyncio.TimeoutError:
                    debug_log(f"⚠️ [WebSocketBridge] Connection health check timeout", {
                        "kernel_id": kernel_id
                    })
                    break
                except Exception as e:
                    debug_log(f"❌ [WebSocketBridge] Connection health check failed", {
                        "kernel_id": kernel_id,
                        "error": str(e)
                    })
                    break
                    
        except asyncio.CancelledError:
            debug_log(f"🔄 [WebSocketBridge] Connection health monitoring cancelled", {
                "kernel_id": kernel_id
            })
            raise
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error in connection health monitoring", {
                "kernel_id": kernel_id,
                "error": str(e)
            })

    async def _notify_connection_status(self, kernel_id: str, status: str):
        """Notify frontend about connection status changes."""
        try:
            if kernel_id in self.jupyter_connections:
                instance_ids = self.jupyter_connections[kernel_id].get('instance_ids', [])
                
                for instance_id in instance_ids:
                    if instance_id in self.frontend_connections:
                        # Update frontend connection status
                        self.frontend_connections[instance_id]['status'] = status
                        
                        # Notify frontend via broadcast callback
                        if self.broadcast_callback:
                            await self.broadcast_callback({
                                'action': 'connection_status',
                                'instance_id': instance_id,
                                'kernel_id': kernel_id,
                                'status': status,
                                'timestamp': datetime.datetime.now().isoformat()
                            })
                            
                        debug_log(f"📡 [WebSocketBridge] Connection status notification sent", {
                            "instance_id": instance_id,
                            "kernel_id": kernel_id,
                            "status": status
                        })
                        
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error notifying connection status", {
                "kernel_id": kernel_id,
                "status": status,
                "error": str(e)
            })
    
    async def _handle_jupyter_message(self, kernel_id: str, message: Dict[str, Any], channel: str = 'shell'):
        """Handle incoming message from Jupyter server."""
        try:
            # Extract message details
            msg_type = message.get('header', {}).get('msg_type', 'unknown')
            msg_id = message.get('header', {}).get('msg_id', 'unknown')
            parent_header = message.get('parent_header', {})
            parent_msg_id = parent_header.get('msg_id') if parent_header else None
            
            # ✅ CRITICAL FIX: Check for duplicate message processing
            if msg_id in self.processed_messages:
                debug_log(f"🔄 [WebSocketBridge] Skipping duplicate message", {
                    "kernel_id": kernel_id,
                    "channel": channel,
                    "msg_type": msg_type,
                    "msg_id": msg_id
                })
                return
            
            # Add to processed messages set
            self.processed_messages.add(msg_id)
            
            # For comm messages, also track by comm_id to prevent loops
            if msg_type in ['comm_open', 'comm_msg', 'comm_close']:
                comm_id = message.get('content', {}).get('comm_id')
                if comm_id:
                    if comm_id not in self.comm_message_tracker:
                        self.comm_message_tracker[comm_id] = set()
                    self.comm_message_tracker[comm_id].add(msg_id)
                    
                    debug_log(f"🔗 [WebSocketBridge] Tracking comm message", {
                        "kernel_id": kernel_id,
                        "comm_id": comm_id,
                        "msg_type": msg_type,
                        "msg_id": msg_id,
                        "total_tracked": len(self.comm_message_tracker[comm_id])
                    })
            
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
            
            # Handle pending message response (but don't return early!)
            if response_to_msg_id:
                await self._handle_response(response_to_msg_id, message)
                # ✅ CRITICAL FIX: Don't return here! Continue to forward the message
            
            # Handle different message types according to Jupyter protocol
            if msg_type == 'status':
                await self._handle_status_update(kernel_id, message)
            elif msg_type == 'kernel_info_reply':
                await self._handle_kernel_info(kernel_id, message)
            elif msg_type == 'comm_msg':
                # Handle comm messages and send echo responses
                await self._handle_comm_message(kernel_id, message, channel)
            elif msg_type == 'comm_open':
                # Handle comm open messages
                await self._handle_comm_open(kernel_id, message, channel)
            elif msg_type == 'comm_close':
                # Handle comm close messages
                await self._handle_comm_close(kernel_id, message, channel)
            else:
                # Forward all other messages to frontend with proper channel information
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
    
    async def _handle_comm_message(self, kernel_id: str, message: Dict[str, Any], channel: str):
        """Handle comm messages and send echo responses."""
        try:
            content = message.get('content', {})
            comm_id = content.get('comm_id')
            data = content.get('data', {})
            method = data.get('method')
            msg_id = message.get('header', {}).get('msg_id')
            
            debug_log(f"🔗 [WebSocketBridge] Comm message received", {
                "kernel_id": kernel_id,
                "comm_id": comm_id,
                "method": method,
                "channel": channel,
                "msg_id": msg_id,
                "direction": "kernel_to_frontend" if channel == 'iopub' else "frontend_to_kernel"
            })
            
            # Track the most recent comm message for this kernel
            if channel == 'shell':
                self.most_recent_comm_messages[kernel_id] = {
                    'msg_id': msg_id,
                    'comm_id': comm_id,
                    'method': method,
                    'timestamp': datetime.datetime.now().isoformat()
                }
                debug_log(f"📝 [WebSocketBridge] Updated most recent comm message for kernel", {
                    "kernel_id": kernel_id,
                    "msg_id": msg_id,
                    "comm_id": comm_id,
                    "method": method
                })
            
            # Forward the original comm message to frontend
            await self._forward_to_frontend(kernel_id, message, channel)
            
            # If this is a frontend-to-kernel update message, send an echo response
            if channel == 'shell' and method == 'update':
                original_msg_id = message.get('header', {}).get('msg_id')
                await self._send_comm_echo_response(kernel_id, comm_id, data.get('state', {}), original_msg_id)
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error handling comm message", {
                "kernel_id": kernel_id,
                "channel": channel,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _handle_comm_open(self, kernel_id: str, message: Dict[str, Any], channel: str):
        """Handle comm_open messages according to Jupyter protocol."""
        try:
            content = message.get('content', {})
            comm_id = content.get('comm_id')
            target_name = content.get('target_name')
            data = content.get('data', {})
            
            debug_log(f"🔗 [WebSocketBridge] Comm open received", {
                "kernel_id": kernel_id,
                "comm_id": comm_id,
                "target_name": target_name,
                "channel": channel,
                "direction": "kernel_to_frontend" if channel == 'iopub' else "frontend_to_kernel"
            })
            
            # Forward the comm_open message to frontend
            await self._forward_to_frontend(kernel_id, message, channel)
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error handling comm_open", {
                "kernel_id": kernel_id,
                "channel": channel,
                "error": str(e),
                "error_type": type(e).__name__
            })

    async def _handle_comm_close(self, kernel_id: str, message: Dict[str, Any], channel: str):
        """Handle comm_close messages according to Jupyter protocol."""
        try:
            content = message.get('content', {})
            comm_id = content.get('comm_id')
            data = content.get('data', {})
            
            debug_log(f"🔗 [WebSocketBridge] Comm close received", {
                "kernel_id": kernel_id,
                "comm_id": comm_id,
                "channel": channel,
                "direction": "kernel_to_frontend" if channel == 'iopub' else "frontend_to_kernel"
            })
            
            # Forward the comm_close message to frontend
            await self._forward_to_frontend(kernel_id, message, channel)
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error handling comm_close", {
                "kernel_id": kernel_id,
                "channel": channel,
                "error": str(e),
                "error_type": type(e).__name__
            })

    async def _send_comm_echo_response(self, kernel_id: str, comm_id: str, state: Dict[str, Any], original_msg_id: str = None):
        """Send an echo response for a comm message."""
        try:
            # Create echo response message
            echo_msg = {
                'header': {
                    'msg_id': f"comm_echo_{uuid.uuid4().hex[:8]}",
                    'msg_type': 'comm_msg',
                    'session': 'session',
                    'username': 'user',
                    'version': '5.3',
                    'date': datetime.datetime.now().isoformat()
                },
                'parent_header': {
                    'msg_id': original_msg_id or f"comm_{comm_id}",
                    'msg_type': 'comm_msg',
                    'session': 'session',
                    'username': 'user',
                    'version': '5.3',
                    'date': datetime.datetime.now().isoformat()
                },
                'metadata': {},
                'content': {
                    'comm_id': comm_id,
                    'data': {
                        'method': 'echo_update',
                        'state': state
                    }
                },
                'buffers': [],
                'channel': 'iopub'  # Echo responses go to IOPub channel
            }
            
            debug_log(f"🔄 [WebSocketBridge] Sending comm echo response", {
                "kernel_id": kernel_id,
                "comm_id": comm_id,
                "state": state,
                "channel": "iopub"
            })
            
            # Forward echo response to frontend on IOPub channel
            await self._forward_to_frontend(kernel_id, echo_msg, 'iopub')
            
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error sending comm echo response", {
                "kernel_id": kernel_id,
                "comm_id": comm_id,
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

                debug_log(f"🔍 [WebSocketBridge] Frontend connections", {
                    "frontend_connections": self.frontend_connections
                })
                
                # Look for a frontend connection that matches this session

                # frontend_connections is a dictionary of we
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
            
            # Add channel information to the message according to Jupyter WebSocket protocol
            # The channel must be encoded in the message structure as per Jupyter specification
            message_with_channel = {
                'action': 'websocket_message',
                'instanceId': instance_id,  # Use the actual instance ID
                'kernelId': kernel_id,
                'channel': channel,  # Channel name must be encoded in WebSocket messages
                'timestamp': datetime.datetime.now().isoformat(),
                # Include the original Jupyter message with channel information
                'msg': {
                    'channel': channel,  # Channel name as per Jupyter protocol
                    'header': message.get('header', {}),
                    'parent_header': message.get('parent_header', {}),
                    'metadata': message.get('metadata', {}),
                    'content': message.get('content', {}),
                    'buffers': message.get('buffers', [])
                }
            }
            
            # If this is an output message (stream, clear_output, etc.) and we have a recent comm message,
            # add the comm message info to help with routing
            msg_type = message.get('header', {}).get('msg_type')
            if msg_type in ['stream', 'clear_output', 'display_data', 'execute_result'] and kernel_id in self.most_recent_comm_messages:
                recent_comm = self.most_recent_comm_messages[kernel_id]
                time_since_comm = (datetime.datetime.now() - datetime.datetime.fromisoformat(recent_comm['timestamp'])).total_seconds()
                
                # Only include if the comm message was recent (within 10 seconds)
                if time_since_comm < 10:
                    message_with_channel['recent_comm_info'] = {
                        'msg_id': recent_comm['msg_id'],
                        'comm_id': recent_comm['comm_id'],
                        'method': recent_comm['method'],
                        'time_since_comm': time_since_comm
                    }
                    debug_log(f"📝 [WebSocketBridge] Added recent comm info to output message", {
                        "kernel_id": kernel_id,
                        "msg_type": msg_type,
                        "recent_comm_msg_id": recent_comm['msg_id'],
                        "recent_comm_id": recent_comm['comm_id'],
                        "time_since_comm": time_since_comm
                    })
            
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

    async def _cleanup_old_messages(self):
        """Clean up old processed messages to prevent memory leaks."""
        try:
            # Keep only the last 1000 processed messages
            if len(self.processed_messages) > 1000:
                # Convert to list and keep only the most recent 1000
                processed_list = list(self.processed_messages)
                self.processed_messages = set(processed_list[-1000:])
                
                debug_log(f"🧹 [WebSocketBridge] Cleaned up processed messages", {
                    "old_count": len(processed_list),
                    "new_count": len(self.processed_messages)
                })
            
            # Clean up comm message tracker (keep only active comms)
            if len(self.comm_message_tracker) > 100:
                # Remove comms with no recent activity
                current_time = datetime.datetime.now()
                comms_to_remove = []
                
                for comm_id, msg_ids in self.comm_message_tracker.items():
                    if len(msg_ids) > 50:  # Too many messages for one comm
                        comms_to_remove.append(comm_id)
                
                for comm_id in comms_to_remove:
                    del self.comm_message_tracker[comm_id]
                
                if comms_to_remove:
                    debug_log(f"🧹 [WebSocketBridge] Cleaned up comm message tracker", {
                        "removed_comms": len(comms_to_remove),
                        "remaining_comms": len(self.comm_message_tracker)
                    })
                    
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error during message cleanup", {
                "error": str(e),
                "error_type": type(e).__name__
            })

    async def _cleanup_kernel_messages(self, kernel_id: str):
        """Clean up message tracking for a specific kernel."""
        try:
            # Remove pending messages for this kernel
            pending_to_remove = []
            for msg_id, pending_msg in self.pending_messages.items():
                if pending_msg.get('kernel_id') == kernel_id:
                    pending_to_remove.append(msg_id)
            
            for msg_id in pending_to_remove:
                del self.pending_messages[msg_id]
            
            if pending_to_remove:
                debug_log(f"🧹 [WebSocketBridge] Cleaned up pending messages for kernel", {
                    "kernel_id": kernel_id,
                    "removed_count": len(pending_to_remove)
                })
                
        except Exception as e:
            debug_log(f"❌ [WebSocketBridge] Error cleaning up kernel messages", {
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
