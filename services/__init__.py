"""
Services module for TensorDock server.
Handles HTTP proxy, canvas operations, widget communication, WebSocket bridging, and Yjs document synchronization.
"""

from .http_proxy import HTTPProxyService
from .canvas_service import CanvasService
from .widget_service import WidgetService
from .websocket_bridge import WebSocketBridge
from .yjs_service import YjsDocumentService
from .document_sync_service import DocumentSyncService

__all__ = [
    'HTTPProxyService',
    'CanvasService',
    'WidgetService',
    'WebSocketBridge',
    'YjsDocumentService',
    'DocumentSyncService'
]
