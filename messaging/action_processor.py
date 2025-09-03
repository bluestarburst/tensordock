"""
Action processor for TensorDock server.
Handles specific action types and integrates with other modules.
"""

import asyncio
import json
import datetime
from typing import Dict, Any, Optional, Callable, Set

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log


class ActionProcessor(LoggerMixin):
    """Processes specific action types and integrates with other modules."""
    
    def __init__(self):
        # External module references (to be set by server)
        self.jupyter_manager = None
        self.broadcast_callback = None
        self.http_proxy_service = None
        self.canvas_service = None
        self.widget_service = None
        self.websocket_bridge = None
        self.peer_manager = None
        
        # Action handlers
        self.action_handlers: Dict[str, Callable] = {}
        
        # Action statistics
        self.action_stats = {
            'total_actions': 0,
            'actions_by_type': {},
            'successful_actions': 0,
            'failed_actions': 0,
            'start_time': datetime.datetime.now()
        }
        
        # ✅ CRITICAL FIX: Add message deduplication tracking
        self.processed_comm_messages: Set[str] = set()  # Track processed comm message IDs
        self.comm_message_tracker: Dict[str, Set[str]] = {}  # comm_id -> set of processed msg_ids
        
        # Register default handlers
        self._register_default_handlers()
        
        debug_log(f"⚙️ [ActionProcessor] Action processor initialized")
    
    def set_jupyter_manager(self, jupyter_manager):
        """Set the Jupyter manager reference."""
        self.jupyter_manager = jupyter_manager
        
        debug_log(f"🔗 [ActionProcessor] Jupyter manager reference set")
    
    def set_broadcast_callback(self, broadcast_callback: Callable):
        """Set the broadcast callback function."""
        self.broadcast_callback = broadcast_callback
        
        debug_log(f"🔗 [ActionProcessor] Broadcast callback set")
    
    def set_http_proxy_service(self, http_proxy_service):
        """Set the HTTP proxy service reference."""
        self.http_proxy_service = http_proxy_service
        
        debug_log(f"🔗 [ActionProcessor] HTTP proxy service reference set")
    
    def set_canvas_service(self, canvas_service):
        """Set the canvas service reference."""
        self.canvas_service = canvas_service
        
        debug_log(f"🔗 [ActionProcessor] Canvas service reference set")
    
    def set_widget_service(self, widget_service):
        """Set the widget service reference."""
        self.widget_service = widget_service
        
        debug_log(f"🔗 [ActionProcessor] Widget service reference set")
    
    def set_websocket_bridge(self, websocket_bridge):
        """Set the WebSocket bridge service."""
        self.websocket_bridge = websocket_bridge
        debug_log(f"🔌 [ActionProcessor] WebSocket bridge service set")
    
    def set_peer_manager(self, peer_manager):
        """Set the peer manager."""
        self.peer_manager = peer_manager
        debug_log(f"🔗 [ActionProcessor] Peer manager set")
    
    def _register_default_handlers(self):
        """Register default action handlers."""
        self.register_handler('execute_code', self._handle_execute_code)
        self.register_handler('comm_msg', self._handle_comm_msg)
        self.register_handler('kernel_message', self._handle_kernel_message)
        self.register_handler('start_kernel', self._handle_start_kernel)
        self.register_handler('restart_kernel', self._handle_restart_kernel)
        self.register_handler('interrupt_kernel', self._handle_interrupt_kernel)
        self.register_handler('input', self._handle_input)
        self.register_handler('sudo_http_request', self._handle_sudo_http_request)
        self.register_handler('canvas_data', self._handle_canvas_data)
        
        # WebSocket handlers
        self.register_handler('websocket_connect', self._handle_websocket_connect)
        self.register_handler('websocket_message', self._handle_websocket_message)
        self.register_handler('websocket_close', self._handle_websocket_close)
        
        debug_log(f"➕ [ActionProcessor] Default handlers registered", {
            "total_handlers": len(self.action_handlers)
        })
    
    def register_handler(self, action: str, handler: Callable):
        """Register a handler for a specific action."""
        self.action_handlers[action] = handler
        
        debug_log(f"➕ [ActionProcessor] Action handler registered", {
            "action": action,
            "handler": handler.__name__,
            "total_handlers": len(self.action_handlers)
        })
    
    def unregister_handler(self, action: str):
        """Unregister an action handler."""
        if action in self.action_handlers:
            del self.action_handlers[action]
            
            debug_log(f"➖ [ActionProcessor] Action handler unregistered", {
                "action": action,
                "total_handlers": len(self.action_handlers)
            })
    
    async def process_action(self, action: Dict[str, Any]) -> bool:
        """Process a single action."""
        try:
            action_type = action.get('action', 'unknown')
            
            debug_log(f"⚙️ [ActionProcessor] Processing action", {
                "action": action_type,
                "action_keys": list(action.keys()),
                "timestamp": datetime.datetime.now().isoformat()
            })
            
            # Update statistics
            self.action_stats['total_actions'] += 1
            self.action_stats['actions_by_type'][action_type] = self.action_stats['actions_by_type'].get(action_type, 0) + 1
            
            # Check if we have a handler for this action
            if action_type in self.action_handlers:
                handler = self.action_handlers[action_type]
                
                try:
                    # Execute handler
                    result = await handler(action)
                    
                    self.action_stats['successful_actions'] += 1
                    
                    debug_log(f"✅ [ActionProcessor] Action processed successfully", {
                        "action": action_type,
                        "result": result
                    })
                    
                    return True
                    
                except Exception as e:
                    self.action_stats['failed_actions'] += 1
                    
                    debug_log(f"❌ [ActionProcessor] Action handler error", {
                        "action": action_type,
                        "error": str(e),
                        "error_type": type(e).__name__
                    })
                    
                    return False
            else:
                self.action_stats['failed_actions'] += 1
                
                debug_log(f"❌ [ActionProcessor] No handler for action", {
                    "action": action_type,
                    "available_handlers": list(self.action_handlers.keys())
                })
                
                return False
                
        except Exception as e:
            self.action_stats['failed_actions'] += 1
            
            debug_log(f"❌ [ActionProcessor] Action processing error", {
                "error": str(e),
                "error_type": type(e).__name__,
                "action": action
            })
            
            return False
    
    async def _handle_execute_code(self, action: Dict[str, Any]) -> Optional[str]:
        """Handle code execution action."""
        if not self.jupyter_manager:
            raise Exception("Jupyter manager not available")
        
        code = action.get('code', '')
        cell_id = action.get('cell_id', 'unknown')
        
        debug_log(f"⚡ [ActionProcessor] Executing code", {
            "cell_id": cell_id,
            "code_length": len(code)
        })
        
        execution_count = await self.jupyter_manager.execute_code(code, cell_id)
        
        if execution_count is not None and self.broadcast_callback:
            await self.broadcast_callback({
                'action': 'execution_complete',
                'cell_id': cell_id,
                'execution_count': execution_count
            })
        
        return execution_count
    
    async def _handle_comm_msg(self, action: Dict[str, Any]):
        """Handle comm message action with proper Jupyter integration."""
        instance_id = action.get('instanceId')
        kernel_id = action.get('kernelId')
        
        if not instance_id or not kernel_id:
            raise ValueError("Missing instanceId or kernelId in comm message")
        
        # Extract Jupyter message from action
        jupyter_message = {
            'header': action.get('header', {}),
            'content': action.get('content', {}),
            'metadata': action.get('metadata', {}),
            'buffers': action.get('buffers', [])
        }
        
        # ✅ CRITICAL FIX: Check for duplicate comm message processing
        msg_id = jupyter_message.get('header', {}).get('msg_id')
        comm_id = jupyter_message.get('content', {}).get('comm_id')
        
        if msg_id and msg_id in self.processed_comm_messages:
            debug_log(f"🔄 [ActionProcessor] Skipping duplicate comm message", {
                "instance_id": instance_id,
                "kernel_id": kernel_id,
                "msg_id": msg_id,
                "comm_id": comm_id
            })
            return {"success": True, "message": "Duplicate comm message skipped"}
        
        # Track processed message
        if msg_id:
            self.processed_comm_messages.add(msg_id)
        
        # Track comm messages by comm_id
        if comm_id:
            if comm_id not in self.comm_message_tracker:
                self.comm_message_tracker[comm_id] = set()
            if msg_id:
                self.comm_message_tracker[comm_id].add(msg_id)
        
        debug_log(f"💬 [ActionProcessor] Enhanced comm message handling", {
            "instance_id": instance_id,
            "kernel_id": kernel_id,
            "msg_type": jupyter_message.get('header', {}).get('msg_type'),
            "comm_id": comm_id,
            "target_name": jupyter_message.get('content', {}).get('target_name'),
            "msg_id": msg_id
        })
        
        # Forward to WebSocket bridge for proper Jupyter handling
        if self.websocket_bridge:
            success = await self.websocket_bridge.send_message(instance_id, kernel_id, jupyter_message)
            if not success:
                debug_log(f"❌ [ActionProcessor] Failed to forward comm message to Jupyter")
        
        # Also track in widget service for state management
        if self.widget_service:
            try:
                await self.widget_service.handle_jupyter_comm_message(kernel_id, jupyter_message)
            except AttributeError:
                # Fallback to legacy method if enhanced widget service not available
                data = jupyter_message.get('content', {}).get('data', {})
                client_id = action.get('client_id', 'unknown')
                result = await self.widget_service.handle_comm_message(comm_id, data, client_id)
                
                if result.get('success') and self.broadcast_callback:
                    await self.broadcast_callback({
                        'action': 'comm_msg_processed',
                        'comm_id': comm_id,
                        'result': result
                    })
                
                return result
        
        return {"success": True, "message": "Comm message processed via WebSocket bridge"}
    
    async def _handle_kernel_message(self, action: Dict[str, Any]) -> bool:
        """Handle kernel message action via WebSocket bridge."""
        if not hasattr(self, 'websocket_bridge') or not self.websocket_bridge:
            raise Exception("WebSocket bridge service not available")
        
        # Extract message details from the action
        instance_id = action.get('instanceId')
        kernel_id = action.get('kernelId')
        data = action.get('data')  # The Jupyter message is in the 'data' field
        channel = action.get('channel')  # The channel information from frontend
        
        debug_log(f"🔍 [ActionProcessor] Kernel message via WebSocket bridge", {
            "instance_id": instance_id,
            "kernel_id": kernel_id,
            "has_data": data is not None,
            "data_type": type(data).__name__ if data else 'None'
        })
        
        if not instance_id or not data:
            debug_log(f"❌ [ActionProcessor] Missing required fields for kernel message", {
                "instance_id": instance_id,
                "has_data": data is not None
            })
            return False
        
        try:
            # Extract message details from the Jupyter message data
            msg_type = data.get('header', {}).get('msg_type', 'unknown')
            msg_id = data.get('header', {}).get('msg_id', 'unknown')
            session_id = data.get('header', {}).get('session', 'unknown')
            
            debug_log(f"🔍 [ActionProcessor] Jupyter message details", {
                "msg_type": msg_type,
                "msg_id": msg_id,
                "session_id": session_id,
                "channel": channel
            })
            
            # CRITICAL: Extract session ID from the kernel message and update WebSocket bridge
            if session_id and session_id != 'unknown':
                debug_log(f"🔍 [ActionProcessor] Extracted session ID from kernel message: {session_id}")
                
                # Update the WebSocket bridge with the session ID for this instance
                self.websocket_bridge.update_session_id(instance_id, session_id)
            else:
                debug_log(f"⚠️ [ActionProcessor] No valid session ID found in kernel message header")
            
            # Send message via WebSocket bridge with channel information
            success = await self.websocket_bridge.send_message(instance_id, kernel_id or 'default', data, channel)
            
            if success:
                debug_log(f"✅ [ActionProcessor] Kernel message sent via WebSocket bridge", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id,
                    "msg_type": msg_type,
                    "session_id": session_id,
                    "channel": channel
                })
                return True
            else:
                debug_log(f"❌ [ActionProcessor] Failed to send kernel message via WebSocket bridge", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id
                })
                return False
                
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error sending kernel message via WebSocket bridge", {
                "instance_id": instance_id,
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    async def _route_kernel_message_via_http(self, target_kernel_id: str, message_data: Any) -> bool:
        """Route a kernel message to a specific kernel via HTTP API."""
        try:
            debug_log(f"🌐 [ActionProcessor] Routing kernel message via HTTP", {
                "target_kernel_id": target_kernel_id,
                "message_type": "kernel_info_request"
            })
            print(f"🌐 [ActionProcessor] Routing kernel message via HTTP to kernel: {target_kernel_id}")
            
            # Create a temporary WebSocket connection to the target kernel
            # This is a simplified approach - in production you might want to maintain a pool
            
            # For now, we'll just acknowledge that we received the request
            # and let the client handle the response through the HTTP API
            
            if self.broadcast_callback:
                # Broadcast a message indicating that the kernel is available
                await self.broadcast_callback({
                    'action': 'kernel_available',
                    'kernel_id': target_kernel_id,
                    'message': 'Kernel is available via HTTP API'
                })
            
            debug_log(f"✅ [ActionProcessor] Kernel message routed via HTTP", {
                "target_kernel_id": target_kernel_id
            })
            return True
            
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Failed to route kernel message via HTTP", {
                "target_kernel_id": target_kernel_id,
                "error": str(e)
            })
            print(f"❌ [ActionProcessor] Failed to route kernel message via HTTP: {e}")
            return False
    
    async def _handle_start_kernel(self, action: Dict[str, Any]):
        """Handle start kernel action."""
        if not self.jupyter_manager:
            raise Exception("Jupyter manager not available")
        
        debug_log(f"🚀 [ActionProcessor] Starting kernel")
        
        # CRITICAL FIX: Check if we already have a kernel to prevent duplicates
        existing_kernel_id = self.jupyter_manager.get_kernel_id()
        if existing_kernel_id:
            debug_log(f"⚠️ [ActionProcessor] Kernel already exists, returning existing ID", {
                "existing_kernel_id": existing_kernel_id
            })
            print(f"⚠️ [ActionProcessor] Kernel already exists: {existing_kernel_id}")
            
            if self.broadcast_callback:
                await self.broadcast_callback({
                    'action': 'kernel_started',
                    'kernel_id': existing_kernel_id,
                    'status': 'existing'
                })
            
            return existing_kernel_id
        
        # Only create a new kernel if we don't have one
        kernel_id = await self.jupyter_manager.create_kernel()
        
        if self.broadcast_callback:
            await self.broadcast_callback({
                'action': 'kernel_started',
                'kernel_id': kernel_id,
                'status': 'new'
            })
        
        return kernel_id
    
    async def _handle_restart_kernel(self, action: Dict[str, Any]):
        """Handle restart kernel action."""
        if not self.jupyter_manager:
            raise Exception("Jupyter manager not available")
        
        debug_log(f"🔄 [ActionProcessor] Restarting kernel")
        
        success = await self.jupyter_manager.restart_kernel()
        
        if success and self.broadcast_callback:
            await self.broadcast_callback({
                'action': 'kernel_restarted'
            })
        
        return success
    
    async def _handle_interrupt_kernel(self, action: Dict[str, Any]):
        """Handle interrupt kernel action."""
        debug_log(f"⏹️ [ActionProcessor] Interrupting kernel")
        
        # TODO: Implement kernel interruption
        # This would integrate with Jupyter manager
        
        if self.broadcast_callback:
            await self.broadcast_callback({
                'action': 'kernel_interrupted'
            })
        
        return True
    
    async def _handle_input(self, action: Dict[str, Any]):
        """Handle input action."""
        input_data = action.get('input', '')
        
        debug_log(f"⌨️ [ActionProcessor] Input received", {
            "input_length": len(input_data) if input_data else 0
        })
        
        # TODO: Implement input handling
        # This would integrate with kernel input system
        
        return True
    
    async def _handle_sudo_http_request(self, action: Dict[str, Any]) -> bool:
        """Handle sudo HTTP request action."""
        try:
            url = action.get('url')
            method = action.get('method')
            body = action.get('data', {})
            headers = action.get('headers', {})
            msg_id = action.get('msgId')
            client_id = action.get('client_id')
            
            # Reduce logging for frequent HTTP requests
            if hasattr(self, '_http_log_counter'):
                self._http_log_counter += 1
                if self._http_log_counter % 10 == 0:  # Log every 10th HTTP request
                    debug_log(f"🌐 [ActionProcessor] Sudo HTTP request", {
                        "url": url,
                        "method": method,
                        "body_type": type(body).__name__,
                        "body_keys": list(body.keys()) if isinstance(body, dict) else None,
                        "body_preview": str(body)[:100] if body else None,
                        "body_is_string": isinstance(body, str),
                        "body_is_dict": isinstance(body, dict),
                        "body_is_none": body is None,
                        "headers": headers,
                        "msg_id": msg_id,
                        "client_id": client_id,
                        "count": self._http_log_counter
                    })
            else:
                # Initialize counter
                self._http_log_counter = 0
                debug_log(f"🌐 [ActionProcessor] Sudo HTTP request", {
                    "url": url,
                    "method": method,
                    "body_type": type(body).__name__,
                    "body_keys": list(body.keys()) if isinstance(body, dict) else None,
                    "body_preview": str(body)[:100] if body else None,
                    "body_is_string": isinstance(body, str),
                    "body_is_dict": isinstance(body, dict),
                    "body_is_none": body is None,
                    "headers": headers,
                    "msg_id": msg_id,
                    "client_id": client_id
                })
            
            if not url or not method:
                debug_log(f"❌ [ActionProcessor] Missing URL or method", {
                    "url": url,
                    "method": method
                })
                return False
            
            # Process the HTTP request
            result = await self.http_proxy_service.sudo_http_request(url, method, body, headers)
            
            # Send response back to the client
            if result and self.peer_manager and client_id:
                # Format response for the client
                response_data = {
                    'action': msg_id,
                    'msgId': msg_id,
                    'data': result.get('data', {}),
                    'status': result.get('status', 500),
                    'headers': result.get('headers', {}),
                    'timestamp': datetime.datetime.now().isoformat()
                }
                
                # Send response to the specific client
                success = self.peer_manager.send_message(client_id, response_data)
                
                if success:
                    debug_log(f"✅ [ActionProcessor] Response sent to client", {
                        "client_id": client_id,
                        "action": msg_id,
                        "status": result.get('status')
                    })
                else:
                    debug_log(f"❌ [ActionProcessor] Failed to send response to client", {
                        "client_id": client_id,
                        "action": msg_id
                    })
            
            return result
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error handling sudo HTTP request", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    async def _handle_canvas_data(self, action: Dict[str, Any]) -> bool:
        """Handle canvas data action."""
        try:
            data = action.get('data', {})
            data_type = data.get('type', 'unknown')
            data_id = data.get('id')
            client_id = action.get('client_id')
            
            # Reduce logging for canvas data
            if data_type == 'mouse' and hasattr(self, '_mouse_log_counter'):
                self._mouse_log_counter += 1
                if self._mouse_log_counter % 50 == 0:  # Log every 50th mouse event
                    debug_log(f"🎨 [ActionProcessor] Canvas data", {
                        "data_type": data_type,
                        "data_id": data_id,
                        "client_id": client_id,
                        "count": self._mouse_log_counter
                    })
            else:
                # Initialize counter for non-mouse events
                if not hasattr(self, '_mouse_log_counter'):
                    self._mouse_log_counter = 0
                debug_log(f"🎨 [ActionProcessor] Canvas data", {
                    "data_type": data_type,
                    "data_id": data_id,
                    "client_id": client_id
                })
            
            return True
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error handling canvas data", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    def get_action_statistics(self) -> Dict[str, Any]:
        """Get action processing statistics."""
        uptime = datetime.datetime.now() - self.action_stats['start_time']
        
        return {
            'total_actions': self.action_stats['total_actions'],
            'successful_actions': self.action_stats['successful_actions'],
            'failed_actions': self.action_stats['failed_actions'],
            'success_rate': (self.action_stats['successful_actions'] / max(self.action_stats['total_actions'], 1)) * 100,
            'actions_by_type': dict(self.action_stats['actions_by_type']),
            'uptime_seconds': uptime.total_seconds(),
            'start_time': self.action_stats['start_time'].isoformat()
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get action processor status."""
        return {
            'total_handlers': len(self.action_handlers),
            'jupyter_manager_available': self.jupyter_manager is not None,
            'broadcast_callback_available': self.broadcast_callback is not None,
            'http_proxy_service_available': self.http_proxy_service is not None,
            'canvas_service_available': self.canvas_service is not None,
            'widget_service_available': self.widget_service is not None,
            'websocket_bridge_available': self.websocket_bridge is not None,
            'peer_manager_available': self.peer_manager is not None,
            'available_actions': list(self.action_handlers.keys())
        }
    
    async def _handle_websocket_connect(self, action: Dict[str, Any]):
        """Handle WebSocket connection request from frontend."""
        debug_log(f"🔌 [ActionProcessor] WebSocket connect request received", {
            "action": action,
            "has_websocket_bridge": hasattr(self, 'websocket_bridge'),
            "websocket_bridge_available": bool(self.websocket_bridge) if hasattr(self, 'websocket_bridge') else False
        })
        
        if not hasattr(self, 'websocket_bridge') or not self.websocket_bridge:
            debug_log(f"❌ [ActionProcessor] WebSocket bridge service not available")
            raise Exception("WebSocket bridge service not available")
        
        instance_id = action.get('instanceId')
        kernel_id = action.get('kernelId')
        url = action.get('url')
        client_id = action.get('client_id')
        
        debug_log(f"🔌 [ActionProcessor] WebSocket connect request", {
            "instance_id": instance_id,
            "kernel_id": kernel_id,
            "url": url,
            "client_id": client_id
        })
        
        if not instance_id or not url:
            debug_log(f"❌ [ActionProcessor] Missing required fields for WebSocket connect", {
                "instance_id": instance_id,
                "url": url
            })
            return False
        
        try:
            debug_log(f"🔌 [ActionProcessor] Calling websocket_bridge.connect_kernel", {
                "instance_id": instance_id,
                "kernel_id": kernel_id or 'default',
                "url": url
            })
            
            # Connect to kernel via WebSocket bridge
            success = await self.websocket_bridge.connect_kernel(instance_id, kernel_id or 'default', url)
            
            debug_log(f"🔌 [ActionProcessor] connect_kernel result", {
                "success": success,
                "instance_id": instance_id,
                "kernel_id": kernel_id or 'default'
            })
            
            if success:
                debug_log(f"✅ [ActionProcessor] WebSocket connection established", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id,
                    "url": url
                })
                
                # Send confirmation to frontend
                if self.broadcast_callback:
                    confirmation_message = {
                        'action': 'websocket_connected',
                        'instanceId': instance_id,
                        'kernelId': kernel_id or 'default',
                        'timestamp': datetime.datetime.now().isoformat()
                    }
                    
                    debug_log(f"📤 [ActionProcessor] Sending websocket_connected confirmation", {
                        "message": confirmation_message,
                        "client_id": client_id
                    })
                    
                    # Send confirmation WITHOUT excluding the client (they need to receive it)
                    await self.broadcast_callback(confirmation_message)
                    
                    debug_log(f"✅ [ActionProcessor] websocket_connected confirmation sent")
                else:
                    debug_log(f"⚠️ [ActionProcessor] No broadcast callback available")
                
                return True
            else:
                debug_log(f"❌ [ActionProcessor] Failed to establish WebSocket connection", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id,
                    "url": url
                })
                return False
                
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error establishing WebSocket connection", {
                "instance_id": instance_id,
                "kernel_id": kernel_id,
                "url": url,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    async def _handle_websocket_message(self, action: Dict[str, Any]):
        """Handle WebSocket message from frontend."""
        if not hasattr(self, 'websocket_bridge') or not self.websocket_bridge:
            raise Exception("WebSocket bridge service not available")
        
        instance_id = action.get('instanceId')
        kernel_id = action.get('kernelId')
        data = action.get('data')
        client_id = action.get('client_id')
        
        debug_log(f"📤 [ActionProcessor] WebSocket message from frontend", {
            "instance_id": instance_id,
            "kernel_id": kernel_id,
            "data_type": type(data).__name__,
            "client_id": client_id
        })
        
        if not instance_id or not data:
            debug_log(f"❌ [ActionProcessor] Missing required fields for WebSocket message", {
                "instance_id": instance_id,
                "has_data": data is not None
            })
            return False
        
        try:
            # Send message via WebSocket bridge
            success = await self.websocket_bridge.send_message(instance_id, kernel_id or 'default', data)
            
            if success:
                debug_log(f"✅ [ActionProcessor] WebSocket message sent successfully", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id
                })
                return True
            else:
                debug_log(f"❌ [ActionProcessor] Failed to send WebSocket message", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id
                })
                return False
                
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error sending WebSocket message", {
                "instance_id": instance_id,
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    async def _handle_websocket_close(self, action: Dict[str, Any]):
        """Handle WebSocket close request from frontend."""
        if not hasattr(self, 'websocket_bridge') or not self.websocket_bridge:
            raise Exception("WebSocket bridge service not available")
        
        instance_id = action.get('instanceId')
        kernel_id = action.get('kernelId')
        client_id = action.get('client_id')
        
        debug_log(f"🔌 [ActionProcessor] WebSocket close request", {
            "instance_id": instance_id,
            "kernel_id": kernel_id,
            "client_id": client_id
        })
        
        if not instance_id:
            debug_log(f"❌ [ActionProcessor] Missing instance_id for WebSocket close", {
                "instance_id": instance_id
            })
            return False
        
        try:
            # Disconnect kernel via WebSocket bridge
            success = await self.websocket_bridge.disconnect_kernel(instance_id, kernel_id or 'default')
            
            if success:
                debug_log(f"✅ [ActionProcessor] WebSocket connection closed", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id
                })
                
                # Send confirmation to frontend
                if self.broadcast_callback:
                    await self.broadcast_callback({
                        'action': 'websocket_closed',
                        'instanceId': instance_id,
                        'kernelId': kernel_id or 'default',
                        'timestamp': datetime.datetime.now().isoformat()
                    })
                
                return True
            else:
                debug_log(f"❌ [ActionProcessor] Failed to close WebSocket connection", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id
                })
                return False
                
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error closing WebSocket connection", {
                "instance_id": instance_id,
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    def _build_websocket_url(self, url: str) -> str:
        """Build WebSocket URL from HTTP URL."""
        if url.startswith('http://'):
            return url.replace('http://', 'ws://')
        elif url.startswith('https://'):
            return url.replace('https://', 'wss://')
        else:
            # Assume localhost if no protocol
            return f"ws://localhost:8888{url}"
    
    async def cleanup(self):
        """Clean up action processor resources."""
        debug_log(f"🧹 [ActionProcessor] Cleaning up action processor")
        
        # Clear handlers
        self.action_handlers.clear()
        
        # Clear references
        self.jupyter_manager = None
        self.broadcast_callback = None
        self.http_proxy_service = None
        self.canvas_service = None
        self.widget_service = None
        self.websocket_bridge = None
        self.peer_manager = None
        
        debug_log(f"🧹 [ActionProcessor] Action processor cleanup completed")
