"""
Canvas service for TensorDock server.
Handles canvas data operations and client state management.
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


class CanvasService(LoggerMixin):
    """Handles canvas data operations and client state."""
    
    def __init__(self):
        # Debug mode for controlling logging verbosity
        self.debug_mode = os.environ.get('TENSORDOCK_DEBUG', 'false').lower() == 'true'

        # Canvas data storage
        self.canvas_data: Dict[str, Dict[str, Any]] = {}
        self.client_canvases: Dict[str, Set[str]] = defaultdict(set)
        
        # Client state tracking
        self.client_states: Dict[str, Dict[str, Any]] = {}
        self.client_connections: Set[str] = set()
        
        # Canvas statistics
        self.canvas_stats = {
            'total_operations': 0,
            'operations_by_type': defaultdict(int),
            'active_clients': 0,
            'total_canvas_elements': 0,
            'start_time': datetime.datetime.now()
        }
        
        debug_log(f"🎨 [Canvas] Canvas service initialized")
    
    async def handle_canvas_data(self, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle incoming canvas data from a client."""
        try:
            operation_type = data.get('type', 'unknown')
            
            # Reduce logging verbosity for frequent operations
            # if operation_type in ['move', 'resize', 'update']:
            #     if self.debug_mode:
            #         debug_log(f"🎨 [Canvas] {operation_type} operation for client {client_id}")
            # else:
            #     debug_log(f"🎨 [Canvas] Processing canvas data", {
            #         "client_id": client_id,
            #         "operation_type": operation_type,
            #         "data_keys": list(data.keys()),
            #         "timestamp": datetime.datetime.now().isoformat()
            #     })
            
            # Update statistics
            self.canvas_stats['total_operations'] += 1
            self.canvas_stats['operations_by_type'][operation_type] += 1
            
            # Handle different operation types
            if operation_type == 'create':
                result = await self._handle_create_operation(data, client_id)
            elif operation_type == 'update':
                result = await self._handle_update_operation(data, client_id)
            elif operation_type == 'delete':
                result = await self._handle_delete_operation(data, client_id)
            elif operation_type == 'move':
                result = await self._handle_move_operation(data, client_id)
            elif operation_type == 'resize':
                result = await self._handle_resize_operation(data, client_id)
            elif operation_type == 'connect':
                result = await self._handle_connect_operation(data, client_id)
            elif operation_type == 'disconnect':
                result = await self._handle_disconnect_operation(data, client_id)
            else:
                result = await self._handle_unknown_operation(data, client_id)
            
            # Update client state
            self._update_client_state(client_id, operation_type, data)
            
            return result
            
        except Exception as e:
            debug_log(f"❌ [Canvas] Canvas data handling error", {
                "client_id": client_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "data": data
            })
            
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }
    
    async def _handle_create_operation(self, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle canvas element creation."""
        element_id = data.get('id')
        element_data = data.get('data', {})
        
        if element_id:
            self.canvas_data[element_id] = {
                **element_data,
                'created_by': client_id,
                'created_at': datetime.datetime.now().isoformat(),
                'last_modified': datetime.datetime.now().isoformat()
            }
            
            self.client_canvases[client_id].add(element_id)
            self.canvas_stats['total_canvas_elements'] += 1
            
            debug_log(f"✅ [Canvas] Element created", {
                "client_id": client_id,
                "element_id": element_id,
                "element_type": element_data.get('type')
            })
            
            return {
                'success': True,
                'element_id': element_id,
                'operation': 'create'
            }
        
        return {
            'success': False,
            'error': 'Missing element ID'
        }
    
    async def _handle_update_operation(self, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle canvas element update."""
        element_id = data.get('id')
        updates = data.get('updates', {})
        
        if element_id and element_id in self.canvas_data:
            # Update element data
            self.canvas_data[element_id].update(updates)
            self.canvas_data[element_id]['last_modified'] = datetime.datetime.now().isoformat()
            self.canvas_data[element_id]['modified_by'] = client_id
            
            debug_log(f"✅ [Canvas] Element updated", {
                "client_id": client_id,
                "element_id": element_id,
                "update_keys": list(updates.keys())
            })
            
            return {
                'success': True,
                'element_id': element_id,
                'operation': 'update'
            }
        
        return {
            'success': False,
            'error': 'Element not found'
        }
    
    async def _handle_delete_operation(self, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle canvas element deletion."""
        element_id = data.get('id')
        
        if element_id and element_id in self.canvas_data:
            # Remove element
            del self.canvas_data[element_id]
            
            # Remove from client canvases
            for client_canvas in self.client_canvases.values():
                client_canvas.discard(element_id)
            
            self.canvas_stats['total_canvas_elements'] = max(0, self.canvas_stats['total_canvas_elements'] - 1)
            
            debug_log(f"✅ [Canvas] Element deleted", {
                "client_id": client_id,
                "element_id": element_id
            })
            
            return {
                'success': True,
                'element_id': element_id,
                'operation': 'delete'
            }
        
        return {
            'success': False,
            'error': 'Element not found'
        }
    
    async def _handle_move_operation(self, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle canvas element movement."""
        element_id = data.get('id')
        position = data.get('position', {})
        
        if element_id and element_id in self.canvas_data:
            # Update position
            self.canvas_data[element_id]['position'] = position
            self.canvas_data[element_id]['last_modified'] = datetime.datetime.now().isoformat()
            self.canvas_data[element_id]['modified_by'] = client_id
            
            debug_log(f"✅ [Canvas] Element moved", {
                "client_id": client_id,
                "element_id": element_id,
                "position": position
            })
            
            return {
                'success': True,
                'element_id': element_id,
                'operation': 'move',
                'position': position
            }
        
        return {
            'success': False,
            'error': 'Element not found'
        }
    
    async def _handle_resize_operation(self, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle canvas element resizing."""
        element_id = data.get('id')
        dimensions = data.get('dimensions', {})
        
        if element_id and element_id in self.canvas_data:
            # Update dimensions
            self.canvas_data[element_id]['dimensions'] = dimensions
            self.canvas_data[element_id]['last_modified'] = datetime.datetime.now().isoformat()
            self.canvas_data[element_id]['modified_by'] = client_id
            
            debug_log(f"✅ [Canvas] Element resized", {
                "client_id": client_id,
                "element_id": element_id,
                "dimensions": dimensions
            })
            
            return {
                'success': True,
                'element_id': element_id,
                'operation': 'resize',
                'dimensions': dimensions
            }
        
        return {
            'success': False,
            'error': 'Element not found'
        }
    
    async def _handle_connect_operation(self, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle client connection."""
        self.client_connections.add(client_id)
        self.client_states[client_id] = {
            'connected_at': datetime.datetime.now().isoformat(),
            'last_activity': datetime.datetime.now().isoformat(),
            'status': 'connected'
        }
        
        self.canvas_stats['active_clients'] = len(self.client_connections)
        
        debug_log(f"✅ [Canvas] Client connected", {
            "client_id": client_id,
            "total_clients": len(self.client_connections)
        })
        
        return {
            'success': True,
            'operation': 'connect',
            'client_id': client_id
        }
    
    async def _handle_disconnect_operation(self, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle client disconnection."""
        self.client_connections.discard(client_id)
        
        if client_id in self.client_states:
            self.client_states[client_id]['status'] = 'disconnected'
            self.client_states[client_id]['disconnected_at'] = datetime.datetime.now().isoformat()
        
        self.canvas_stats['active_clients'] = len(self.client_connections)
        
        debug_log(f"✅ [Canvas] Client disconnected", {
            "client_id": client_id,
            "total_clients": len(self.client_connections)
        })
        
        return {
            'success': True,
            'operation': 'disconnect',
            'client_id': client_id
        }
    
    async def _handle_unknown_operation(self, data: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        """Handle unknown operation types."""
        operation_type = data.get('type', 'unknown')
        
        # debug_log(f"⚠️ [Canvas] Unknown operation type", {
        #     "client_id": client_id,
        #     "operation_type": operation_type,
        #     "data": data
        # })
        
        return {
            'success': False,
            'error': f'Unknown operation type: {operation_type}'
        }
    
    def _update_client_state(self, client_id: str, operation_type: str, data: Dict[str, Any]):
        """Update client state information."""
        if client_id in self.client_states:
            self.client_states[client_id]['last_activity'] = datetime.datetime.now().isoformat()
            self.client_states[client_id]['last_operation'] = operation_type
            self.client_states[client_id]['operation_count'] = self.client_states[client_id].get('operation_count', 0) + 1
    
    def get_canvas_data(self, client_id: Optional[str] = None) -> Dict[str, Any]:
        """Get canvas data for a specific client or all data."""
        if client_id:
            # Return only elements owned by the client
            client_elements = self.client_canvases.get(client_id, set())
            return {element_id: self.canvas_data[element_id] for element_id in client_elements if element_id in self.canvas_data}
        else:
            # Return all canvas data
            return self.canvas_data.copy()
    
    def get_client_status(self, client_id: str) -> Dict[str, Any]:
        """Get status information for a specific client."""
        if client_id in self.client_states:
            return self.client_states[client_id].copy()
        return {}
    
    def get_canvas_statistics(self) -> Dict[str, Any]:
        """Get canvas operation statistics."""
        uptime = datetime.datetime.now() - self.canvas_stats['start_time']
        
        return {
            'total_operations': self.canvas_stats['total_operations'],
            'operations_by_type': dict(self.canvas_stats['operations_by_type']),
            'active_clients': self.canvas_stats['active_clients'],
            'total_canvas_elements': self.canvas_stats['total_canvas_elements'],
            'uptime_seconds': uptime.total_seconds(),
            'start_time': self.canvas_stats['start_time'].isoformat()
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get canvas service status."""
        return {
            'total_canvas_elements': self.canvas_stats['total_canvas_elements'],
            'active_clients': len(self.client_connections),
            'total_clients': len(self.client_states),
            'total_operations': self.canvas_stats['total_operations']
        }
    
    async def cleanup(self):
        """Clean up canvas service resources."""
        debug_log(f"🧹 [Canvas] Cleaning up canvas service")
        
        # Clear all data
        self.canvas_data.clear()
        self.client_canvases.clear()
        self.client_states.clear()
        self.client_connections.clear()
        
        # Reset statistics
        self.canvas_stats.clear()
        self.canvas_stats['start_time'] = datetime.datetime.now()
        
        debug_log(f"🧹 [Canvas] Canvas service cleanup completed")

    def set_debug_mode(self, enabled: bool):
        """Enable or disable debug logging for canvas operations."""
        self.debug_mode = enabled
        debug_log(f"🔧 [Canvas] Debug mode {'enabled' if enabled else 'disabled'}")

    def get_debug_mode(self) -> bool:
        """Get current debug mode status."""
        return self.debug_mode
