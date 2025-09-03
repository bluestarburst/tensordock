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
from services import HTTPProxyService, CanvasService, WidgetService, WebSocketBridge


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
        
        # Set up module integrations
        self._setup_module_integrations()
        
        # Set up cross-references between messaging components
        self.message_broker.set_worker_manager(self.worker_manager)
        
        # Start messaging system
        asyncio.create_task(self._start_messaging_system())
        
        # Initialize Jupyter manager
        asyncio.create_task(self.initialize_jupyter())
        
        debug_log(f"🚀 [Server] Modular TensorDock server initialized")
    
    def _setup_module_integrations(self):
        """Set up integrations between modules."""
        # Set up Jupyter manager
        self.jupyter_manager.set_broadcast_callback(self.broadcast)
        self.jupyter_manager.set_websocket_bridge(self.websocket_bridge)
        
        # Set up action processor
        self.action_processor.set_jupyter_manager(self.jupyter_manager)
        self.action_processor.set_broadcast_callback(self.broadcast)
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
        self.message_broker.add_routing_rule('execute_code', 'action')
        self.message_broker.add_routing_rule('comm_msg', 'action')
        self.message_broker.add_routing_rule('kernel_message', 'action')
        self.message_broker.add_routing_rule('input', 'input')
        self.message_broker.add_routing_rule('sudo_http_request', 'action')
        self.message_broker.add_routing_rule('canvas_data', 'action')
        self.message_broker.add_routing_rule('start_kernel', 'action')
        self.message_broker.add_routing_rule('restart_kernel', 'action')
        self.message_broker.add_routing_rule('websocket_connect', 'action')
        self.message_broker.add_routing_rule('websocket_message', 'action')
        self.message_broker.add_routing_rule('websocket_close', 'action')
        
        # Register action handlers with worker manager
        self.worker_manager.register_task_handler('execute_code', self.action_processor._handle_execute_code)
        self.worker_manager.register_task_handler('comm_msg', self.action_processor._handle_comm_msg)
        self.worker_manager.register_task_handler('kernel_message', self.action_processor._handle_kernel_message)
        self.worker_manager.register_task_handler('start_kernel', self.action_processor._handle_start_kernel)
        self.worker_manager.register_task_handler('restart_kernel', self.action_processor._handle_restart_kernel)
        self.worker_manager.register_task_handler('interrupt_kernel', self.action_processor._handle_interrupt_kernel)
        self.worker_manager.register_task_handler('input', self.action_processor._handle_input)
        self.worker_manager.register_task_handler('sudo_http_request', self.action_processor._handle_sudo_http_request)
        self.worker_manager.register_task_handler('canvas_data', self.action_processor._handle_canvas_data)
        self.worker_manager.register_task_handler('websocket_connect', self.action_processor._handle_websocket_connect)
        self.worker_manager.register_task_handler('websocket_message', self.action_processor._handle_websocket_message)
        self.worker_manager.register_task_handler('websocket_close', self.action_processor._handle_websocket_close)
        
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
                'execute_code',
                'comm_msg',
                'kernel_message',
                'input',
                'canvas_data',
                'events',
                'start_kernel',
                'restart_kernel',
                'websocket_connect',
                'websocket_message',
                'websocket_close'
            ]
            
            import asyncio
            
            def register(action_name: str):
                def listener(data):
                    # Normalize payload to include action and client id
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


async def main():
    """Main server function."""
    try:
        # Setup logging with file output
        logger = setup_logging(log_file="tensordock_server.log")
        debug_log(f"🚀 [Main] Starting Modular TensorDock Server")
        
        # Create server instance
        server = ModularTensorDockServer()
        
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
