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
        self.send_to_client: Optional[Callable] = None
        
        # Tasks
        self.message_listener_task = None
        self.watchdog_task = None
        self.watchdog_interval_sec = 10
    
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
            
            
            self.initialized = True
            
            debug_log(f"🚀 [Jupyter] Jupyter manager initialized successfully", {
                "session_id": session_id,
                "kernel_id": kernel_id,
                # "ws_connected": connected # Removed as WebSocket management is now handled by bridge
            })
            
            # Start watchdog to auto-heal session/kernel if they die
            self._start_watchdog()

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

    def _start_watchdog(self):
        """Start periodic watchdog ensuring a valid session and an alive kernel."""
        if self.watchdog_task and not self.watchdog_task.done():
            return
        self.watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def _watchdog_loop(self):
        while True:
            try:
                await asyncio.sleep(self.watchdog_interval_sec)

                # Ensure session exists and is valid
                sid = self.session_manager.get_session_id()
                if not sid or not await self.session_manager.validate_session(sid):
                    debug_log(f"🛠️ [Jupyter] Watchdog creating default session (tmp.ipynb)")
                    try:
                        await self.session_manager.create_session()
                    except Exception:
                        continue  # try again next tick

                # Ensure kernel exists and is alive
                kid = self.kernel_manager.kernel_id if hasattr(self.kernel_manager, 'kernel_id') else None
                kernel_ok = False
                if kid:
                    kernel_ok = await self.session_manager.validate_kernel(kid)

                if not kernel_ok:
                    debug_log(f"🛠️ [Jupyter] Watchdog restarting kernel for default session")
                    try:
                        # Prefer creating kernel tied to current session
                        await self.kernel_manager.cleanup()
                        await self.kernel_manager.create_kernel(self.session_manager)
                        self.initialized = True
                    except Exception:
                        # As fallback, re-run full initialize
                        await self.initialize()

            except asyncio.CancelledError:
                break
            except Exception as e:
                debug_log(f"❌ [Jupyter] Watchdog error", {"error": str(e), "error_type": type(e).__name__})
                # continue loop
    
    def set_broadcast_callback(self, callback: Callable):
        """Set the callback for broadcasting messages to clients."""
        self.broadcast_callback = callback
        
        debug_log(f"📡 [Jupyter] Broadcast callback set")

    def set_send_to_client(self, send_to_client: Callable):
        """Set the callback for sending messages to clients."""
        self.send_to_client = send_to_client
        
        debug_log(f"📡 [Jupyter] Send to client callback set")
    
    def set_websocket_bridge(self, websocket_bridge):
        """Set the WebSocket bridge reference for sending kernel messages."""
        self.websocket_bridge = websocket_bridge
        
        debug_log(f"🔌 [Jupyter] WebSocket bridge reference set")
        print(f"🔌 [Jupyter] WebSocket bridge reference set")
    
    def can_handle_kernel_messages(self) -> bool:
        """Check if the manager can handle kernel messages."""
        return (self.initialized and 
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
            
            # Delegate kernel creation to KernelManager with SessionManager
            kernel_id = await self.kernel_manager.create_kernel(self.session_manager)
            
            # Mark as initialized
            self.initialized = True
            
            debug_log(f"🚀 [Jupyter] New kernel created successfully", {
                "kernel_id": kernel_id,
                "status": "connected"
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
            
            if self.kernel_manager:
                await self.kernel_manager.cleanup()
            
            if self.session_manager:
                await self.session_manager.cleanup()
            
            if self.watchdog_task:
                self.watchdog_task.cancel()
                try:
                    await self.watchdog_task
                except asyncio.CancelledError:
                    pass
                self.watchdog_task = None

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
            'session_id': self.session_manager.get_session_id() if hasattr(self.session_manager, 'get_session_id') else None,
            'message_listener_active': self.message_listener_task and not self.message_listener_task.done()
        }
