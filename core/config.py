"""
Configuration management for TensorDock server.
"""
import os
from dataclasses import dataclass
from typing import List, Optional

# Make aiortc import optional for testing
try:
    from aiortc import RTCConfiguration, RTCIceServer
    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False
    # Create mock classes for testing
    class RTCConfiguration:
        def __init__(self, ice_servers):
            self.ice_servers = ice_servers
    
    class RTCIceServer:
        def __init__(self, urls, username=None, credential=None):
            self.urls = urls
            self.username = username
            self.credential = credential


@dataclass
class ServerConfig:
    """Server configuration settings."""
    
    # Environment detection
    is_local: bool = False
    
    # TURN server configuration
    turn_server_address: str = "0.0.0.0:6000?transport=udp"
    turn_client_address: str = "0.0.0.0:6000?transport=udp"
    turn_username: str = "user"
    turn_password: str = "password"
    
    # Jupyter configuration
    jupyter_url: str = "http://localhost:8888"
    jupyter_token: str = "test"
    
    # Server ports
    vast_udp_port: int = 6000
    vast_tcp_port: int = 8765
    
    # Yjs configuration
    yjs_enabled: bool = True
    yjs_port: int = 8766
    yjs_host: str = "localhost"
    yjs_max_connections: int = 100
    yjs_document_timeout: int = 3600  # 1 hour
    
    # WebRTC configuration
    rtc_config: Optional[RTCConfiguration] = None
    
    def __post_init__(self):
        """Initialize configuration from environment variables."""
        self.is_local = os.environ.get('IS_LOCAL', 'false') == 'true'
        
        # TURN server settings
        self.turn_server_address = os.environ.get(
            'TURN_ADDRESS', 
            f"0.0.0.0:{os.environ.get('VAST_UDP_PORT_70001', self.vast_udp_port)}?transport=udp"
        )
        self.turn_client_address = os.environ.get(
            'TURN_ADDRESS', 
            f"{os.environ.get('PUBLIC_IPADDR', '0.0.0.0')}:{os.environ.get('VAST_UDP_PORT_70001', self.vast_udp_port)}?transport=udp"
        )
        self.turn_username = os.environ.get('TURN_USERNAME', 'user')
        self.turn_password = os.environ.get('TURN_PASSWORD', 'password')
        
        # Jupyter settings
        self.jupyter_url = os.environ.get('JUPYTER_URL', 'http://localhost:8888')
        self.jupyter_token = os.environ.get('JUPYTER_TOKEN', 'test')
        
        # Server ports
        self.vast_udp_port = int(os.environ.get('VAST_UDP_PORT_70001', 6000))
        self.vast_tcp_port = int(os.environ.get('VAST_TCP_PORT_70000', 8765))
        
        # Build WebRTC configuration
        self._build_rtc_config()
    
    def _build_rtc_config(self):
        """Build WebRTC configuration based on environment."""
        if not AIORTC_AVAILABLE:
            print("⚠️  Warning: aiortc not available, using mock configuration")
            self.rtc_config = None
            return
            
        ice_servers = [
            RTCIceServer(urls="stun:stun.l.google.com:19302")
        ]
        
        if not self.is_local:
            ice_servers.append(
                RTCIceServer(
                    urls=f"turn:{self.turn_server_address}",
                    username=self.turn_username,
                    credential=self.turn_password
                )
            )
        
        self.rtc_config = RTCConfiguration(ice_servers)
    
    def get_jupyter_headers(self) -> dict:
        """Get headers for Jupyter API requests."""
        return {'Authorization': f'Token {self.jupyter_token}'}
    
    def get_jupyter_token(self) -> str:
        """Get Jupyter authentication token."""
        return self.jupyter_token
    
    def get_ws_url(self, kernel_id: str, session_id: str) -> str:
        """Get WebSocket URL for Jupyter kernel."""
        base = self.jupyter_url.split('://')[-1]
        return f"ws://{base}/api/kernels/{kernel_id}/channels?session_id={session_id}"
    
    def __str__(self) -> str:
        """String representation of configuration."""
        return f"ServerConfig(is_local={self.is_local}, jupyter_url={self.jupyter_url}, tcp_port={self.vast_tcp_port})"
