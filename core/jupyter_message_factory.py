"""
Jupyter message factory for creating standardized Jupyter protocol messages.
Centralizes message creation to eliminate duplication across the codebase.
"""

import datetime
from typing import Dict, Any, Optional


class JupyterMessageFactory:
    """Factory for creating standardized Jupyter protocol messages."""
    
    @staticmethod
    def create_execute_request(code: str, cell_id: str = 'unknown', silent: bool = False, 
                              store_history: bool = True, allow_stdin: bool = False) -> Dict[str, Any]:
        """Create an execute_request message."""
        msg_id = str(hash(f"{cell_id}_{datetime.datetime.now().isoformat()}"))
        
        return {
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
                'silent': silent,
                'store_history': store_history,
                'user_expressions': {},
                'allow_stdin': allow_stdin
            }
        }
    
    @staticmethod
    def create_comm_message(comm_id: str, data: Dict[str, Any], msg_type: str = 'comm_msg') -> Dict[str, Any]:
        """Create a comm message."""
        msg_id = str(hash(f"{comm_id}_{datetime.datetime.now().isoformat()}"))
        
        return {
            'header': {
                'msg_id': msg_id,
                'msg_type': msg_type,
                'username': 'user',
                'session': 'session',
                'date': datetime.datetime.now().isoformat(),
                'version': '5.0'
            },
            'parent_header': {},
            'metadata': {},
            'content': {
                'comm_id': comm_id,
                'data': data
            }
        }
    
    @staticmethod
    def create_kernel_request(msg_type: str, content: Dict[str, Any], parent_header: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a generic kernel request message."""
        msg_id = str(hash(f"{msg_type}_{datetime.datetime.now().isoformat()}"))
        
        return {
            'header': {
                'msg_id': msg_id,
                'msg_type': msg_type,
                'username': 'user',
                'session': 'session',
                'date': datetime.datetime.now().isoformat(),
                'version': '5.0'
            },
            'parent_header': parent_header or {},
            'metadata': {},
            'content': content
        }
    
    @staticmethod
    def extract_message_info(message: Dict[str, Any]) -> Dict[str, Any]:
        """Extract common message information."""
        header = message.get('header', {})
        content = message.get('content', {})
        
        return {
            'msg_id': header.get('msg_id'),
            'msg_type': header.get('msg_type'),
            'username': header.get('username'),
            'session': header.get('session'),
            'comm_id': content.get('comm_id'),
            'parent_msg_id': message.get('parent_header', {}).get('msg_id')
        }
