"""
WebRTC peer connection management.
"""
import datetime
from typing import Dict, Set, Optional, Callable, Any

# Make aiortc import optional for testing
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel
    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False
    # Create mock classes for testing
    class RTCPeerConnection:
        def __init__(self, configuration=None):
            self.configuration = configuration
            self.iceConnectionState = "new"
            self.iceGatheringState = "new"
            self.signalingState = "stable"
            self.connectionState = "new"
        
        def on(self, event):
            def decorator(func):
                return func
            return decorator
        
        async def setRemoteDescription(self, description):
            pass
        
        async def createAnswer(self):
            return RTCSessionDescription("answer", "mock-sdp")
        
        async def setLocalDescription(self, description):
            pass
    
    class RTCSessionDescription:
        def __init__(self, type, sdp):
            self.type = type
            self.sdp = sdp
    
    class RTCDataChannel:
        def __init__(self):
            self.label = "mock-channel"
            self.ordered = True
            self.protocol = ""
            self.readyState = "open"
            self.bufferedAmount = 0
        
        def on(self, event):
            def decorator(func):
                return func
            return decorator
        
        def send(self, data):
            pass

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log
from core.config import ServerConfig
from webrtc.data_channel import DataChannelManager
from webrtc.message_handler import WebRTCMessageHandler


