"""
Document Synchronization Service for TensorDock.
Handles document state synchronization between frontend and backend.
"""
import asyncio
import json
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime

# Use absolute imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin
from core.config import ServerConfig


class DocumentSyncService(LoggerMixin):
    """Service for synchronizing document states."""
    
    def __init__(self, config: ServerConfig):
        super().__init__()
        self.config = config
        
        # Document state management
        self.document_states: Dict[str, Dict[str, Any]] = {}  # doc_id -> document state
        self.document_versions: Dict[str, int] = {}  # doc_id -> version number
        self.document_locks: Dict[str, str] = {}  # doc_id -> lock_owner
        
        # Change tracking
        self.document_changes: Dict[str, List[Dict[str, Any]]] = {}  # doc_id -> list of changes
        self.change_subscribers: Dict[str, List[str]] = {}  # doc_id -> list of subscriber_ids
    
    async def create_document(self, doc_id: str, initial_state: Dict[str, Any] = None) -> bool:
        """Create a new document."""
        try:
            if doc_id in self.document_states:
                self.log_warning(f"Document already exists: {doc_id}")
                return False
            
            self.document_states[doc_id] = initial_state or {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {},
                "cells": []
            }
            self.document_versions[doc_id] = 0
            self.document_changes[doc_id] = []
            self.change_subscribers[doc_id] = []
            
            self.log_info(f"Created document: {doc_id}")
            return True
            
        except Exception as e:
            self.log_error(f"Failed to create document {doc_id}: {e}")
            return False
    
    async def get_document_state(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get current document state."""
        return self.document_states.get(doc_id)
    
    async def update_document(self, doc_id: str, changes: List[Dict[str, Any]], client_id: str) -> bool:
        """Update document with changes."""
        try:
            if doc_id not in self.document_states:
                self.log_warning(f"Document not found: {doc_id}")
                return False
            
            # Apply changes
            for change in changes:
                await self._apply_change(doc_id, change, client_id)
            
            # Increment version
            self.document_versions[doc_id] += 1
            
            # Store change history
            self.document_changes[doc_id].append({
                "timestamp": datetime.now().isoformat(),
                "client_id": client_id,
                "version": self.document_versions[doc_id],
                "changes": changes
            })
            
            self.log_info(f"Updated document {doc_id} to version {self.document_versions[doc_id]}")
            return True
            
        except Exception as e:
            self.log_error(f"Failed to update document {doc_id}: {e}")
            return False
    
    async def _apply_change(self, doc_id: str, change: Dict[str, Any], client_id: str):
        """Apply a single change to the document."""
        change_type = change.get("type")
        
        if change_type == "cell_insert":
            # Insert new cell
            cell_data = change.get("cell")
            position = change.get("position", 0)
            self.document_states[doc_id]["cells"].insert(position, cell_data)
            
        elif change_type == "cell_update":
            # Update existing cell
            cell_id = change.get("cell_id")
            cell_data = change.get("cell")
            for i, cell in enumerate(self.document_states[doc_id]["cells"]):
                if cell.get("id") == cell_id:
                    self.document_states[doc_id]["cells"][i] = cell_data
                    break
                    
        elif change_type == "cell_delete":
            # Delete cell
            cell_id = change.get("cell_id")
            self.document_states[doc_id]["cells"] = [
                cell for cell in self.document_states[doc_id]["cells"]
                if cell.get("id") != cell_id
            ]
            
        elif change_type == "metadata_update":
            # Update metadata
            metadata = change.get("metadata", {})
            self.document_states[doc_id]["metadata"].update(metadata)
    
    async def subscribe_to_changes(self, doc_id: str, subscriber_id: str) -> bool:
        """Subscribe to document changes."""
        if doc_id not in self.change_subscribers:
            return False
        
        if subscriber_id not in self.change_subscribers[doc_id]:
            self.change_subscribers[doc_id].append(subscriber_id)
            self.log_info(f"Subscribed {subscriber_id} to document {doc_id}")
        
        return True
    
    async def unsubscribe_from_changes(self, doc_id: str, subscriber_id: str) -> bool:
        """Unsubscribe from document changes."""
        if doc_id in self.change_subscribers:
            if subscriber_id in self.change_subscribers[doc_id]:
                self.change_subscribers[doc_id].remove(subscriber_id)
                self.log_info(f"Unsubscribed {subscriber_id} from document {doc_id}")
                return True
        
        return False
    
    async def get_document_version(self, doc_id: str) -> int:
        """Get current document version."""
        return self.document_versions.get(doc_id, 0)
    
    async def get_document_changes(self, doc_id: str, from_version: int = 0) -> List[Dict[str, Any]]:
        """Get document changes since a specific version."""
        if doc_id not in self.document_changes:
            return []
        
        return [
            change for change in self.document_changes[doc_id]
            if change["version"] > from_version
        ]
