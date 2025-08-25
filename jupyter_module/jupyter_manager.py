"""
Unified Jupyter manager for TensorDock server.
Coordinates kernel, session, and WebSocket management.
"""

import asyncio
import json
import datetime
from typing import Optional, Dict, Any, Callable

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log
from core.config import ServerConfig
from .kernel_manager import KernelManager
from .session_manager import SessionManager
# from .websocket_manager import WebSocketManager # Removed as WebSocket management is now handled by bridge


class JupyterManager(LoggerMixin):
    """Unified manager for Jupyter integration."""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        
        # Component managers
        self.session_manager = SessionManager(config)
        self.kernel_manager = KernelManager(config)
        # Note: WebSocket management is now handled by the WebSocket bridge service
        
        # State
        self.initialized = False
        self.initialization_task = None
        
        # Message handling
        self.message_handlers: Dict[str, Callable] = {}
        self.broadcast_callback: Optional[Callable] = None
        
        # Tasks
        self.message_listener_task = None
    
    async def initialize(self) -> bool:
        """Initialize the Jupyter manager and create kernel."""
        try:
            debug_log(f"🚀 [Jupyter] Initializing Jupyter manager")
            
            # Check if we already have a kernel to prevent duplicates
            if self.initialized and self.kernel_manager.kernel_id:
                debug_log(f"⚠️ [Jupyter] Already initialized with kernel, skipping duplicate creation", {
                    "existing_kernel_id": self.kernel_manager.kernel_id,
                    "initialized": self.initialized
                })
                print(f"⚠️ [Jupyter] Already initialized with kernel: {self.kernel_manager.kernel_id}")
                return True
            
            # Create session
            session_id = await self.session_manager.create_session()
            
            # Create kernel
            kernel_id = await self.kernel_manager.create_kernel()
            
            # Connect WebSocket
            # ws_url = self.config.get_ws_url(kernel_id, session_id) # Removed as WebSocket management is now handled by bridge
            # headers = self.config.get_jupyter_headers() # Removed as WebSocket management is now handled by bridge
            
            # connected = await self.websocket_manager.connect(ws_url, headers) # Removed as WebSocket management is now handled by bridge
            # if not connected: # Removed as WebSocket management is now handled by bridge
            #     raise Exception("Failed to connect WebSocket") # Removed as WebSocket management is now handled by bridge
            
            # CRITICAL: Set broadcast callback for WebSocket manager to send messages to frontend # Removed as WebSocket management is now handled by bridge
            # if hasattr(self, 'broadcast_callback') and self.broadcast_callback: # Removed as WebSocket management is now handled by bridge
            #     self.websocket_manager.set_broadcast_callback(self.broadcast_callback) # Removed as WebSocket management is now handled by bridge
            #     debug_log(f"📡 [Jupyter] WebSocket broadcast callback set") # Removed as WebSocket management is now handled by bridge
            #     print(f"📡 [Jupyter] WebSocket broadcast callback set") # Removed as WebSocket management is now handled by bridge
            
            # Start message listener # Removed as WebSocket management is now handled by bridge
            # self.message_listener_task = asyncio.create_task( # Removed as WebSocket management is now handled by bridge
            #     self.websocket_manager.listen_for_messages(self._handle_kernel_message) # Removed as WebSocket management is now handled by bridge
            # ) # Removed as WebSocket management is now handled by bridge
            
            self.initialized = True
            
            debug_log(f"🚀 [Jupyter] Jupyter manager initialized successfully", {
                "session_id": session_id,
                "kernel_id": kernel_id,
                # "ws_connected": connected # Removed as WebSocket management is now handled by bridge
            })
            
            return True
            
        except Exception as e:
            debug_log(f"❌ [Jupyter] Failed to initialize Jupyter manager", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    async def _handle_kernel_message(self, message: str):
        """Handle incoming kernel messages."""
        try:
            # Parse message
            msg = json.loads(message)
            msg_type = msg.get('header', {}).get('msg_type', 'unknown')
            
            debug_log(f"📥 [Jupyter] Kernel message received", {
                "msg_type": msg_type,
                "msg_id": msg.get('header', {}).get('msg_id', 'unknown')
            })
            
            print(f"📥 [Jupyter] Kernel message: {msg_type}")
            
            # Store in kernel response queue for processing
            await self.kernel_manager.response_queue.put(msg)
            
        except Exception as e:
            debug_log(f"❌ [Jupyter] Error handling kernel message", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            print(f"❌ [Jupyter] Error handling kernel message: {e}")
    
    async def execute_code(self, code: str, cell_id: str) -> Optional[str]:
        """Execute Python code in the kernel."""
        if not self.initialized:
            await self.initialize()
        
        try:
            debug_log(f"⚡ [Jupyter] Executing code", {
                "cell_id": cell_id,
                "code_length": len(code)
            })
            
            # Send execute request through WebSocket
            msg_id = await self._send_execute_request(code, cell_id)
            
            # Wait for execution reply
            execution_count = await self._wait_for_execution_reply(msg_id)
            
            debug_log(f"⚡ [Jupyter] Code execution completed", {
                "cell_id": cell_id,
                "execution_count": execution_count,
                "msg_id": msg_id
            })
            
            return execution_count
            
        except Exception as e:
            debug_log(f"❌ [Jupyter] Code execution failed", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            return None
    
    async def _send_execute_request(self, code: str, cell_id: str) -> str:
        """Send execute request to kernel."""
        msg_id = str(hash(f"{cell_id}_{datetime.datetime.now().isoformat()}"))
        
        msg = {
            'header': {
                'msg_id': msg_id,
                'msg_type': 'execute_request',
                'username': 'user',
                'session': 'session',
                'date': datetime.datetime.now().isoformat(),
                'version': '5.0'
            },
            'parent_header': {},
            'metadata': {},
            'content': {
                'code': code,
                'silent': False,
                'store_history': True,
                'user_expressions': {},
                'allow_stdin': False
            }
        }
        
        # success = await self.websocket_manager.send_message(msg) # Removed as WebSocket management is now handled by bridge
        # if not success: # Removed as WebSocket management is now handled by bridge
        #     raise Exception("Failed to send execute request") # Removed as WebSocket management is now handled by bridge
        
        return msg_id
    
    async def _wait_for_execution_reply(self, msg_id: str) -> Optional[int]:
        """Wait for execution reply from kernel."""
        timeout = 30  # 30 second timeout
        start_time = datetime.datetime.now()
        
        while (datetime.datetime.now() - start_time).seconds < timeout:
            if not self.kernel_manager.response_queue.empty():
                msg = await self.kernel_manager.response_queue.get()
                
                if (msg.get('parent_header', {}).get('msg_id') == msg_id and 
                    msg.get('msg_type') == 'execute_reply'):
                    execution_count = msg['content'].get('execution_count')
                    self.kernel_manager.execution_count = execution_count
                    return execution_count
            
            await asyncio.sleep(0.1)
        
        debug_log(f"⏰ [Jupyter] Execution reply timeout", {
            "msg_id": msg_id,
            "timeout_seconds": timeout
        })
        return None
    
    async def send_kernel_message(self, message: Dict[str, Any]) -> bool:
        """Send a message to the kernel via WebSocket bridge."""
        if not self.can_handle_kernel_messages():
            debug_log(f"❌ [Jupyter] Cannot send message, not ready for kernel messages", {
                "initialized": self.initialized,
                "kernel_id": self.kernel_manager.kernel_id if self.kernel_manager else None
            })
            print(f"❌ [Jupyter] Cannot send message, not ready for kernel messages")
            print(f"❌ [Jupyter] Initialized: {self.initialized}")
            print(f"❌ [Jupyter] Kernel ID: {self.kernel_manager.kernel_id if self.kernel_manager else None}")
            return False
        
        try:
            # Extract message details
            msg_type = message.get('header', {}).get('msg_type', 'unknown')
            msg_id = message.get('header', {}).get('msg_id', 'unknown')
            
            debug_log(f"📤 [Jupyter] Sending kernel message via WebSocket bridge", {
                "msg_type": msg_type,
                "msg_id": msg_id,
                "kernel_id": self.kernel_manager.kernel_id
            })
            
            # Send message through WebSocket bridge
            if hasattr(self, 'websocket_bridge') and self.websocket_bridge:
                # Create a message with the format expected by WebSocket bridge
                bridge_message = {
                    'instanceId': f"instance_{msg_id}",
                    'kernelId': self.kernel_manager.kernel_id,
                    'data': message
                }
                
                success = await self.websocket_bridge.send_message(
                    bridge_message['instanceId'],
                    self.kernel_manager.kernel_id,
                    bridge_message['data']
                )
                
                if success:
                    debug_log(f"✅ [Jupyter] Message sent via WebSocket bridge", {
                        "msg_type": msg_type,
                        "msg_id": msg_id
                    })
                    return True
                else:
                    debug_log(f"❌ [Jupyter] Failed to send message via WebSocket bridge", {
                        "msg_type": msg_type,
                        "msg_id": msg_id
                    })
                    return False
            else:
                debug_log(f"❌ [Jupyter] WebSocket bridge not available", {
                    "msg_type": msg_type,
                    "msg_id": msg_id
                })
                print(f"❌ [Jupyter] WebSocket bridge not available")
                return False
                
        except Exception as e:
            debug_log(f"❌ [Jupyter] Error sending kernel message", {
                "error": str(e),
                "error_type": type(e).__name__,
                "message": message
            })
            print(f"❌ [Jupyter] Error sending kernel message: {e}")
            return False
    
    async def restart_kernel(self) -> bool:
        """Restart the current kernel."""
        try:
            debug_log(f"🔄 [Jupyter] Restarting kernel")
            
            # Cleanup existing components
            await self.cleanup()
            
            # Reinitialize
            success = await self.initialize()
            
            if success:
                debug_log(f"🔄 [Jupyter] Kernel restarted successfully")
            else:
                debug_log(f"❌ [Jupyter] Kernel restart failed")
            
            return success
            
        except Exception as e:
            debug_log(f"❌ [Jupyter] Kernel restart error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    def set_broadcast_callback(self, callback: Callable):
        """Set the callback for broadcasting messages to clients."""
        self.broadcast_callback = callback
        
        debug_log(f"📡 [Jupyter] Broadcast callback set")
    
    def set_websocket_bridge(self, websocket_bridge):
        """Set the WebSocket bridge reference for sending kernel messages."""
        self.websocket_bridge = websocket_bridge
        
        debug_log(f"🔌 [Jupyter] WebSocket bridge reference set")
        print(f"🔌 [Jupyter] WebSocket bridge reference set")
    
    def can_handle_kernel_messages(self) -> bool:
        """Check if the manager can handle kernel messages."""
        return (self.initialized and 
                # self.websocket_manager and # Removed as WebSocket management is now handled by bridge
                # self.websocket_manager.is_connected() and # Removed as WebSocket management is now handled by bridge
                self.kernel_manager and 
                self.kernel_manager.kernel_id)
    
    def get_kernel_id(self) -> Optional[str]:
        """Get the current kernel ID."""
        return self.kernel_manager.kernel_id if self.kernel_manager else None
    
    async def create_kernel(self) -> str:
        """Create a new kernel using the same pattern as initialization."""
        try:
            debug_log(f"🚀 [Jupyter] Creating new kernel from action processor")
            
            # CRITICAL: Check if we already have a kernel to prevent duplicates
            if self.kernel_manager.kernel_id:
                debug_log(f"⚠️ [Jupyter] Kernel already exists, returning existing ID", {
                    "existing_kernel_id": self.kernel_manager.kernel_id
                })
                print(f"⚠️ [Jupyter] Kernel already exists: {self.kernel_manager.kernel_id}")
                return self.kernel_manager.kernel_id
            
            # CRITICAL: Check if we're already initialized
            if self.initialized:
                debug_log(f"⚠️ [Jupyter] Already initialized, returning existing kernel", {
                    "kernel_id": self.kernel_manager.kernel_id
                })
                return self.kernel_manager.kernel_id
            
            # Only create a new kernel if we don't have one and aren't initialized
            debug_log(f"🚀 [Jupyter] No existing kernel found, creating new one")
            
            # Create session
            session_id = await self.session_manager.create_session()
            
            # Create kernel
            kernel_id = await self.kernel_manager.create_kernel()
            
            # Connect WebSocket
            # ws_url = self.config.get_ws_url(kernel_id, session_id) # Removed as WebSocket management is now handled by bridge
            # headers = self.config.get_jupyter_headers() # Removed as WebSocket management is now handled by bridge
            
            # connected = await self.websocket_manager.connect(ws_url, headers) # Removed as WebSocket management is now handled by bridge
            # if not connected: # Removed as WebSocket management is now handled by bridge
            #     raise Exception("Failed to connect WebSocket") # Removed as WebSocket management is now handled by bridge
            
            # Set broadcast callback for WebSocket manager # Removed as WebSocket management is now handled by bridge
            # if self.broadcast_callback: # Removed as WebSocket management is now handled by bridge
            #     self.websocket_manager.set_broadcast_callback(self.broadcast_callback) # Removed as WebSocket management is now handled by bridge
            #     debug_log(f"📡 [Jupyter] WebSocket broadcast callback set for new kernel") # Removed as WebSocket management is now handled by bridge
            
            # Start message listener if not already running # Removed as WebSocket management is now handled by bridge
            # if not self.message_listener_task or self.message_listener_task.done(): # Removed as WebSocket management is now handled by bridge
            #     self.message_listener_task = asyncio.create_task( # Removed as WebSocket management is now handled by bridge
            #         self.websocket_manager.listen_for_messages(self._handle_kernel_message) # Removed as WebSocket management is now handled by bridge
            #     ) # Removed as WebSocket management is now handled by bridge
            
            # Mark as initialized # Removed as WebSocket management is now handled by bridge
            self.initialized = True # Removed as WebSocket management is now handled by bridge
            
            debug_log(f"🚀 [Jupyter] New kernel created successfully", {
                "session_id": session_id,
                "kernel_id": kernel_id,
                # "ws_connected": connected # Removed as WebSocket management is now handled by bridge
            })
            
            return kernel_id
            
        except Exception as e:
            debug_log(f"❌ [Jupyter] Failed to create new kernel", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            raise
    
    async def cleanup(self):
        """Clean up resources."""
        try:
            debug_log(f"🧹 [Jupyter] Cleaning up Jupyter manager")
            
            # Cancel tasks
            if self.message_listener_task:
                self.message_listener_task.cancel()
                try:
                    await self.message_listener_task
                except asyncio.CancelledError:
                    pass
            
            # Cleanup components
            # if self.websocket_manager: # Removed as WebSocket management is now handled by bridge
            #     await self.websocket_manager.cleanup() # Removed as WebSocket management is now handled by bridge
            
            if self.kernel_manager:
                await self.kernel_manager.cleanup()
            
            if self.session_manager:
                await self.session_manager.cleanup()
            
            # Reset state
            self.initialized = False
            self.message_listener_task = None
            
            debug_log(f"🧹 [Jupyter] Jupyter manager cleanup completed")
            
        except Exception as e:
            debug_log(f"❌ [Jupyter] Cleanup error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the Jupyter manager."""
        return {
            'initialized': self.initialized,
            'kernel_id': self.kernel_manager.kernel_id if self.kernel_manager else None,
            # 'websocket_connected': self.websocket_manager.is_connected() if self.websocket_manager else False, # Removed as WebSocket management is now handled by bridge
            'session_id': self.session_manager.get_session_id() if hasattr(self.session_manager, 'get_session_id') else None,
            'message_listener_active': self.message_listener_task and not self.message_listener_task.done()
        }
