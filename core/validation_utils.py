"""
Validation utilities for common validation patterns.
Centralizes validation logic to eliminate duplication.
"""

from typing import Dict, Any, List, Optional


class ValidationUtils:
    """Common validation utilities."""
    
    @staticmethod
    def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> Optional[str]:
        """Validate that all required fields are present in the data."""
        missing_fields = [field for field in required_fields if field not in data or data[field] is None]
        if missing_fields:
            return f"Missing required fields: {', '.join(missing_fields)}"
        return None
    
    @staticmethod
    def validate_websocket_connection(websocket_bridge, action_name: str) -> Optional[str]:
        """Validate that WebSocket bridge is available."""
        if not websocket_bridge:
            return f"WebSocket bridge not available for {action_name}"
        return None
    
    @staticmethod
    def validate_jupyter_connection(jupyter_manager, action_name: str) -> Optional[str]:
        """Validate that Jupyter manager is available."""
        if not jupyter_manager:
            return f"Jupyter manager not available for {action_name}"
        return None
    
    @staticmethod
    def validate_kernel_connection(instance_id: str, kernel_id: str) -> Optional[str]:
        """Validate kernel connection parameters."""
        if not instance_id:
            return "Missing instanceId"
        if not kernel_id:
            return "Missing kernelId"
        return None
    
    @staticmethod
    def validate_http_request(url: str, method: str) -> Optional[str]:
        """Validate HTTP request parameters."""
        if not url:
            return "URL cannot be None"
        if not method:
            return "Method cannot be None"
        return None
