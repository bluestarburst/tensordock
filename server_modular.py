"""
Modular TensorDock server using the new WebRTC, Jupyter, Messaging, and Service layer structure.
This is a fully refactored version of the original server.py with no legacy code.
"""
import asyncio
import json
import threading
import time
import uuid
import datetime
import sys
import os
from aiohttp import web

# Add the tensordock directory to Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from core.config import ServerConfig
from core.logging import setup_logging, debug_log
from webrtc.peer_manager import WebRTCPeerManager
from webrtc.signaling import SignalingManager
from jupyter_module import JupyterManager
from messaging import MessageBroker, WorkerManager, ActionProcessor
from services import HTTPProxyService, CanvasService, WidgetService, WebSocketBridge, YjsDocumentService, DocumentSyncService

class ModularTensorDockServer:
    """Modular TensorDock server using the new module structure."""
    
    def __init__(self):
        # Initialize configuration
        self.config = ServerConfig()
        
        # Initialize modules
        self.peer_manager = WebRTCPeerManager(self.config)
        self.signaling_manager = SignalingManager()
        self.jupyter_manager = JupyterManager(self.config)
        
        # Initialize messaging system
        self.message_broker = MessageBroker()
        self.worker_manager = WorkerManager(max_workers=4)
        self.action_processor = ActionProcessor()
        
        # Initialize service layer
        self.http_proxy_service = HTTPProxyService(self.config)
        self.canvas_service = CanvasService()
        self.widget_service = WidgetService()
        self.websocket_bridge = WebSocketBridge(self.config)
        
        # Initialize Yjs services
        self.yjs_service = YjsDocumentService(self.config)
        self.document_sync_service = DocumentSyncService(self.config)
        
        # Set up module integrations
        self._setup_module_integrations()
        
        # Set up cross-references between messaging components
        self.message_broker.set_worker_manager(self.worker_manager)
        
        # Set up YJS service with broadcast callback
        self.yjs_service.set_broadcast_callback(self._broadcast_to_all_clients)
        
        # Set up action processor with YJS service reference
        self.action_processor.yjs_service = self.yjs_service
        
        # Initialize task references (will be started when server starts)
        self._messaging_task = None
        self._jupyter_task = None
        
        debug_log(f"🚀 [Server] Modular TensorDock server initialized")
    
    async def start(self):
        """Start the server services."""
        # Start messaging system
        self._messaging_task = asyncio.create_task(self._start_messaging_system())
        
        # Initialize Jupyter manager
        self._jupyter_task = asyncio.create_task(self.initialize_jupyter())
        
        # Start WebSocket bridge
        await self.websocket_bridge.start()
        
        debug_log(f"🚀 [Server] Server services started")
    
    def _setup_module_integrations(self):
        """Set up integrations between modules."""
        # Set up Jupyter manager
        self.jupyter_manager.set_broadcast_callback(self.broadcast)
        self.jupyter_manager.set_send_to_client(self.send_to_client)
        self.jupyter_manager.set_websocket_bridge(self.websocket_bridge)
        
        # Set up action processor
        self.action_processor.set_jupyter_manager(self.jupyter_manager)
        self.action_processor.set_broadcast_callback(self.broadcast)
        self.action_processor.set_send_to_client(self.send_to_client)
        self.action_processor.set_http_proxy_service(self.http_proxy_service)
        self.action_processor.set_canvas_service(self.canvas_service)
        self.action_processor.set_widget_service(self.widget_service)
        self.action_processor.set_peer_manager(self.peer_manager)
        self.action_processor.set_websocket_bridge(self.websocket_bridge)
        
        # Set up WebSocket bridge broadcast callback
        self.websocket_bridge.set_broadcast_callback(self.broadcast)
        
        # Route WebRTC data channel messages into the message broker
        self.peer_manager.add_connection_callback('data_channel_ready', self._on_data_channel_ready)
        
        # Set up message broker routing rules
        self.message_broker.add_routing_rule('sudo_http_request', 'action')
        self.message_broker.add_routing_rule('canvas_data', 'action')
        self.message_broker.add_routing_rule('ws_connect', 'action')
        self.message_broker.add_routing_rule('ws_message', 'action')
        self.message_broker.add_routing_rule('ws_close', 'action')
        
        # Register action handlers with worker manager
        self.worker_manager.register_task_handler('sudo_http_request', self.action_processor._handle_sudo_http_request)
        self.worker_manager.register_task_handler('canvas_data', self.action_processor._handle_canvas_data)
        self.worker_manager.register_task_handler('ws_connect', self.action_processor._handle_websocket_connect)
        self.worker_manager.register_task_handler('ws_message', self.action_processor._handle_websocket_message)
        self.worker_manager.register_task_handler('ws_close', self.action_processor._handle_websocket_close)
        
        # Register YJS message handlers
        self.worker_manager.register_task_handler('yjs_document_update', self.action_processor._handle_yjs_document_update)
        self.worker_manager.register_task_handler('yjs_awareness_update', self.action_processor._handle_yjs_awareness_update)
        self.worker_manager.register_task_handler('yjs_sync_request', self.action_processor._handle_yjs_sync_request)
        self.worker_manager.register_task_handler('yjs_request_state', self.action_processor._handle_yjs_request_state)
        self.worker_manager.register_task_handler('yjs_state_response', self.action_processor._handle_yjs_state_response)
        
        debug_log(f"🔗 [Server] Module integrations configured")

    def _on_data_channel_ready(self, client_id, channel):
        """Attach listeners to a client's WebRTC message handler and forward to broker."""
        try:
            handler = self.peer_manager.get_message_handler(client_id)
            if not handler:
                debug_log(f"⚠️ [Server] No message handler for client", {"client_id": client_id})
                return
            
            # Known actions to forward
            actions = [
                'sudo_http_request',
                'canvas_data',
                'ws_connect',
                'ws_message',
                'ws_close',
                'yjs_document_update',
                'yjs_awareness_update',
                'yjs_sync_request',
                'yjs_request_state',
                'yjs_state_response'
            ]
            
            import asyncio
            
            def register(action_name: str):
                def listener(client_id, data):
                    # ✅ CRITICAL FIX: Preserve wrapped message structure instead of flattening
                    # The frontend sends properly wrapped messages that should be preserved
                    if isinstance(data, dict) and 'instanceId' in data and 'url' in data and 'data' in data:
                        # This is a properly wrapped WebSocket message - preserve the structure
                        message = {
                            'action': action_name,
                            'client_id': client_id,
                            'instanceId': data.get('instanceId'),
                            'url': data.get('url'),
                            'data': data.get('data'),
                            'timestamp': data.get('timestamp')
                        }
                    else:
                        # Legacy handling for non-wrapped messages
                        message = {'action': action_name, 'client_id': client_id}
                        if isinstance(data, dict):
                            message.update(data)
                        else:
                            message['data'] = data
                    # Forward to message broker
                    asyncio.create_task(self.message_broker.route_message(message))
                handler.add_listener(action_name, listener)
            
            for act in actions:
                register(act)
            
            debug_log(f"🔗 [Server] Data channel listeners attached", {
                "client_id": client_id,
                "actions": actions
            })
        except Exception as e:
            debug_log(f"❌ [Server] Failed to attach data channel listeners", {
                "client_id": client_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def _start_messaging_system(self):
        """Start the messaging system components."""
        try:
            debug_log(f"🚀 [Server] Starting messaging system")
            
            # Start message broker
            await self.message_broker.start()
            
            # Start worker manager
            await self.worker_manager.start_workers()
            
            debug_log(f"✅ [Server] Messaging system started successfully")
            
        except Exception as e:
            debug_log(f"❌ [Server] Failed to start messaging system", {
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def initialize_jupyter(self):
        """Initialize the Jupyter manager."""
        try:
            debug_log(f"🚀 [Server] Initializing Jupyter manager")
            
            # Wait a bit for the server to start
            await asyncio.sleep(5)
            
            success = await self.jupyter_manager.initialize()
            if success:
                debug_log(f"✅ [Server] Jupyter manager initialized successfully")
            else:
                debug_log(f"❌ [Server] Failed to initialize Jupyter manager")
                
        except Exception as e:
            debug_log(f"❌ [Server] Jupyter initialization error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def handle_client(self, offer):
        """Handle new client connection using WebRTC peer manager."""
        try:
            debug_log(f"🔗 [Server] New client connection request")
            
            # Use the peer manager to handle the client
            response = await self.peer_manager.handle_client_offer(offer)
            
            debug_log(f"✅ [Server] Client connection established")
            
            return response
            
        except Exception as e:
            debug_log(f"❌ [Server] Client connection error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            raise
    
    async def broadcast(self, message, client_id=None):
        """Broadcast message to clients using WebRTC peer manager."""
        try:
            debug_log(f"📤 [Server] Broadcasting message", {
                "action": message.get('action'),
                "exclude_client_id": client_id
            })
            
            return self.peer_manager.broadcast_message(message, client_id)
            
        except Exception as e:
            debug_log(f"❌ [Server] Broadcast error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            return 0

    async def send_to_client(self, client_id, message):
        """Send a message to a specific client."""
        try:
            debug_log(f"📤 [Server] Sending message to client", {
                "client_id": client_id,
                "action": message.get('action')
            })
            return self.peer_manager.send_message(client_id, message)
        except Exception as e:
            debug_log(f"❌ [Server] Failed to send message to client", {
                "client_id": client_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    def get_server_status(self) -> dict:
        """Get comprehensive server status."""
        return {
            'server_type': 'modular',
            'modules': {
                'webrtc': self.peer_manager.get_status(),
                'jupyter': self.jupyter_manager.get_status(),
                'signaling': {
                    'total_offers': len(self.signaling_manager.offers)
                },
                'messaging': {
                    'broker': self.message_broker.get_queue_status(),
                    'worker': self.worker_manager.get_worker_status(),
                    'action_processor': self.action_processor.get_status()
                },
                'services': {
                    'http_proxy': self.http_proxy_service.get_status(),
                    'canvas': self.canvas_service.get_status(),
                    'widget': self.widget_service.get_status(),
                    'websocket_bridge': self.websocket_bridge.get_status()
                }
            }
        }
    
    async def cleanup(self):
        """Clean up server resources."""
        debug_log(f"🧹 [Server] Cleaning up server")
        
        # Cleanup modules
        await self.jupyter_manager.cleanup()
        await self.message_broker.cleanup()
        await self.worker_manager.cleanup()
        await self.action_processor.cleanup()
        
        # Cleanup services
        await self.http_proxy_service.cleanup()
        await self.canvas_service.cleanup()
        await self.widget_service.cleanup()
        await self.websocket_bridge.cleanup()
        
        debug_log(f"🧹 [Server] Server cleanup completed")

    async def _broadcast_to_all_clients(self, message: dict):
        """Broadcast a message to all connected WebRTC clients."""
        try:
            # Get all connected clients
            connected_clients = self.peer_manager.get_connected_clients()
            
            if not connected_clients:
                debug_log(f"⚠️ [Server] No connected clients to broadcast to")
                return
            
            debug_log(f"📡 [Server] Broadcasting message to {len(connected_clients)} clients", {
                "action": message.get('action'),
                "client_count": len(connected_clients)
            })
            
            # Send message to each client
            for client_id in connected_clients:
                try:
                    # Send the message through WebRTC using peer manager
                    success = self.peer_manager.send_message(client_id, message)
                    if not success:
                        debug_log(f"⚠️ [Server] Failed to send message to client {client_id}")
                except Exception as e:
                    debug_log(f"❌ [Server] Error broadcasting to client {client_id}", {
                        "error": str(e),
                        "error_type": type(e).__name__
                    })
            
            debug_log(f"✅ [Server] Broadcast completed to {len(connected_clients)} clients")
            
        except Exception as e:
            debug_log(f"❌ [Server] Error in broadcast_to_all_clients", {
                "error": str(e),
                "error_type": type(e).__name__
            })


async def handle_offer(request):
    """Handle WebRTC offer from client."""
    try:
        params = await request.json()
        server = request.app['server']
        response = await server.handle_client(params)
        return web.Response(
            content_type="application/json",
            text=json.dumps(response)
        )
    except Exception as e:
        debug_log(f"❌ [HTTP] Offer handling error", {
            "error": str(e),
            "error_type": type(e).__name__
        })
        return web.Response(
            content_type="application/json",
            text=json.dumps({'error': str(e)}),
            status=500
        )


async def handle_status(request):
    """Handle status request."""
    try:
        server = request.app['server']
        status = server.get_server_status()
        return web.Response(
            content_type="application/json",
            text=json.dumps(status)
        )
    except Exception as e:
        debug_log(f"❌ [HTTP] Status handling error", {
            "error": str(e),
            "error_type": type(e).__name__
        })
        return web.Response(
            content_type="application/json",
            text=json.dumps({'error': str(e)}),
            status=500
        )


async def handle_yjs_document(request):
    """Handle Yjs document requests."""
    try:
        document_id = request.match_info['document_id']
        server = request.app['server']
        doc_state = await server.document_sync_service.get_document_state(document_id)
        
        if doc_state:
            return web.json_response(doc_state)
        else:
            return web.json_response({"error": "Document not found"}, status=404)
            
    except Exception as e:
        debug_log(f"❌ [YJS] Document handling error", {
            "error": str(e),
            "error_type": type(e).__name__
        })
        return web.json_response({"error": str(e)}, status=500)


async def handle_yjs_sync(request):
    """Handle Yjs sync requests."""
    try:
        document_id = request.match_info['document_id']
        data = await request.json()
        
        # Handle sync logic
        return web.json_response({"status": "success"})
        
    except Exception as e:
        debug_log(f"❌ [YJS] Sync handling error", {
            "error": str(e),
            "error_type": type(e).__name__
        })
        return web.json_response({"error": str(e)}, status=500)


async def handle_yjs_update(request):
    """Handle Yjs update requests."""
    try:
        document_id = request.match_info['document_id']
        data = await request.json()
        server = request.app['server']
        
        changes = data.get("changes", [])
        client_id = data.get("client_id")
        
        success = await server.document_sync_service.update_document(document_id, changes, client_id)
        
        if success:
            return web.json_response({"status": "success"})
        else:
            return web.json_response({"error": "Update failed"}, status=400)
            
    except Exception as e:
        debug_log(f"❌ [YJS] Update handling error", {
            "error": str(e),
            "error_type": type(e).__name__
        })
        return web.json_response({"error": str(e)}, status=500)


async def handle_websocket_events(request):
    """Handle WebSocket connections to /api/events/subscribe."""
    try:
        debug_log(f"🔌 [WebSocket] Events WebSocket connection request")
        
        # Create WebSocket connection
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        # Store the WebSocket connection
        server = request.app['server']
        connection_id = f"events_{datetime.datetime.now().timestamp()}"
        
        # Add to WebSocket bridge
        await server.websocket_bridge.add_frontend_connection(
            connection_id, 
            ws, 
            connection_type='events'
        )
        
        debug_log(f"✅ [WebSocket] Events WebSocket connected", {
            "connection_id": connection_id
        })
        
        # Handle messages
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    debug_log(f"📥 [WebSocket] Events message received", {
                        "connection_id": connection_id,
                        "data": data
                    })
                    
                    # Handle client message
                    await server.websocket_bridge.handle_frontend_websocket_message(connection_id, data)
                    
                except json.JSONDecodeError as e:
                    debug_log(f"❌ [WebSocket] Invalid JSON in events message", {
                        "connection_id": connection_id,
                        "error": str(e)
                    })
            elif msg.type == web.WSMsgType.ERROR:
                debug_log(f"❌ [WebSocket] Events WebSocket error", {
                    "connection_id": connection_id,
                    "error": str(ws.exception())
                })
                break
        
        # Clean up connection
        await server.websocket_bridge.remove_frontend_connection(connection_id)
        
        debug_log(f"🔌 [WebSocket] Events WebSocket disconnected", {
            "connection_id": connection_id
        })
        
        return ws
        
    except Exception as e:
        debug_log(f"❌ [WebSocket] Events WebSocket error", {
            "error": str(e),
            "error_type": type(e).__name__
        })
        return web.Response(status=500)


async def handle_websocket_kernel(request):
    """Handle WebSocket connections to /api/kernels/{kernel_id}/channels."""
    try:
        kernel_id = request.match_info['kernel_id']
        debug_log(f"🔌 [WebSocket] Kernel WebSocket connection request", {
            "kernel_id": kernel_id
        })
        
        # Create WebSocket connection
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        # Store the WebSocket connection
        server = request.app['server']
        connection_id = f"kernel_{kernel_id}_{datetime.datetime.now().timestamp()}"
        
        # Add to WebSocket bridge
        await server.websocket_bridge.add_frontend_connection(
            connection_id, 
            ws, 
            connection_type='kernel',
            kernel_id=kernel_id
        )
        
        debug_log(f"✅ [WebSocket] Kernel WebSocket connected", {
            "connection_id": connection_id,
            "kernel_id": kernel_id
        })
        
        # Handle messages
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    debug_log(f"📥 [WebSocket] Kernel message received", {
                        "connection_id": connection_id,
                        "kernel_id": kernel_id,
                        "msg_type": data.get('header', {}).get('msg_type', 'unknown'),
                        "msg_id": data.get('header', {}).get('msg_id', 'unknown')
                    })
                    
                    # Handle client message
                    await server.websocket_bridge.handle_frontend_websocket_message(connection_id, data)
                    
                except json.JSONDecodeError as e:
                    debug_log(f"❌ [WebSocket] Invalid JSON in kernel message", {
                        "connection_id": connection_id,
                        "kernel_id": kernel_id,
                        "error": str(e)
                    })
            elif msg.type == web.WSMsgType.ERROR:
                debug_log(f"❌ [WebSocket] Kernel WebSocket error", {
                    "connection_id": connection_id,
                    "kernel_id": kernel_id,
                    "error": str(ws.exception())
                })
                break
        
        # Clean up connection
        await server.websocket_bridge.remove_frontend_connection(connection_id)
        
        debug_log(f"🔌 [WebSocket] Kernel WebSocket disconnected", {
            "connection_id": connection_id,
            "kernel_id": kernel_id
        })
        
        return ws
        
    except Exception as e:
        debug_log(f"❌ [WebSocket] Kernel WebSocket error", {
            "kernel_id": kernel_id if 'kernel_id' in locals() else 'unknown',
            "error": str(e),
            "error_type": type(e).__name__
        })
        return web.Response(status=500)


async def main():
    """Main server function."""
    try:
        # Setup logging with file output
        logger = setup_logging(log_file="tensordock_server.log")
        debug_log(f"🚀 [Main] Starting Modular TensorDock Server")
        
        # Create server instance
        server = ModularTensorDockServer()
        
        # Start server services
        await server.start()
        
        # Create aiohttp app
        app = web.Application()
        app['server'] = server
        
        # Add routes
        app.router.add_post("/offer", handle_offer)
        app.router.add_get("/status", handle_status)
        
        # Setup runner
        runner = web.AppRunner(app)
        await runner.setup()
        
        # Start site
        port = int(os.environ.get('VAST_TCP_PORT_70000', 8765))
        site = web.TCPSite(runner, "0.0.0.0", port)
        
        debug_log(f"🌐 [Main] Starting HTTP server on port {port}")
        await site.start()
        
        # Start WebSocket bridge service
        debug_log(f"🔌 [Main] Starting WebSocket bridge service")
        await server.websocket_bridge.start()
        
        # Start Yjs WebSocket server
        if server.config.yjs_enabled:
            debug_log(f"🔗 [Main] Starting Yjs WebSocket server on port {server.config.yjs_port}")
            await server.yjs_service.start_websocket_server(
                host=server.config.yjs_host,
                port=server.config.yjs_port
            )
        
        debug_log(f"✅ [Main] Modular TensorDock Server started successfully")
        print(f"Modular server started at http://0.0.0.0:{port}")
        
        # Run forever
        await asyncio.Future()
        
    except Exception as e:
        debug_log(f"❌ [Main] Server startup error", {
            "error": str(e),
            "error_type": type(e).__name__
        })
        raise
    finally:
        # Cleanup
        if 'server' in locals():
            await server.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
