"""
Minimal WebSocket Bridge Service for TensorDock.
URL-based schema only:
- ws_connect: create or reuse a single backend WebSocket per URL; add subscriber (instanceId)
- ws_message: send raw message to backend WebSocket identified by URL
- ws_close: remove subscriber; close backend WebSocket when last subscriber leaves

All inbound messages from the backend WebSocket are broadcast to ALL subscribers of that URL
using a single broadcast callback with action 'ws_message'.
"""

import asyncio
import json
import datetime
from typing import Dict, Any, Optional, Callable, Set
from websockets.client import connect

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log
from core.config import ServerConfig


class WebSocketBridge(LoggerMixin):
    """Minimal URL-based WebSocket bridge over WebRTC."""

    def __init__(self, config: ServerConfig):
        super().__init__()
        self.config = config

        # URL -> backend websocket connection
        self._url_to_ws: Dict[str, Any] = {}
        # URL -> set(instance_id) subscribers
        self._url_to_subscribers: Dict[str, Set[str]] = {}
        # URL -> listener task
        self._url_to_task: Dict[str, asyncio.Task] = {}

        # Broadcast callback to WebRTC layer (set by server)
        self.broadcast_callback: Optional[Callable] = None

        # Send to client callback (set by server)
        self.send_to_client: Optional[Callable] = None

        debug_log("🔌 [WebSocketBridge] Minimal URL-based bridge initialized")

    async def start(self):
        """Start the bridge (no-op placeholder for lifecycle compatibility)."""
        debug_log("🔌 [WebSocketBridge] start() called - minimal bridge ready")

    def set_broadcast_callback(self, callback: Callable):
        self.broadcast_callback = callback
        debug_log("🔌 [WebSocketBridge] Broadcast callback set")

    def set_send_to_client(self, send_to_client: Callable):
        """Set the callback for sending messages to clients."""
        self.send_to_client = send_to_client
        debug_log("🔌 [WebSocketBridge] Send to client callback set")

    def _normalize_url(self, url: str) -> str:
        """Normalize incoming URL to real ws:// or wss:// Jupyter URL.
        Handles webrtc://jupyter prefix and adds token when needed.
        """
        try:
            if url.startswith('webrtc://jupyter'):
                jupyter_path = url.replace('webrtc://jupyter', '')
                token = self.config.get_jupyter_token() or "test"
                sep = "&" if "?" in jupyter_path else "?"
                return f"ws://localhost:8888{jupyter_path}{sep}token={token}"
            if url.startswith('http://'):
                return url.replace('http://', 'ws://')
            if url.startswith('https://'):
                return url.replace('https://', 'wss://')
            if url.startswith('ws://') or url.startswith('wss://'):
                return url
            # Assume relative path on Jupyter
            token = self.config.get_jupyter_token() or "test"
            sep = "&" if "?" in url else "?"
            return f"ws://localhost:8888{url}{sep}token={token}"
        except Exception:
            return url

    async def connect_websocket(self, instance_id: str, url: str) -> bool:
        """ws_connect: Ensure a backend WebSocket for URL and add subscriber.
        - If URL exists, ensure subscriber is registered.
        - If backend WS missing or closed, create it and initialize maps.
        """
        try:
            if not instance_id or not url:
                return False
            ws_url = self._normalize_url(url)

            # Ensure subscriber set exists for URL
            subs = self._url_to_subscribers.get(ws_url)
            if subs is None:
                subs = set()
                self._url_to_subscribers[ws_url] = subs
            # Add subscriber if not present
            if instance_id not in subs:
                subs.add(instance_id)

            # Check backend websocket existence/health
            websocket = self._url_to_ws.get(ws_url)
            ws_closed = False
            try:
                ws_closed = bool(getattr(websocket, 'closed', False)) if websocket is not None else True
            except Exception:
                ws_closed = True

            debug_log("🔌 [WebSocketBridge] connect_websocket", {"url": ws_url, "instance_id": instance_id, "websocket": websocket, "ws_closed": ws_closed})

            if websocket is None or ws_closed:
                debug_log("🔌 [WebSocketBridge] Connecting backend WebSocket", {"url": ws_url})
                websocket = await connect(
                    ws_url,
                    extra_headers=self.config.get_jupyter_headers() or {},
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=10
                )
                self._url_to_ws[ws_url] = websocket

                # Cancel any stale listener and start a fresh one
                old_task = self._url_to_task.get(ws_url)
                if old_task and not old_task.done():
                    old_task.cancel()
                    try:
                        await old_task
                    except asyncio.CancelledError:
                        pass
                task = asyncio.create_task(self._listen_ws(ws_url, websocket))
                self._url_to_task[ws_url] = task

            # Notify this subscriber of connection
            if self.broadcast_callback:
                await self.broadcast_callback({
                    'action': 'ws_connected',
                    'instanceId': instance_id,
                    'url': ws_url,
                    'timestamp': datetime.datetime.now().isoformat()
                })

            return True
        except Exception as e:
            debug_log("❌ [WebSocketBridge] ws_connect failed", {"url": url, "error": str(e)})
            return False

    async def send_ws_message_by_url(self, instance_id: str, url: str, data: Any) -> bool:
        """ws_message: Send raw data to backend WebSocket identified by URL."""
        try:
            if not url:
                return False
            ws_url = self._normalize_url(url)
            websocket = self._url_to_ws.get(ws_url)
            # Attempt lazy init if somehow missing (no-op for subscribers here)
            if websocket is None or bool(getattr(websocket, 'closed', False)):
                debug_log("⚠️ [WebSocketBridge] Backend WS missing/closed on send; attempting reconnect", {"url": ws_url})
                websocket = await connect(
                    ws_url,
                    extra_headers=self.config.get_jupyter_headers() or {},
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=10
                )
                self._url_to_ws[ws_url] = websocket
                # restart listener
                old_task = self._url_to_task.get(ws_url)
                if old_task and not old_task.done():
                    old_task.cancel()
                    try:
                        await old_task
                    except asyncio.CancelledError:
                        pass
                self._url_to_task[ws_url] = asyncio.create_task(self._listen_ws(ws_url, websocket))
            payload = data if isinstance(data, str) else json.dumps(data)
            await websocket.send(payload)
            return True
        except Exception as e:
            debug_log("❌ [WebSocketBridge] ws_message send failed", {"url": url, "error": str(e)})
            return False

    async def ws_close(self, instance_id: str, url: str) -> bool:
        """ws_close: Remove subscriber; close backend WebSocket if last subscriber leaves."""
        try:
            ws_url = self._normalize_url(url)
            subs = self._url_to_subscribers.get(ws_url)
            if subs and instance_id in subs:
                subs.discard(instance_id)
            # Close if no subscribers remain
            if not subs or len(subs) == 0:
                await self._close_backend_ws(ws_url)
            return True
        except Exception as e:
            debug_log("❌ [WebSocketBridge] ws_close failed", {"url": url, "error": str(e)})
            return False

    async def _close_backend_ws(self, ws_url: str):
        websocket = self._url_to_ws.get(ws_url)
        if websocket:
            try:
                await websocket.close()
            except Exception:
                pass
        self._url_to_ws[ws_url] = None
        # Cancel listener task
        task = self._url_to_task.get(ws_url)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._url_to_task.pop(ws_url, None)
        # Broadcast closed to subscribers and clear
        subs = list(self._url_to_subscribers.get(ws_url, set()))
        if self.broadcast_callback and subs:
            for instance_id in subs:
                try:
                    await self.broadcast_callback({
                        'action': 'websocket_closed',
                        'instanceId': instance_id,
                        'kernelId': None,
                        'timestamp': datetime.datetime.now().isoformat()
                    })
                except Exception:
                    pass
        self._url_to_subscribers[ws_url] = set()

    async def _listen_ws(self, ws_url: str, websocket):
        """Listen for inbound messages and broadcast to all subscribers for the URL."""
        try:
            async for message in websocket:
                # Handle both string and binary messages from Jupyter
                if isinstance(message, str):
                    # Try to parse as JSON, fallback to raw string
                    try:
                        data = json.loads(message)
                        # Targeted logging for kernel IOPub traffic of interest
                        if isinstance(data, dict):
                            header = data.get('header', {}) if isinstance(data.get('header'), dict) else {}
                            msg_type = header.get('msg_type')
                            channel = data.get('channel') or 'iopub'
                            if channel == 'iopub' and (msg_type in ['comm_msg', 'comm_open', 'comm_close', 'display_data', 'update_display_data', 'clear_output', 'stream'] or (isinstance(msg_type, str) and msg_type.startswith('comm'))):
                                content = data.get('content', {}) if isinstance(data.get('content'), dict) else {}
                                comm_id = content.get('comm_id') if isinstance(content, dict) else None
                                pdata = data.get('parent_header', {}) if isinstance(data.get('parent_header'), dict) else {}
                                debug_log("📡 [WebSocketBridge] IOPub passthrough", {
                                    "msg_type": msg_type,
                                    "comm_id": comm_id,
                                    "channel": channel,
                                    "has_parent": bool(pdata),
                                    "data_keys": list((content.get('data') or {}).keys()) if isinstance(content.get('data'), dict) else None
                                })
                    except json.JSONDecodeError:
                        data = message
                elif isinstance(message, bytes):
                    # Binary message - pass through as base64 encoded string
                    import base64
                    data = {
                        "type": "binary",
                        "data": base64.b64encode(message).decode('utf-8')
                    }
                else:
                    # Other types (like dict) - pass through as-is
                    data = message

                subs = list(self._url_to_subscribers.get(ws_url, set()))
                if not subs:
                    continue

                if self.broadcast_callback:
                    for instance_id in subs:
                        try:
                            await self.broadcast_callback({
                                'action': 'ws_message',
                                'instanceId': instance_id,
                                'url': ws_url,
                                'data': data,
                                'timestamp': datetime.datetime.now().isoformat()
                            })
                        except Exception:
                            pass
        except Exception as e:
            debug_log("❌ [WebSocketBridge] Listener error", {"url": ws_url, "error": str(e)})
        finally:
            await self._close_backend_ws(ws_url)

    def get_status(self) -> Dict[str, Any]:
        """Get WebSocket bridge status."""
        total_subscribers = sum(len(subs) for subs in self._url_to_subscribers.values())
        return {
            'active_websockets': len(self._url_to_ws),
            'total_subscribers': total_subscribers,
            'urls_with_connections': len(self._url_to_subscribers),
            'active_tasks': len([t for t in self._url_to_task.values() if t and not t.done()]),
            'broadcast_callback_set': self.broadcast_callback is not None,
            'send_to_client_set': self.send_to_client is not None
        }
    
    async def cleanup(self):
        """Cleanup all backend websockets and internal maps for graceful shutdown."""
        debug_log("🧹 [WebSocketBridge] cleanup() called")
        # Close all websockets
        for url in list(self._url_to_ws.keys()):
            try:
                await self._close_backend_ws(url)
            except Exception:
                pass
        # Clear maps
        self._url_to_ws.clear()
        self._url_to_subscribers.clear()
        # Cancel any remaining tasks
        for task in list(self._url_to_task.values()):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._url_to_task.clear()
        debug_log("✅ [WebSocketBridge] cleanup() completed")
    