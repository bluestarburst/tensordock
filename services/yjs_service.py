"""
Yjs Document Service for TensorDock.
Handles Yjs document synchronization and collaborative editing.
"""
import asyncio
import json
import uuid
import datetime
import requests
from typing import Dict, Any, Optional, Set, List
from pycrdt.websocket import WebsocketServer

# Use absolute imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin
from core.config import ServerConfig


class YjsDocumentService(LoggerMixin):
    """Service for managing Yjs document synchronization."""
    
    def __init__(self, config: ServerConfig):
        super().__init__()
        self.config = config
        
        # Document management
        self.documents: Dict[str, Dict[str, Any]] = {}  # doc_id -> document info
        self.active_connections: Dict[str, Set[str]] = {}  # doc_id -> set of connection_ids
        self.websocket_server: Optional[WebsocketServer] = None
        
        # Message tracking
        self.document_updates: Dict[str, List[bytes]] = {}  # doc_id -> list of updates
        
        # WebRTC broadcast callback (to be set by server)
        self.broadcast_callback: Optional[callable] = None
        
        # Document save scheduling
        self.save_tasks: Dict[str, asyncio.Task] = {}  # doc_id -> save task
        self.save_delay = 2.0  # seconds to wait before saving
        
    async def start_websocket_server(self, host: str = "localhost", port: int = 8765):
        """Start the Yjs WebSocket server."""
        try:
            self.websocket_server = WebsocketServer()
            
            self.log_info(f"Starting Yjs WebSocket server on {host}:{port}")
            await self.websocket_server.start()
            
        except Exception as e:
            self.log_error(f"Failed to start Yjs WebSocket server: {e}")
            raise
    
    async def handle_document_update(self, document_id: str, update: bytes):
        """Handle incoming Yjs document update."""
        try:
            self.log_info(f"Received document update for {document_id}, size: {len(update)}")
            
            # Store the update for this document
            if document_id not in self.document_updates:
                self.document_updates[document_id] = []
            self.document_updates[document_id].append(update)
            
            # Broadcast to all connected clients for this document
            await self._broadcast_document_update(document_id, update)
            
            # Schedule a save operation (debounced to avoid too frequent saves)
            await self._schedule_document_save(document_id)
            
        except Exception as e:
            self.log_error(f"Error handling document update: {e}")

    async def request_document_state(self, document_id: str):
        """Request the current document state from the frontend."""
        try:
            if self.broadcast_callback:
                message = {
                    'action': 'yjs_request_state',
                    'documentId': document_id,
                    'timestamp': datetime.datetime.now().isoformat()
                }
                await self.broadcast_callback(message)
                self.log_info(f"Requested document state for {document_id}")
            else:
                self.log_warning(f"No broadcast callback available to request state for {document_id}")
        except Exception as e:
            self.log_error(f"Error requesting document state for {document_id}: {e}")

    async def handle_document_state_response(self, document_id: str, notebook_content: Dict[str, Any]):
        """Handle document state response from frontend."""
        try:
            self.log_info(f"Received document state for {document_id}")
            
            # Save the document state to file
            success = await self.save_document_to_file(document_id, notebook_content)
            if success:
                self.log_info(f"Successfully saved document state for {document_id}")
            else:
                self.log_error(f"Failed to save document state for {document_id}")
                
        except Exception as e:
            self.log_error(f"Error handling document state response for {document_id}: {e}")

    async def handle_awareness_update(self, document_id: str, update: dict):
        """Handle incoming Yjs awareness update."""
        try:
            self.log_info(f"Received awareness update for {document_id}: {update}")
            
            # Broadcast to all connected clients for this document
            await self._broadcast_awareness_update(document_id, update)
            
        except Exception as e:
            self.log_error(f"Error handling awareness update: {e}")

    async def handle_sync_request(self, document_id: str):
        """Handle sync request from client."""
        try:
            self.log_info(f"Received sync request for {document_id}")
            
            # Send all stored updates for this document
            if document_id in self.document_updates:
                for update in self.document_updates[document_id]:
                    await self._broadcast_document_update(document_id, update)
            
        except Exception as e:
            self.log_error(f"Error handling sync request: {e}")

    async def _broadcast_document_update(self, document_id: str, update: bytes):
        """Broadcast document update to all connected clients."""
        try:
            if self.broadcast_callback:
                # Create message for WebRTC broadcast
                message = {
                    'action': 'yjs_document_update',
                    'documentId': document_id,
                    'update': list(update),  # Convert bytes to list for JSON serialization
                    'timestamp': datetime.datetime.now().isoformat()
                }
                
                # Broadcast to all clients
                await self.broadcast_callback(message)
                self.log_info(f"Broadcasted document update for {document_id} to all clients")
            else:
                self.log_warning(f"No broadcast callback available for document {document_id}")
                
        except Exception as e:
            self.log_error(f"Error broadcasting document update: {e}")

    async def _broadcast_awareness_update(self, document_id: str, update: bytes):
        """Broadcast awareness update to all connected clients."""
        try:
            if self.broadcast_callback:
                # Create message for WebRTC broadcast
                message = {
                    'action': 'yjs_awareness_update',
                    'documentId': document_id,
                    'awareness': list(update),  # Convert bytes to list for JSON serialization
                    'timestamp': datetime.datetime.now().isoformat()
                }
                
                # Broadcast to all clients
                await self.broadcast_callback(message)
                self.log_info(f"Broadcasted awareness update for {document_id} to all clients")
            else:
                self.log_warning(f"No broadcast callback available for document {document_id}")
                
        except Exception as e:
            self.log_error(f"Error broadcasting awareness update: {e}")

    async def _broadcast_sync_response(self, document_id: str, state: bytes):
        """Broadcast sync response to requesting client."""
        try:
            if self.broadcast_callback:
                # Create message for WebRTC broadcast
                message = {
                    'action': 'yjs_sync_response',
                    'documentId': document_id,
                    'state': list(state),  # Convert bytes to list for JSON serialization
                    'timestamp': datetime.datetime.now().isoformat()
                }
                
                # Broadcast to all clients
                await self.broadcast_callback(message)
                self.log_info(f"Broadcasted sync response for {document_id} to all clients")
            else:
                self.log_warning(f"No broadcast callback available for document {document_id}")
                
        except Exception as e:
            self.log_error(f"Error broadcasting sync response: {e}")

    def set_broadcast_callback(self, callback: callable):
        """Set the broadcast callback for WebRTC messaging."""
        self.broadcast_callback = callback
        self.log_info("Broadcast callback set for YJS service")

    async def save_document_to_file(self, document_id: str, notebook_content: Dict[str, Any]):
        """Save the document state to the actual notebook file."""
        try:
            # Map document_id to notebook file path
            if document_id.startswith('notebook-'):
                # Extract the notebook path from document_id
                notebook_path = document_id.replace('notebook-', '').replace('-', '/')
                if not notebook_path.endswith('.ipynb'):
                    notebook_path = 'tmp.ipynb'  # Default to tmp.ipynb
            else:
                notebook_path = 'tmp.ipynb'  # Default to tmp.ipynb
            
            self.log_info(f"Saving document {document_id} to notebook file: {notebook_path}")
            
            # Save to Jupyter server via API
            save_url = f"{self.config.jupyter_url}/api/contents/{notebook_path}"
            save_data = {
                'type': 'notebook',
                'path': notebook_path,
                'content': notebook_content
            }
            
            response = requests.put(save_url, headers=self.config.get_jupyter_headers(), json=save_data)
            if response.status_code in [200, 201]:
                self.log_info(f"Successfully saved document {document_id} to {notebook_path}")
                return True
            else:
                self.log_error(f"Failed to save document {document_id} to {notebook_path}: {response.status_code}")
                return False
                
        except Exception as e:
            self.log_error(f"Error saving document {document_id} to file: {e}")
            return False

    async def _schedule_document_save(self, document_id: str):
        """Schedule a debounced save operation for the document."""
        try:
            # Cancel existing save task if it exists
            if document_id in self.save_tasks:
                self.save_tasks[document_id].cancel()
            
            # Create new save task
            self.save_tasks[document_id] = asyncio.create_task(
                self._debounced_save(document_id)
            )
            
        except Exception as e:
            self.log_error(f"Error scheduling document save for {document_id}: {e}")

    async def _debounced_save(self, document_id: str):
        """Debounced save operation."""
        try:
            # Wait for the save delay
            await asyncio.sleep(self.save_delay)
            
            # Request the current document state from the frontend
            await self.request_document_state(document_id)
            
            # Clean up the save task
            if document_id in self.save_tasks:
                del self.save_tasks[document_id]
                
        except asyncio.CancelledError:
            # Task was cancelled, which is expected for debouncing
            pass
        except Exception as e:
            self.log_error(f"Error in debounced save for {document_id}: {e}")

    async def stop(self):
        """Stop the Yjs service."""
        if self.websocket_server:
            await self.websocket_server.stop()
            self.log_info("Yjs WebSocket server stopped")
