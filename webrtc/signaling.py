"""
WebRTC signaling management.
"""
from typing import Dict, Any, Optional

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin


class SignalingManager(LoggerMixin):
    """Manages WebRTC signaling and offer/answer exchange."""
    
    def __init__(self):
        super().__init__()
        self.pending_offers: Dict[str, Dict[str, Any]] = {}
    
    @property
    def offers(self) -> Dict[str, Dict[str, Any]]:
        """Get pending offers (alias for pending_offers for backward compatibility)."""
        return self.pending_offers
    
    def create_offer_id(self, offer: Dict[str, Any]) -> str:
        """Create a unique ID for an offer."""
        return f"offer_{id(offer)}"
    
    def store_offer(self, offer_id: str, offer: Dict[str, Any]):
        """Store a pending offer."""
        self.pending_offers[offer_id] = offer
        self.log_info(f"Stored pending offer", {"offer_id": offer_id})
    
    def get_offer(self, offer_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a stored offer."""
        return self.pending_offers.get(offer_id)
    
    def remove_offer(self, offer_id: str):
        """Remove a stored offer."""
        if offer_id in self.pending_offers:
            del self.pending_offers[offer_id]
            self.log_info(f"Removed pending offer", {"offer_id": offer_id})
    
    def validate_offer(self, offer: Dict[str, Any]) -> bool:
        """Validate an offer structure."""
        required_fields = ['type', 'sdp']
        
        for field in required_fields:
            if field not in offer:
                self.log_warning(f"Offer missing required field", {
                    "field": field,
                    "offer_keys": list(offer.keys())
                })
                return False
        
        if offer['type'] != 'offer':
            self.log_warning(f"Invalid offer type", {
                "expected": "offer",
                "received": offer['type']
            })
            return False
        
        if not offer['sdp'] or len(offer['sdp']) < 10:
            self.log_warning(f"Invalid SDP in offer", {
                "sdp_length": len(offer['sdp']) if offer['sdp'] else 0
            })
            return False
        
        return True
    
    def create_answer(self, offer: Dict[str, Any], sdp: str, answer_type: str = 'answer') -> Dict[str, Any]:
        """Create an answer response."""
        return {
            'type': answer_type,
            'sdp': sdp
        }
    
    def get_pending_offer_count(self) -> int:
        """Get number of pending offers."""
        return len(self.pending_offers)
    
    def cleanup_expired_offers(self, max_age_seconds: int = 300):
        """Clean up expired offers (placeholder for future implementation)."""
        # TODO: Implement offer expiration cleanup
        pass
