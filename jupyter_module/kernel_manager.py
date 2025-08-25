"""
Kernel management for Jupyter integration.
Handles kernel creation, execution, and lifecycle management.
"""

import asyncio
import json
import datetime
from typing import Optional, Dict, Any, Callable
from websockets.client import connect

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log
from core.config import ServerConfig


class KernelManager(LoggerMixin):
    """Manages Jupyter kernel lifecycle and communication."""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.kernel_id: Optional[str] = None
        self.kernel_ws = None
        self.kernel_status = "disconnected"
        self.execution_count = 0
        
        # Message handling
        self.message_handlers: Dict[str, Callable] = {}
        self.response_queue = asyncio.Queue()
        
        # Connection state
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        
        # Ping task
        self.ping_task = None
        
    async def create_kernel(self) -> str:
        """Create a new Jupyter kernel."""
        try:
            debug_log(f"🚀 [Kernel] Creating new kernel")
            
            # Create session first
            session_id = await self._create_session()
            
            # Get kernel info
            kernel_id = await self._get_kernel_info(session_id)
            
            # Connect WebSocket
            await self._connect_websocket(session_id, kernel_id)
            
            self.kernel_id = kernel_id
            self.connected = True
            self.reconnect_attempts = 0
            
            debug_log(f"🚀 [Kernel] Kernel created successfully", {
                "kernel_id": kernel_id,
                "session_id": session_id,
                "status": "connected"
            })
            
            return kernel_id
            
        except Exception as e:
            debug_log(f"❌ [Kernel] Failed to create kernel", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            raise
    
    async def _create_session(self) -> str:
        """Create a new Jupyter session."""
        import requests
        
        url = f"{self.config.jupyter_url}/api/sessions"
        headers = self.config.get_jupyter_headers()
        
        session_data = {
            'name': 'python3',
            'path': '/tmp/test.ipynb',
            'type': 'notebook',
            'kernel': {
                'name': 'python3'
            }
        }
        
        response = requests.post(url, headers=headers, json=session_data)
        if response.status_code != 201:
            raise Exception(f"Session creation failed: {response.status_code}")
        
        session_info = json.loads(response.text)
        return session_info['id']
    
    async def _get_kernel_info(self, session_id: str) -> str:
        """Get kernel information for a session."""
        import requests
        
        url = f"{self.config.jupyter_url}/api/sessions/{session_id}"
        headers = self.config.get_jupyter_headers()
        
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to get session info: {response.status_code}")
        
        session_info = json.loads(response.text)
        kernel_id = session_info['kernel']['id']
        
        # Get detailed kernel info
        url = f"{self.config.jupyter_url}/api/kernels/{kernel_id}"
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to get kernel info: {response.status_code}")
        
        kernel_info = json.loads(response.text)
        debug_log(f"🔌 [Kernel] Kernel info retrieved", {
            "kernel_id": kernel_id,
            "kernel_name": kernel_info.get('name'),
            "kernel_status": kernel_info.get('execution_state')
        })
        
        return kernel_id
    
    async def _connect_websocket(self, session_id: str, kernel_id: str):
        """Connect to kernel WebSocket."""
        ws_url = self.config.get_ws_url(kernel_id, session_id)
        headers = self.config.get_jupyter_headers()
        
        debug_log(f"🔌 [Kernel] Connecting to WebSocket", {
            "ws_url": ws_url,
            "session_id": session_id,
            "kernel_id": kernel_id
        })
        
        self.kernel_ws = await connect(ws_url, extra_headers=headers)
        
        debug_log(f"🔌 [Kernel] WebSocket connected", {
            "ws_status": "open" if self.kernel_ws.open else "closed",
            "session_id": session_id,
            "kernel_id": kernel_id
        })
        
        # Start ping task
        self.ping_task = asyncio.create_task(self._ping_loop())
    
    async def _ping_loop(self):
        """Keep WebSocket connection alive with pings."""
        while self.connected and self.kernel_ws and self.kernel_ws.open:
            try:
                await self.kernel_ws.ping()
                await asyncio.sleep(10)  # Ping every 10 seconds
            except Exception as e:
                debug_log(f"❌ [Kernel] Ping failed", {
                    "error": str(e),
                    "error_type": type(e).__name__
                })
                break
    
    async def execute_code(self, code: str, cell_id: str) -> str:
        """Execute Python code in the kernel."""
        if not self.connected or not self.kernel_ws:
            await self.create_kernel()
        
        msg_id = await self._send_execute_request(code, cell_id)
        
        # Wait for execution to complete
        execution_count = await self._wait_for_execution_reply(msg_id)
        
        debug_log(f"⚡ [Kernel] Code execution completed", {
            "cell_id": cell_id,
            "execution_count": execution_count,
            "msg_id": msg_id
        })
        
        return execution_count
    
    async def _send_execute_request(self, code: str, cell_id: str) -> str:
        """Send execute request to kernel."""
        msg_id = str(hash(f"{cell_id}_{datetime.datetime.now().isoformat()}"))
        
        msg = {
            'header': {
                'msg_id': msg_id,
                'msg_type': 'execute_request',
                'username': 'user',
                'session': 'session',
                'date': datetime.datetime.now().isoformat(),
                'version': '5.0'
            },
            'parent_header': {},
            'metadata': {},
            'content': {
                'code': code,
                'silent': False,
                'store_history': True,
                'user_expressions': {},
                'allow_stdin': False
            }
        }
        
        await self.kernel_ws.send(json.dumps(msg))
        
        debug_log(f"📤 [Kernel] Execute request sent", {
            "msg_id": msg_id,
            "cell_id": cell_id,
            "code_length": len(code)
        })
        
        return msg_id
    
    async def _wait_for_execution_reply(self, msg_id: str) -> Optional[int]:
        """Wait for execution reply from kernel."""
        timeout = 30  # 30 second timeout
        start_time = datetime.datetime.now()
        
        while (datetime.datetime.now() - start_time).seconds < timeout:
            if not self.response_queue.empty():
                msg = await self.response_queue.get()
                
                if (msg.get('parent_header', {}).get('msg_id') == msg_id and 
                    msg.get('msg_type') == 'execute_reply'):
                    execution_count = msg['content'].get('execution_count')
                    self.execution_count = execution_count
                    return execution_count
            
            await asyncio.sleep(0.1)
        
        debug_log(f"⏰ [Kernel] Execution reply timeout", {
            "msg_id": msg_id,
            "timeout_seconds": timeout
        })
        return None
    
    async def send_message(self, message: Dict[str, Any]):
        """Send a message to the kernel."""
        if not self.connected or not self.kernel_ws:
            raise Exception("Kernel not connected")
        
        await self.kernel_ws.send(json.dumps(message))
        
        debug_log(f"📤 [Kernel] Message sent to kernel", {
            "msg_type": message.get('header', {}).get('msg_type', 'unknown'),
            "msg_id": message.get('header', {}).get('msg_id', 'unknown')
        })
    
    async def restart_kernel(self):
        """Restart the current kernel."""
        debug_log(f"🔄 [Kernel] Restarting kernel")
        
        if self.kernel_ws:
            await self.kernel_ws.close()
        
        if self.ping_task:
            self.ping_task.cancel()
        
        self.kernel_id = None
        self.kernel_ws = None
        self.connected = False
        
        # Create new kernel
        await self.create_kernel()
        
        debug_log(f"🔄 [Kernel] Kernel restarted successfully")
    
    async def shutdown_kernel(self):
        """Shutdown the current kernel."""
        debug_log(f"🛑 [Kernel] Shutting down kernel")
        
        if self.kernel_ws:
            await self.kernel_ws.close()
        
        if self.ping_task:
            self.ping_task.cancel()
        
        self.kernel_id = None
        self.kernel_ws = None
        self.connected = False
        
        debug_log(f"🛑 [Kernel] Kernel shutdown complete")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current kernel status."""
        return {
            'kernel_id': self.kernel_id,
            'connected': self.connected,
            'status': self.kernel_status,
            'execution_count': self.execution_count,
            'reconnect_attempts': self.reconnect_attempts
        }
    
    def is_connected(self) -> bool:
        """Check if kernel is connected."""
        return self.connected and self.kernel_ws and self.kernel_ws.open
