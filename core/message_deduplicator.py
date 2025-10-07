"""
Message deduplication service for TensorDock server.
Centralizes all message deduplication logic to prevent redundancy.
"""

from typing import Dict, Set, Any
from core.logging import LoggerMixin, debug_log


class MessageDeduplicator(LoggerMixin):
    """Centralized message deduplication service."""
    
    def __init__(self):
        # Global message tracking
        self.processed_messages: Set[str] = set()  # Track all processed message IDs
        self.comm_message_tracker: Dict[str, Set[str]] = {}  # comm_id -> set of processed msg_ids
        self.most_recent_comm_messages: Dict[str, Dict[str, Any]] = {}  # kernel_id -> most recent comm message
        
        debug_log(f"🔄 [MessageDeduplicator] Message deduplication service initialized")
    
    def is_duplicate(self, msg_id: str, comm_id: str = None, kernel_id: str = None) -> bool:
        """Check if a message is a duplicate."""
        if not msg_id:
            return False
            
        # Check global processed messages
        if msg_id in self.processed_messages:
            debug_log(f"🔄 [MessageDeduplicator] Duplicate message detected", {
                "msg_id": msg_id,
                "comm_id": comm_id,
                "kernel_id": kernel_id
            })
            return True
        
        # Check comm message tracker
        if comm_id and comm_id in self.comm_message_tracker:
            if msg_id in self.comm_message_tracker[comm_id]:
                debug_log(f"🔄 [MessageDeduplicator] Duplicate comm message detected", {
                    "msg_id": msg_id,
                    "comm_id": comm_id,
                    "kernel_id": kernel_id
                })
                return True
        
        return False
    
    def mark_processed(self, msg_id: str, comm_id: str = None, kernel_id: str = None, message: Dict[str, Any] = None):
        """Mark a message as processed."""
        if not msg_id:
            return
            
        # Add to global processed messages
        self.processed_messages.add(msg_id)
        
        # Track comm messages by comm_id
        if comm_id:
            if comm_id not in self.comm_message_tracker:
                self.comm_message_tracker[comm_id] = set()
            self.comm_message_tracker[comm_id].add(msg_id)
        
        # Track most recent comm message by kernel
        if kernel_id and comm_id and message:
            self.most_recent_comm_messages[kernel_id] = {
                'comm_id': comm_id,
                'msg_id': msg_id,
                'message': message
            }
        
        debug_log(f"✅ [MessageDeduplicator] Message marked as processed", {
            "msg_id": msg_id,
            "comm_id": comm_id,
            "kernel_id": kernel_id
        })
    
    def cleanup_old_messages(self, max_age_seconds: int = 3600):
        """Clean up old processed messages to prevent memory leaks."""
        # This is a simple implementation - in production, you might want to use timestamps
        # For now, we'll just clear if we have too many messages
        if len(self.processed_messages) > 10000:
            # Keep only the most recent 5000 messages
            recent_messages = list(self.processed_messages)[-5000:]
            self.processed_messages = set(recent_messages)
            
            debug_log(f"🧹 [MessageDeduplicator] Cleaned up old messages", {
                "remaining_count": len(self.processed_messages)
            })
    
    def get_stats(self) -> Dict[str, Any]:
        """Get deduplication statistics."""
        return {
            'processed_messages_count': len(self.processed_messages),
            'comm_trackers_count': len(self.comm_message_tracker),
            'most_recent_comm_messages_count': len(self.most_recent_comm_messages)
        }
