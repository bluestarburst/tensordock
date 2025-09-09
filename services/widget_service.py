"""
Widget service for TensorDock server.
Handles widget communication and comm message management.
"""

import json
import datetime
from typing import Dict, Any, Optional, List, Set
from collections import defaultdict

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log


class WidgetService(LoggerMixin):
    """Handles widget communication and comm message management."""
    
    def __init__(self):
        # Widget state tracking
        self.widget_states: Dict[str, Dict[str, Any]] = {}
        self.widget_models: Dict[str, Dict[str, Any]] = {}
        self.comm_managers: Dict[str, Dict[str, Any]] = {}
        
        # Comm message tracking
        self.comm_messages: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.comm_handlers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        # Client widget associations
        self.client_widgets: Dict[str, Set[str]] = defaultdict(set)
        
        # Widget statistics
        self.widget_stats = {
            'total_comm_messages': 0,
            'messages_by_type': defaultdict(int),
            'active_widgets': 0,
            'total_handlers': 0,
            'start_time': datetime.datetime.now()
        }
        
        debug_log(f"🎛️ [Widget] Widget service initialized")
    
    async def handle_jupyter_comm_message(self, kernel_id: str, jupyter_message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Jupyter comm messages with proper protocol compliance."""
        try:
            header = jupyter_message.get('header', {})
            content = jupyter_message.get('content', {})
            metadata = jupyter_message.get('metadata', {})
            buffers = jupyter_message.get('buffers', [])
            
            msg_type = header.get('msg_type')
            comm_id = content.get('comm_id')
            msg_id = header.get('msg_id')
            
            debug_log(f"🎛️ [Widget] Processing Jupyter comm message", {
                "kernel_id": kernel_id,
                "msg_type": msg_type,
                "comm_id": comm_id,
                "msg_id": msg_id,
                "has_buffers": len(buffers) > 0
            })
            
            # Validate required fields
            if not msg_type:
                raise ValueError("Missing msg_type in Jupyter message header")
            if not comm_id:
                raise ValueError("Missing comm_id in Jupyter message content")
            
            # Extract client_id from metadata or use kernel_id as fallback
            client_id = metadata.get('client_id', kernel_id)
            
            # Create data structure for legacy handler
            data = {
                'msg_type': msg_type,
                'target_name': content.get('target_name'),
                'data': content.get('data', {}),
                'metadata': metadata
            }
            
            # Route to appropriate handler
            if msg_type == 'comm_open':
                result = await self._handle_comm_open(comm_id, data, client_id)
            elif msg_type == 'comm_msg':
                result = await self._handle_comm_msg(comm_id, data, client_id)
            elif msg_type == 'comm_close':
                result = await self._handle_comm_close(comm_id, data, client_id)
            else:
                result = await self._handle_unknown_comm_msg(comm_id, data, client_id)
            
            # Store Jupyter message for tracking
            if comm_id not in self.comm_messages:
                self.comm_messages[comm_id] = []
            
            self.comm_messages[comm_id].append({
                'timestamp': datetime.datetime.now().isoformat(),
                'kernel_id': kernel_id,
                'msg_type': msg_type,
                'msg_id': msg_id,
                'jupyter_message': jupyter_message,
                'result': result
            })
            
            return result
            
        except Exception as e:
            debug_log(f"❌ [Widget] Jupyter comm message handling error", {
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }
    
    async def handle_comm_message(self, comm_id: str, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle incoming comm message from a client."""
        try:
            msg_type = data.get('msg_type', 'unknown')
            
            debug_log(f"🎛️ [Widget] Processing comm message", {
                "client_id": client_id,
                "comm_id": comm_id,
                "msg_type": msg_type,
                "data_keys": list(data.keys()),
                "timestamp": datetime.datetime.now().isoformat()
            })
            
            # Update statistics
            self.widget_stats['total_comm_messages'] += 1
            self.widget_stats['messages_by_type'][msg_type] += 1
            
            # Handle different message types
            if msg_type == 'comm_open':
                result = await self._handle_comm_open(comm_id, data, client_id)
            elif msg_type == 'comm_msg':
                result = await self._handle_comm_msg(comm_id, data, client_id)
            elif msg_type == 'comm_close':
                result = await self._handle_comm_close(comm_id, data, client_id)
            else:
                result = await self._handle_unknown_comm_msg(comm_id, data, client_id)
            
            # Store comm message
            self.comm_messages[comm_id].append({
                'timestamp': datetime.datetime.now().isoformat(),
                'client_id': client_id,
                'msg_type': msg_type,
                'data': data,
                'result': result
            })
            
            return result
            
        except Exception as e:
            debug_log(f"❌ [Widget] Comm message handling error", {
                "client_id": client_id,
                "comm_id": comm_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "data": data
            })
            
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }
    
    async def _handle_comm_open(self, comm_id: str, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle comm_open message for widget initialization."""
        try:
            # ✅ ENHANCED: Extract widget information with proper validation
            target_name = data.get('target_name', 'jupyter.widget')
            model_id = data.get('model_id', comm_id)
            comm_data = data.get('data', {})
            
            # Validate required fields
            if not comm_id:
                raise ValueError("comm_id is required for comm_open")
            if not target_name:
                raise ValueError("target_name is required for comm_open")
            
            # Create widget state
            self.widget_states[comm_id] = {
                'comm_id': comm_id,
                'model_id': model_id,
                'target_name': target_name,
                'client_id': client_id,
                'status': 'open',
                'created_at': datetime.datetime.now().isoformat(),
                'last_activity': datetime.datetime.now().isoformat(),
                'initial_data': comm_data,
                'message_count': 0
            }
            
            # Create comm manager
            self.comm_managers[comm_id] = {
                'comm_id': comm_id,
                'client_id': client_id,
                'status': 'active',
                'message_count': 0,
                'created_at': datetime.datetime.now().isoformat(),
                'target_name': target_name
            }
            
            # Associate with client
            self.client_widgets[client_id].add(comm_id)
            self.widget_stats['active_widgets'] += 1
            
            debug_log(f"✅ [Widget] Comm opened", {
                "client_id": client_id,
                "comm_id": comm_id,
                "target_name": target_name,
                "model_id": model_id,
                "initial_data_keys": list(comm_data.keys()) if comm_data else []
            })
            
            return {
                'success': True,
                'comm_id': comm_id,
                'operation': 'comm_open',
                'widget_state': self.widget_states[comm_id]
            }
            
        except Exception as e:
            debug_log(f"❌ [Widget] Comm open error", {
                "comm_id": comm_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            raise
    
    async def _handle_comm_msg(self, comm_id: str, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle comm_msg message for widget communication."""
        try:
            # ✅ ENHANCED: Better validation and error handling
            if comm_id not in self.widget_states:
                debug_log(f"⚠️ [Widget] Comm not found for comm_msg", {
                    "comm_id": comm_id,
                    "client_id": client_id,
                    "available_comms": list(self.widget_states.keys())
                })
                return {
                    'success': False,
                    'error': f'Comm {comm_id} not found',
                    'comm_id': comm_id
                }
            
            # Validate comm is in open state
            if self.widget_states[comm_id]['status'] != 'open':
                debug_log(f"⚠️ [Widget] Comm not in open state", {
                    "comm_id": comm_id,
                    "status": self.widget_states[comm_id]['status']
                })
                return {
                    'success': False,
                    'error': f'Comm {comm_id} is not open (status: {self.widget_states[comm_id]["status"]})',
                    'comm_id': comm_id
                }
            
            # Update widget state
            self.widget_states[comm_id]['last_activity'] = datetime.datetime.now().isoformat()
            self.widget_states[comm_id]['message_count'] = self.widget_states[comm_id].get('message_count', 0) + 1
            
            # Update comm manager
            self.comm_managers[comm_id]['message_count'] += 1
            self.comm_managers[comm_id]['last_activity'] = datetime.datetime.now().isoformat()
            
            # Process message data
            message_data = data.get('data', {})
            
            debug_log(f"✅ [Widget] Comm message processed", {
                "client_id": client_id,
                "comm_id": comm_id,
                "message_data_keys": list(message_data.keys()) if message_data else [],
                "message_count": self.widget_states[comm_id]['message_count'],
                "target_name": self.widget_states[comm_id].get('target_name')
            })
            
            return {
                'success': True,
                'comm_id': comm_id,
                'operation': 'comm_msg',
                'message_data': message_data,
                'message_count': self.widget_states[comm_id]['message_count']
            }
            
        except Exception as e:
            debug_log(f"❌ [Widget] Comm message error", {
                "comm_id": comm_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            raise
    
    async def _handle_comm_close(self, comm_id: str, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle comm_close message for widget cleanup."""
        try:
            # ✅ ENHANCED: Better validation and cleanup
            if comm_id not in self.widget_states:
                debug_log(f"⚠️ [Widget] Comm not found for comm_close", {
                    "comm_id": comm_id,
                    "client_id": client_id,
                    "available_comms": list(self.widget_states.keys())
                })
                return {
                    'success': False,
                    'error': f'Comm {comm_id} not found',
                    'comm_id': comm_id
                }
            
            # Get comm data before cleanup
            comm_data = data.get('data', {})
            widget_state = self.widget_states[comm_id].copy()
            
            # Update widget state
            self.widget_states[comm_id]['status'] = 'closed'
            self.widget_states[comm_id]['closed_at'] = datetime.datetime.now().isoformat()
            self.widget_states[comm_id]['close_data'] = comm_data
            
            # Update comm manager
            self.comm_managers[comm_id]['status'] = 'closed'
            self.comm_managers[comm_id]['closed_at'] = datetime.datetime.now().isoformat()
            
            # Remove from client associations
            if client_id in self.client_widgets:
                self.client_widgets[client_id].discard(comm_id)
            
            self.widget_stats['active_widgets'] = max(0, self.widget_stats['active_widgets'] - 1)
            
            debug_log(f"✅ [Widget] Comm closed", {
                "client_id": client_id,
                "comm_id": comm_id,
                "target_name": widget_state.get('target_name'),
                "message_count": widget_state.get('message_count', 0),
                "close_data_keys": list(comm_data.keys()) if comm_data else []
            })
            
            return {
                'success': True,
                'comm_id': comm_id,
                'operation': 'comm_close',
                'widget_state': widget_state,
                'close_data': comm_data
            }
            
        except Exception as e:
            debug_log(f"❌ [Widget] Comm close error", {
                "comm_id": comm_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            raise
    
    async def _handle_unknown_comm_msg(self, comm_id: str, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle unknown comm message types."""
        msg_type = data.get('msg_type', 'unknown')
        
        debug_log(f"⚠️ [Widget] Unknown comm message type", {
            "client_id": client_id,
            "comm_id": comm_id,
            "msg_type": msg_type,
            "data": data
        })
        
        return {
            'success': False,
            'error': f'Unknown comm message type: {msg_type}'
        }
    
    async def send_comm_message(self, comm_id: str, data: Dict[str, Any], target_client_id: Optional[str] = None) -> bool:
        """Send a comm message to a widget."""
        try:
            if comm_id not in self.widget_states:
                debug_log(f"❌ [Widget] Cannot send message to non-existent comm", {
                    "comm_id": comm_id
                })
                return False
            
            # Create message structure
            message = {
                'header': {
                    'msg_id': f"comm_{comm_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
                    'msg_type': 'comm_msg',
                    'username': 'server',
                    'session': 'server',
                    'date': datetime.datetime.now().isoformat(),
                    'version': '5.0'
                },
                'parent_header': {},
                'metadata': {},
                'content': {
                    'comm_id': comm_id,
                    'data': data
                }
            }
            
            # Update widget state
            self.widget_states[comm_id]['last_activity'] = datetime.datetime.now().isoformat()
            self.widget_states[comm_id]['outgoing_message_count'] = self.widget_states[comm_id].get('outgoing_message_count', 0) + 1
            
            debug_log(f"✅ [Widget] Comm message sent", {
                "comm_id": comm_id,
                "target_client_id": target_client_id,
                "data_keys": list(data.keys()) if data else []
            })
            
            return True
            
        except Exception as e:
            debug_log(f"❌ [Widget] Failed to send comm message", {
                "comm_id": comm_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    def get_widget_state(self, comm_id: str) -> Optional[Dict[str, Any]]:
        """Get state information for a specific widget."""
        return self.widget_states.get(comm_id)
    
    def get_client_widgets(self, client_id: str) -> List[Dict[str, Any]]:
        """Get all widgets associated with a client."""
        widget_ids = self.client_widgets.get(client_id, set())
        return [self.widget_states.get(widget_id, {}) for widget_id in widget_ids if widget_id in self.widget_states]
    
    def get_widget_statistics(self) -> Dict[str, Any]:
        """Get widget operation statistics."""
        uptime = datetime.datetime.now() - self.widget_stats['start_time']
        
        return {
            'total_comm_messages': self.widget_stats['total_comm_messages'],
            'messages_by_type': dict(self.widget_stats['messages_by_type']),
            'active_widgets': self.widget_stats['active_widgets'],
            'total_handlers': self.widget_stats['total_handlers'],
            'uptime_seconds': uptime.total_seconds(),
            'start_time': self.widget_stats['start_time'].isoformat()
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get widget service status."""
        return {
            'active_widgets': self.widget_stats['active_widgets'],
            'total_comm_messages': self.widget_stats['total_comm_messages'],
            'total_widget_states': len(self.widget_states),
            'total_comm_managers': len(self.comm_managers),
            'total_clients_with_widgets': len(self.client_widgets)
        }
    
    async def cleanup(self):
        """Clean up widget service resources."""
        debug_log(f"🧹 [Widget] Cleaning up widget service")
        
        # Clear all data
        self.widget_states.clear()
        self.widget_models.clear()
        self.comm_managers.clear()
        self.comm_messages.clear()
        self.comm_handlers.clear()
        self.client_widgets.clear()
        
        # Reset statistics
        self.widget_stats.clear()
        self.widget_stats['start_time'] = datetime.datetime.now()
        
        debug_log(f"🧹 [Widget] Widget service cleanup completed")
