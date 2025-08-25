"""
Services module for TensorDock server.
Handles HTTP proxy, canvas operations, widget communication, and WebSocket bridging.
"""

from .http_proxy import HTTPProxyService
from .canvas_service import CanvasService
from .widget_service import WidgetService
from .websocket_bridge import WebSocketBridge

__all__ = [
    'HTTPProxyService',
    'CanvasService',
    'WidgetService',
    'WebSocketBridge'
]
