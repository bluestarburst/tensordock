"""
Session management for Jupyter integration.
Handles session creation, validation, and lifecycle management.
"""

import asyncio
import json
import datetime
from typing import Optional, Dict, Any, List
import requests

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log
from core.config import ServerConfig


class SessionManager(LoggerMixin):
    """Manages Jupyter session lifecycle and validation."""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.session_id: Optional[str] = None
        self.session_name: str = "python3"
        self.session_path: str = "/tmp/test.ipynb"
        self.session_type: str = "notebook"
        self.kernel_name: str = "python3"
        
        # Session state
        self.active = False
        self.created_at: Optional[datetime.datetime] = None
        self.last_activity: Optional[datetime.datetime] = None
        
        # Session validation
        self.validation_interval = 30  # seconds
        self.validation_task = None
    
    def get_session_id(self) -> Optional[str]:
        """Get the current session ID."""
        return self.session_id
    
    async def create_session(self) -> str:
        """Create a new Jupyter session."""
        try:
            debug_log(f"📝 [Session] Creating new session")
            
            url = f"{self.config.jupyter_url}/api/sessions"
            headers = self.config.get_jupyter_headers()
            
            session_data = {
                'name': self.session_name,
                'path': self.session_path,
                'type': self.session_type,
                'kernel': {
                    'name': self.kernel_name
                }
            }
            
            response = requests.post(url, headers=headers, json=session_data)
            if response.status_code != 201:
                raise Exception(f"Session creation failed: {response.status_code}")
            
            session_info = json.loads(response.text)
            self.session_id = session_info['id']
            self.session_name = session_info.get('name', self.session_name)
            self.active = True
            self.created_at = datetime.datetime.now()
            self.last_activity = datetime.datetime.now()
            
            debug_log(f"📝 [Session] Session created successfully", {
                "session_id": self.session_id,
                "session_name": self.session_name,
                "created_at": self.created_at.isoformat()
            })
            
            # Start validation task
            self._start_validation_task()
            
            return self.session_id
            
        except Exception as e:
            debug_log(f"❌ [Session] Failed to create session", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            raise
    
    async def validate_session(self, session_id: str) -> bool:
        """Validate if a session is still active."""
        try:
            url = f"{self.config.jupyter_url}/api/sessions/{session_id}"
            headers = self.config.get_jupyter_headers()
            
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                debug_log(f"❌ [Session] Session validation failed", {
                    "session_id": session_id,
                    "status_code": response.status_code
                })
                return False
            
            session_info = json.loads(response.text)
            is_valid = session_info.get('id') == session_id
            
            if is_valid:
                self.last_activity = datetime.datetime.now()
                debug_log(f"✅ [Session] Session validated", {
                    "session_id": session_id,
                    "session_name": session_info.get('name'),
                    "last_activity": self.last_activity.isoformat()
                })
            else:
                debug_log(f"❌ [Session] Session ID mismatch", {
                    "expected": session_id,
                    "actual": session_info.get('id')
                })
            
            return is_valid
            
        except Exception as e:
            debug_log(f"❌ [Session] Session validation error", {
                "session_id": session_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    async def validate_kernel(self, kernel_id: str) -> bool:
        """Validate if a kernel is still active."""
        try:
            url = f"{self.config.jupyter_url}/api/kernels/{kernel_id}"
            headers = self.config.get_jupyter_headers()
            
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                debug_log(f"❌ [Session] Kernel validation failed", {
                    "kernel_id": kernel_id,
                    "status_code": response.status_code
                })
                return False
            
            kernel_info = json.loads(response.text)
            is_valid = kernel_info.get('id') == kernel_id
            
            if is_valid:
                debug_log(f"✅ [Session] Kernel validated", {
                    "kernel_id": kernel_id,
                    "kernel_name": kernel_info.get('name'),
                    "kernel_status": kernel_info.get('execution_state')
                })
            else:
                debug_log(f"❌ [Session] Kernel ID mismatch", {
                    "expected": kernel_id,
                    "actual": kernel_info.get('id')
                })
            
            return is_valid
            
        except Exception as e:
            debug_log(f"❌ [Session] Kernel validation error", {
                "kernel_id": kernel_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    async def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed session information."""
        try:
            url = f"{self.config.jupyter_url}/api/sessions/{session_id}"
            headers = self.config.get_jupyter_headers()
            
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                return None
            
            session_info = json.loads(response.text)
            
            debug_log(f"📋 [Session] Session info retrieved", {
                "session_id": session_id,
                "session_name": session_info.get('name'),
                "kernel_id": session_info.get('kernel', {}).get('id')
            })
            
            return session_info
            
        except Exception as e:
            debug_log(f"❌ [Session] Failed to get session info", {
                "session_id": session_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return None
    
    async def list_sessions(self) -> List[Dict[str, Any]]:
        """List all active sessions."""
        try:
            url = f"{self.config.jupyter_url}/api/sessions"
            headers = self.config.get_jupyter_headers()
            
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                return []
            
            sessions = json.loads(response.text)
            
            debug_log(f"📋 [Session] Listed {len(sessions)} sessions")
            
            return sessions
            
        except Exception as e:
            debug_log(f"❌ [Session] Failed to list sessions", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            return []
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        try:
            url = f"{self.config.jupyter_url}/api/sessions/{session_id}"
            headers = self.config.get_jupyter_headers()
            
            response = requests.delete(url, headers=headers)
            if response.status_code != 204:
                debug_log(f"❌ [Session] Failed to delete session", {
                    "session_id": session_id,
                    "status_code": response.status_code
                })
                return False
            
            debug_log(f"🗑️ [Session] Session deleted", {
                "session_id": session_id
            })
            
            # Update local state if this was our active session
            if self.session_id == session_id:
                self.session_id = None
                self.active = False
                self.last_activity = None
            
            return True
            
        except Exception as e:
            debug_log(f"❌ [Session] Failed to delete session", {
                "session_id": session_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    def _start_validation_task(self):
        """Start periodic session validation."""
        if self.validation_task:
            self.validation_task.cancel()
        
        self.validation_task = asyncio.create_task(self._validation_loop())
    
    async def _validation_loop(self):
        """Periodically validate the active session."""
        while self.active and self.session_id:
            try:
                await asyncio.sleep(self.validation_interval)
                
                if not await self.validate_session(self.session_id):
                    debug_log(f"⚠️ [Session] Session validation failed, marking as inactive")
                    self.active = False
                    break
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                debug_log(f"❌ [Session] Validation loop error", {
                    "error": str(e),
                    "error_type": type(e).__name__
                })
                await asyncio.sleep(5)  # Wait before retrying
    
    def get_status(self) -> Dict[str, Any]:
        """Get current session status."""
        return {
            'session_id': self.session_id,
            'session_name': self.session_name,
            'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None,
            'validation_interval': self.validation_interval
        }
    
    def is_active(self) -> bool:
        """Check if session is active."""
        return self.active and self.session_id is not None
    
    async def cleanup(self):
        """Clean up session resources."""
        if self.validation_task:
            self.validation_task.cancel()
            try:
                await self.validation_task
            except asyncio.CancelledError:
                pass
        
        if self.session_id:
            await self.delete_session(self.session_id)
        
        self.session_id = None
        self.active = False
        self.created_at = None
        self.last_activity = None
        
        debug_log(f"🧹 [Session] Session cleanup completed")