class WebRTCPeerManager(LoggerMixin):
    """Manages WebRTC peer connections and their lifecycle."""
    
    def __init__(self, config: ServerConfig):
        super().__init__()
        self.config = config
        self.peer_connections: Set[RTCPeerConnection] = set()
        self.data_channel_manager = DataChannelManager()
        self.message_handlers: Dict[int, WebRTCMessageHandler] = {}
        
        # Connection event callbacks
        self.connection_callbacks: Dict[str, Set[Callable]] = {
            'new_peer': set(),
            'peer_disconnected': set(),
            'data_channel_ready': set()
        }
    
    def add_connection_callback(self, event: str, callback: Callable):
        """Add a callback for connection events."""
        if event in self.connection_callbacks:
            self.connection_callbacks[event].add(callback)
    
    def remove_connection_callback(self, event: str, callback: Callable):
        """Remove a callback for connection events."""
        if event in self.connection_callbacks:
            self.connection_callbacks[event].discard(callback)
    
    async def handle_client_offer(self, offer: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a new client connection offer."""
        client_id = id(offer)  # Use offer object ID as temporary client ID
        
        debug_log(f"🔗 [PeerManager] New client connection request", {
            "offer_type": offer.get("type"),
            "sdp_length": len(offer.get("sdp", "")) if offer.get("sdp") else 0,
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        # Create peer connection
        pc = RTCPeerConnection(configuration=self.config.rtc_config)
        self.peer_connections.add(pc)
        
        # Set up peer connection event handlers
        self._setup_peer_connection_handlers(pc, client_id)
        
        # Set remote description
        debug_log(f"🔗 [PeerManager] Setting remote description", {
            "client_id": client_id,
            "offer_type": offer.get("type"),
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        await pc.setRemoteDescription(RTCSessionDescription(
            sdp=offer["sdp"],
            type=offer["type"]
        ))
        
        # Create and set local description
        debug_log(f"🔗 [PeerManager] Creating answer", {
            "client_id": client_id,
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        
        debug_log(f"🔗 [PeerManager] Client connection established", {
            "client_id": client_id,
            "answer_type": answer.type,
            "sdp_length": len(answer.sdp),
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        # Notify connection callbacks
        self._notify_callbacks('new_peer', client_id, pc)
        
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
    
    def _setup_peer_connection_handlers(self, pc: RTCPeerConnection, client_id: int):
        """Set up event handlers for a peer connection."""
        
        @pc.on("iceconnectionstatechange")
        async def on_ice_connection_state_change():
            debug_log(f"🔗 [PeerManager] ICE connection state changed", {
                "client_id": client_id,
                "ice_state": pc.iceConnectionState,
                "timestamp": datetime.datetime.now().isoformat()
            })
        
        @pc.on("datachannel")
        def on_datachannel(channel: RTCDataChannel):
            self._handle_data_channel(client_id, channel)
        
        @pc.on("icecandidate")
        async def on_ice_candidate(candidate):
            debug_log(f"🧊 [PeerManager] ICE candidate generated", {
                "client_id": client_id,
                "candidate_type": candidate.type if candidate else 'unknown',
                "timestamp": datetime.datetime.now().isoformat()
            })
            
            # Broadcast ICE candidate to client
            await self.data_channel_manager.broadcast_message({
                'action': 'ice_candidate',
                'candidate': candidate
            }, exclude_client_id=client_id)
        
        @pc.on("icegatheringstatechange")
        async def on_ice_gathering_state_change():
            debug_log(f"🧊 [PeerManager] ICE gathering state changed", {
                "client_id": client_id,
                "ice_state": pc.iceGatheringState,
                "timestamp": datetime.datetime.now().isoformat()
            })
        
        @pc.on("signalingstatechange")
        async def on_signaling_state_change():
            debug_log(f"📡 [PeerManager] Signaling state changed", {
                "client_id": client_id,
                "signaling_state": pc.signalingState,
                "timestamp": datetime.datetime.now().isoformat()
            })
        
        @pc.on("connectionstatechange")
        async def on_connection_state_change():
            debug_log(f"🔗 [PeerManager] Connection state changed", {
                "client_id": client_id,
                "connection_state": pc.connectionState,
                "timestamp": datetime.datetime.now().isoformat()
            })
            
            # Handle connection state changes
            if pc.connectionState == "failed":
                self._handle_peer_failure(client_id, pc)
            elif pc.connectionState == "closed":
                self._handle_peer_disconnection(client_id, pc)
        
        @pc.on("negotiationneeded")
        async def on_negotiation_needed():
            debug_log(f"🤝 [PeerManager] Negotiation needed", {
                "client_id": client_id,
                "timestamp": datetime.datetime.now().isoformat()
            })
    
    def _handle_data_channel(self, client_id: int, channel: RTCDataChannel):
        """Handle a new data channel from a peer connection."""
        debug_log(f"🔗 [PeerManager] Data channel established", {
            "client_id": client_id,
            "channel_label": channel.label,
            "total_channels": self.data_channel_manager.get_channel_count(),
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        # Create message handler for this client
        message_handler = WebRTCMessageHandler()
        message_handler.set_client_id(client_id)
        self.message_handlers[client_id] = message_handler
        
        # Add data channel to manager
        self.data_channel_manager.add_channel(
            client_id=client_id,
            channel=channel,
            message_handler=message_handler.handle_message,
            close_handler=lambda: self._handle_client_disconnection(client_id)
        )
        
        # Notify data channel ready callbacks
        self._notify_callbacks('data_channel_ready', client_id, channel)
    
    def _handle_peer_failure(self, client_id: int, pc: RTCPeerConnection):
        """Handle peer connection failure."""
        self.log_error(f"Peer connection failed", {
            "client_id": client_id,
            "connection_state": pc.connectionState
        })
        
        # Clean up failed connection
        self._cleanup_peer_connection(client_id, pc)
    
    def _handle_peer_disconnection(self, client_id: int, pc: RTCPeerConnection):
        """Handle peer disconnection."""
        debug_log(f"🔌 [PeerManager] Peer disconnected", {
            "client_id": client_id,
            "connection_state": pc.connectionState,
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        # Clean up disconnected connection
        self._cleanup_peer_connection(client_id, pc)
    
    def _handle_client_disconnection(self, client_id: int):
        """Handle client disconnection from data channel."""
        debug_log(f"🔌 [PeerManager] Client disconnected", {
            "client_id": client_id,
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        # Notify disconnection callbacks
        self._notify_callbacks('peer_disconnected', client_id)
        
        # Clean up client resources
        if client_id in self.message_handlers:
            del self.message_handlers[client_id]
    
    def _cleanup_peer_connection(self, client_id: int, pc: RTCPeerConnection):
        """Clean up a peer connection."""
        if pc in self.peer_connections:
            self.peer_connections.remove(pc)
        
        # Clean up data channel
        self.data_channel_manager.remove_channel(client_id)
        
        # Clean up message handler
        if client_id in self.message_handlers:
            del self.message_handlers[client_id]
    
    def _notify_callbacks(self, event: str, client_id: int, data: Any = None):
        """Notify all callbacks for an event."""
        if event in self.connection_callbacks:
            for callback in self.connection_callbacks[event]:
                try:
                    callback(client_id, data)
                except Exception as e:
                    self.log_error(f"Error in connection callback", {
                        "event": event,
                        "client_id": client_id,
                        "error": str(e)
                    })
    
    def get_peer_connection_count(self) -> int:
        """Get total number of peer connections."""
        return len(self.peer_connections)
    
    def get_connected_clients(self) -> list:
        """Get list of connected client IDs."""
        return self.data_channel_manager.get_connected_clients()
    
    def get_message_handler(self, client_id: int) -> Optional[WebRTCMessageHandler]:
        """Get message handler for a specific client."""
        return self.message_handlers.get(client_id)
    
    def broadcast_message(self, message: Dict[str, Any], exclude_client_id: Optional[int] = None) -> int:
        """Broadcast a message to all connected clients."""
        return self.data_channel_manager.broadcast_message(message, exclude_client_id)
    
    def send_message(self, client_id: int, message: Dict[str, Any]) -> bool:
        """Send a message to a specific client."""
        return self.data_channel_manager.send_message(client_id, message)
