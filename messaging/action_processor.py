"""
Action processor for TensorDock server.
Handles specific action types and integrates with other modules.
"""

import asyncio
import json
import datetime
from typing import Dict, Any, Optional, Callable

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log
from core.message_deduplicator import MessageDeduplicator
from core.jupyter_message_factory import JupyterMessageFactory
from core.validation_utils import ValidationUtils


class ActionProcessor(LoggerMixin):
    """Processes specific action types and integrates with other modules."""
    
    def __init__(self):
        # External module references (to be set by server)
        self.jupyter_manager = None
        self.broadcast_callback = None
        self.send_to_client = None
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
        
        # Centralized message deduplication
        self.deduplicator = MessageDeduplicator()
        
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

    def set_send_to_client(self, send_to_client: Callable):
        """Set the callback for sending messages to clients."""
        self.send_to_client = send_to_client
        
        debug_log(f"🔗 [ActionProcessor] Send to client callback set")
    
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
        # Deprecated: kernel/comm-specific handlers are removed in favor of URL-based ws_* schema
        self.register_handler('sudo_http_request', self._handle_sudo_http_request)
        self.register_handler('canvas_data', self._handle_canvas_data)
        
        # Aliases for simplified ws_* handshake
        self.register_handler('ws_connect', self._handle_websocket_connect)
        self.register_handler('ws_message', self._handle_websocket_message)
        self.register_handler('ws_close', self._handle_websocket_close)
        
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
    
    
    async def _handle_sudo_http_request(self, action: Dict[str, Any]) -> bool:
        """Handle sudo HTTP request action."""
        try:
            # Validate HTTP proxy service
            error = ValidationUtils.validate_websocket_connection(self.http_proxy_service, "sudo_http_request")
            if error:
                raise Exception(error)
            
            url = action.get('url')
            method = action.get('method')
            
            # Validate HTTP request parameters
            error = ValidationUtils.validate_http_request(url, method)
            if error:
                raise ValueError(error)
            
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
        
        # Handle both camelCase (frontend) and snake_case (backend) field naming
        instance_id = action.get('instanceId') or action.get('instance_id')
        url = action.get('url')
        client_id = action.get('client_id')
        
        debug_log(f"🔌 [ActionProcessor] WebSocket connect request", {
            "instance_id": instance_id,
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
            
            success = await self.websocket_bridge.connect_websocket(instance_id, url)
            
            debug_log(f"🔌 [ActionProcessor] connect_kernel result", {
                "success": success,
                "instance_id": instance_id,
            })
            
            if success:
                debug_log(f"✅ [ActionProcessor] WebSocket connection established", {
                    "instance_id": instance_id,
                    "url": url
                })
                
                # Send confirmation to frontend
                if self.broadcast_callback:
                    confirmation_message = {
                        'action': 'ws_connected',
                        'instanceId': instance_id,
                        'timestamp': datetime.datetime.now().isoformat()
                    }
                    
                    debug_log(f"📤 [ActionProcessor] Sending ws_connected confirmation", {
                        "message": confirmation_message,
                        "client_id": client_id
                    })
                    
                    # Send confirmation WITHOUT excluding the client (they need to receive it)
                    await self.broadcast_callback(confirmation_message)
                    
                    debug_log(f"✅ [ActionProcessor] ws_connected confirmation sent")
                else:
                    debug_log(f"⚠️ [ActionProcessor] No broadcast callback available")
                
                return True
            else:
                debug_log(f"❌ [ActionProcessor] Failed to establish WebSocket connection", {
                    "instance_id": instance_id,
                    "url": url
                })
                
                # Send failure notification to frontend
                if self.broadcast_callback:
                    failure_message = {
                        'action': 'ws_connect_failed',
                        'instanceId': instance_id,
                        'url': url,
                        'error': 'WebSocket connection failed',
                        'timestamp': datetime.datetime.now().isoformat()
                    }
                    
                    debug_log(f"📤 [ActionProcessor] Sending ws_connect_failed notification", {
                        "message": failure_message,
                        "client_id": client_id
                    })
                    
                    await self.broadcast_callback(failure_message)
                
                return False
                
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error establishing WebSocket connection", {
                "instance_id": instance_id,
                "kernel_id": kernel_id,
                "url": url,
                "error": str(e),
                "error_type": type(e).__name__
            })
            
            # Send failure notification to frontend
            if self.broadcast_callback:
                failure_message = {
                    'action': 'ws_connect_failed',
                    'instanceId': instance_id,
                    'kernelId': kernel_id or 'default',
                    'url': url,
                    'error': str(e),
                    'timestamp': datetime.datetime.now().isoformat()
                }
                
                debug_log(f"📤 [ActionProcessor] Sending ws_connect_failed notification (exception)", {
                    "message": failure_message,
                    "client_id": client_id
                })
                
                await self.broadcast_callback(failure_message)
            
            return False
    
    async def _handle_websocket_message(self, action: Dict[str, Any]):
        """Handle WebSocket message from frontend."""
        if not hasattr(self, 'websocket_bridge') or not self.websocket_bridge:
            raise Exception("WebSocket bridge service not available")
        
        # Handle both camelCase (frontend) and snake_case (backend) field naming
        instance_id = action.get('instanceId') or action.get('instance_id')
        kernel_id = action.get('kernelId') or action.get('kernel_id')
        data = action.get('data')
        url = action.get('url')
        client_id = action.get('client_id')
        
        # ERROR: This should never happen - all messages should be properly wrapped
        # If we're receiving direct Jupyter messages, there's a bug in the frontend
        if not instance_id and not data and 'header' in action and 'content' in action:
            debug_log(f"❌ [ActionProcessor] ERROR: Received direct Jupyter message (not wrapped) - this should not happen!", {
                "has_header": 'header' in action,
                "has_content": 'content' in action,
                "msg_type": action.get('header', {}).get('msg_type'),
                "action_keys": list(action.keys()),
                "action_preview": str(action)[:200],
                "session": action.get('header', {}).get('session'),
                "client_id": client_id
            })
            
            # Reject this message - it should be properly wrapped by the frontend
            debug_log(f"❌ [ActionProcessor] REJECTING unwrapped Jupyter message - frontend must fix this!", {
                "msg_type": action.get('header', {}).get('msg_type'),
                "session": action.get('header', {}).get('session'),
                "client_id": client_id,
                "CRITICAL": "There is a WebSocket connection bypassing our WebRTC system!"
            })
            return False
        
        debug_log(f"📤 [ActionProcessor] WebSocket message from frontend", {
            "instance_id": instance_id,
            "kernel_id": kernel_id,
            "data_type": type(data).__name__,
            "data_preview": str(data)[:100] if data else None,
            "url": url,
            "client_id": client_id,
            "action_keys": list(action.keys()),
            "raw_instanceId": action.get('instanceId'),
            "raw_instance_id": action.get('instance_id'),
            "raw_data": action.get('data'),
            "action_type": type(action).__name__,
            "action_str_preview": str(action)[:500]
        })
        
        # Enhanced validation - check for both instance_id and data
        if not instance_id:
            debug_log(f"❌ [ActionProcessor] Missing instance_id for WebSocket message", {
                "instance_id": instance_id,
                "action_keys": list(action.keys()),
                "action_preview": str(action)[:200],
                "full_action": action
            })
            return False
        
        if data is None:
            debug_log(f"❌ [ActionProcessor] Missing data for WebSocket message", {
                "instance_id": instance_id,
                "data": data,
                "action_keys": list(action.keys()),
                "full_action": action
            })
            return False
        
        try:
            # Always use URL-based routing
            if url:
                debug_log(f"🔧 [ActionProcessor] Sending message via URL-based routing", {
                    "instance_id": instance_id,
                    "url": url,
                    "data_type": type(data).__name__,
                    "data_preview": str(data)[:100] if data else None
                })
                success = await self.websocket_bridge.send_ws_message_by_url(instance_id, url, data)
            else:
                # Try to infer URL from kernel_id
                if kernel_id and kernel_id != 'events':
                    # This is likely a kernel message
                    inferred_url = f"ws://localhost:8888/api/kernels/{kernel_id}/channels"
                    debug_log(f"🔧 [ActionProcessor] Sending message via inferred kernel URL", {
                        "instance_id": instance_id,
                        "kernel_id": kernel_id,
                        "inferred_url": inferred_url,
                        "data_type": type(data).__name__
                    })
                    success = await self.websocket_bridge.send_ws_message_by_url(instance_id, inferred_url, data)
                else:
                    # This might be an events message
                    inferred_url = "ws://localhost:8888/api/events/subscribe"
                    debug_log(f"🔧 [ActionProcessor] Sending message via inferred events URL", {
                        "instance_id": instance_id,
                        "inferred_url": inferred_url,
                        "data_type": type(data).__name__
                    })
                    success = await self.websocket_bridge.send_ws_message_by_url(instance_id, inferred_url, data)
            
            if success:
                debug_log(f"✅ [ActionProcessor] WebSocket message sent successfully", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id,
                    "url": url or "inferred"
                })
                return True
            else:
                debug_log(f"❌ [ActionProcessor] Failed to send WebSocket message", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id,
                    "url": url or "inferred"
                })
                return False
                
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error sending WebSocket message", {
                "instance_id": instance_id,
                "kernel_id": kernel_id,
                "url": url or "inferred",
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    async def _handle_websocket_close(self, action: Dict[str, Any]):
        """Handle WebSocket close request from frontend."""
        if not hasattr(self, 'websocket_bridge') or not self.websocket_bridge:
            raise Exception("WebSocket bridge service not available")
        
        # Handle both camelCase (frontend) and snake_case (backend) field naming
        instance_id = action.get('instanceId') or action.get('instance_id')
        kernel_id = action.get('kernelId') or action.get('kernel_id')
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
            # Use URL-based close via WebSocket bridge
            url = action.get('url')
            if url:
                success = await self.websocket_bridge.ws_close(instance_id, url)
            else:
                # Try to infer URL from kernel_id
                if kernel_id and kernel_id != 'events':
                    inferred_url = f"ws://localhost:8888/api/kernels/{kernel_id}/channels"
                    success = await self.websocket_bridge.ws_close(instance_id, inferred_url)
                else:
                    inferred_url = "ws://localhost:8888/api/events/subscribe"
                    success = await self.websocket_bridge.ws_close(instance_id, inferred_url)
            
            if success:
                debug_log(f"✅ [ActionProcessor] WebSocket connection closed", {
                    "instance_id": instance_id,
                    "kernel_id": kernel_id,
                    "url": url or "inferred"
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
                    "kernel_id": kernel_id,
                    "url": url or "inferred"
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
    
    def get_status(self) -> Dict[str, Any]:
        """Get action processor status."""
        uptime = datetime.datetime.now() - self.action_stats['start_time']
        total = self.action_stats['total_actions']
        success_rate = (self.action_stats['successful_actions'] / max(total, 1)) * 100
        
        return {
            'total_handlers': len(self.action_handlers),
            'total_actions': total,
            'successful_actions': self.action_stats['successful_actions'],
            'failed_actions': self.action_stats['failed_actions'],
            'success_rate': success_rate,
            'actions_by_type': dict(self.action_stats['actions_by_type']),
            'uptime_seconds': uptime.total_seconds(),
            'start_time': self.action_stats['start_time'].isoformat(),
            'jupyter_manager_available': self.jupyter_manager is not None,
            'broadcast_callback_available': self.broadcast_callback is not None,
            'http_proxy_service_available': self.http_proxy_service is not None,
            'canvas_service_available': self.canvas_service is not None,
            'widget_service_available': self.widget_service is not None,
            'websocket_bridge_available': self.websocket_bridge is not None,
            'peer_manager_available': self.peer_manager is not None,
            'available_actions': list(self.action_handlers.keys())
        }
    
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

    async def _handle_yjs_document_update(self, action: Dict[str, Any]):
        """Handle YJS document update from frontend."""
        try:
            document_id = action.get('documentId')
            update_data = action.get('update')
            client_id = action.get('client_id')
            
            if not document_id or not update_data:
                debug_log(f"❌ [ActionProcessor] YJS document update missing required fields", {
                    "document_id": document_id,
                    "has_update": bool(update_data),
                    "client_id": client_id
                })
                return False
            
            debug_log(f"📥 [ActionProcessor] YJS document update received", {
                "document_id": document_id,
                "update_size": len(update_data) if update_data else 0,
                "client_id": client_id
            })
            
            # Convert array back to bytes
            update_bytes = bytes(update_data)
            
            # Store the update and broadcast to other clients
            if hasattr(self, 'yjs_service') and self.yjs_service:
                await self.yjs_service.handle_document_update(document_id, update_bytes)
            else:
                debug_log(f"⚠️ [ActionProcessor] YJS service not available", {
                    "document_id": document_id,
                    "client_id": client_id
                })
            
            return True
            
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error handling YJS document update", {
                "error": str(e),
                "error_type": type(e).__name__,
                "client_id": action.get('client_id')
            })
            return False

    async def _handle_yjs_awareness_update(self, action: Dict[str, Any]):
        """Handle YJS awareness update from frontend."""
        try:
            document_id = action.get('documentId')
            awareness_data = action.get('awareness')
            client_id = action.get('client_id')
            
            if not document_id:
                debug_log(f"❌ [ActionProcessor] YJS awareness update missing document ID", {
                    "document_id": document_id,
                    "client_id": client_id
                })
                return False
            
            # Skip empty awareness updates - they're normal in YJS protocol
            if not awareness_data or len(awareness_data) == 0:
                debug_log(f"🔧 [ActionProcessor] Skipping empty YJS awareness update", {
                    "document_id": document_id,
                    "client_id": client_id
                })
                return True
            
            debug_log(f"📥 [ActionProcessor] YJS awareness update received", {
                "document_id": document_id,
                "awareness_size": len(awareness_data),
                "client_id": client_id
            })
            
            # Convert array back to bytes
            awareness_bytes = bytes(awareness_data)
            
            # Store the update and broadcast to other clients
            if hasattr(self, 'yjs_service') and self.yjs_service:
                await self.yjs_service.handle_awareness_update(document_id, awareness_bytes)
            else:
                debug_log(f"⚠️ [ActionProcessor] YJS service not available", {
                    "document_id": document_id,
                    "client_id": client_id
                })
            
            return True
            
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error handling YJS awareness update", {
                "error": str(e),
                "error_type": type(e).__name__,
                "client_id": action.get('client_id')
            })
            return False

    async def _handle_yjs_sync_request(self, action: Dict[str, Any]):
        """Handle YJS sync request from frontend."""
        try:
            document_id = action.get('documentId')
            client_id = action.get('client_id')
            
            if not document_id:
                debug_log(f"❌ [ActionProcessor] YJS sync request missing document ID", {
                    "document_id": document_id,
                    "client_id": client_id
                })
                return False
            
            debug_log(f"📥 [ActionProcessor] YJS sync request received", {
                "document_id": document_id,
                "client_id": client_id
            })
            
            # Handle the sync request
            if hasattr(self, 'yjs_service') and self.yjs_service:
                await self.yjs_service.handle_sync_request(document_id)
            else:
                debug_log(f"⚠️ [ActionProcessor] YJS service not available", {
                    "document_id": document_id,
                    "client_id": client_id
                })
            
            return True
            
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error handling YJS sync request", {
                "error": str(e),
                "error_type": type(e).__name__,
                "client_id": action.get('client_id')
            })
            return False

    async def _handle_yjs_request_state(self, action: Dict[str, Any]):
        """Handle YJS state request from backend."""
        try:
            document_id = action.get('documentId')
            client_id = action.get('client_id')
            
            if not document_id:
                debug_log(f"❌ [ActionProcessor] YJS state request missing document ID", {
                    "document_id": document_id,
                    "client_id": client_id
                })
                return False
            
            debug_log(f"📥 [ActionProcessor] YJS state request received", {
                "document_id": document_id,
                "client_id": client_id
            })
            
            # This will be handled by the frontend YJS provider
            # The frontend will respond with the current document state
            return True
            
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error handling YJS state request", {
                "error": str(e),
                "error_type": type(e).__name__,
                "client_id": action.get('client_id')
            })
            return False

    async def _handle_yjs_state_response(self, action: Dict[str, Any]):
        """Handle YJS state response from frontend."""
        try:
            document_id = action.get('documentId')
            notebook_content = action.get('notebookContent')
            client_id = action.get('client_id')
            
            if not document_id or not notebook_content:
                debug_log(f"❌ [ActionProcessor] YJS state response missing required fields", {
                    "document_id": document_id,
                    "has_content": bool(notebook_content),
                    "client_id": client_id
                })
                return False
            
            debug_log(f"📥 [ActionProcessor] YJS state response received", {
                "document_id": document_id,
                "client_id": client_id
            })
            
            if hasattr(self, 'yjs_service') and self.yjs_service:
                await self.yjs_service.handle_document_state_response(document_id, notebook_content)
            else:
                debug_log(f"⚠️ [ActionProcessor] YJS service not available", {
                    "document_id": document_id,
                    "client_id": client_id
                })
            
            return True
            
        except Exception as e:
            debug_log(f"❌ [ActionProcessor] Error handling YJS state response", {
                "error": str(e),
                "error_type": type(e).__name__,
                "client_id": action.get('client_id')
            })
            return False
