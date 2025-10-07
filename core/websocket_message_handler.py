"""
WebSocket message handling utilities.
Centralizes common WebSocket message handling patterns.
"""

from typing import Dict, Any, Optional, Callable
from core.logging import debug_log
from core.jupyter_message_factory import JupyterMessageFactory
from core.message_deduplicator import MessageDeduplicator


class WebSocketMessageHandler:
    """Common WebSocket message handling utilities."""
    
    def __init__(self, deduplicator: MessageDeduplicator):
        self.deduplicator = deduplicator
    
    def process_jupyter_message(self, message: Dict[str, Any], kernel_id: str, 
                              channel: str = 'shell') -> Optional[Dict[str, Any]]:
        """Process a Jupyter message with common handling patterns."""
        try:
            # Extract message details using factory
            msg_info = JupyterMessageFactory.extract_message_info(message)
            msg_type = msg_info['msg_type'] or 'unknown'
            msg_id = msg_info['msg_id'] or 'unknown'
            comm_id = msg_info['comm_id']
            parent_msg_id = msg_info['parent_msg_id']
            
            # Check for duplicate message processing
            if self.deduplicator.is_duplicate(msg_id, comm_id, kernel_id):
                debug_log(f"🔄 [WebSocketMessageHandler] Skipping duplicate message", {
                    "kernel_id": kernel_id,
                    "channel": channel,
                    "msg_type": msg_type,
                    "msg_id": msg_id
                })
                return None
            
            # Mark message as processed
            self.deduplicator.mark_processed(msg_id, comm_id, kernel_id, message)
            
            # Return processed message info
            return {
                'msg_type': msg_type,
                'msg_id': msg_id,
                'comm_id': comm_id,
                'parent_msg_id': parent_msg_id,
                'message': message
            }
            
        except Exception as e:
            debug_log(f"❌ [WebSocketMessageHandler] Error processing message", {
                "error": str(e),
                "kernel_id": kernel_id,
                "channel": channel
            })
            return None
    
    def should_log_message(self, msg_type: str, msg_id: str) -> bool:
        """Determine if a message should be logged based on type and frequency."""
        # Always log important message types
        important_types = ['execute_input', 'execute_result', 'error', 'stream']
        if msg_type in important_types:
            return True
        
        # For other types, log occasionally to reduce noise
        return hash(msg_id) % 10 == 0
    
    def create_broadcast_message(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a standardized broadcast message."""
        return {
            'action': action,
            'timestamp': data.get('timestamp'),
            'data': data
        }
