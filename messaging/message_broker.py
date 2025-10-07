"""
Message broker for TensorDock server.
Handles message routing, queuing, and distribution to appropriate handlers.
"""

import asyncio
import json
import datetime
from typing import Dict, Any, Callable, Optional, List
from collections import defaultdict

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log


class MessageBroker(LoggerMixin):
    """Routes and distributes messages to appropriate handlers."""
    
    def __init__(self):
        # Message queues
        self.action_queue = asyncio.Queue()
        self.input_queue = asyncio.Queue()
        self.response_queue = asyncio.Queue()
        
        # Message handlers by action type
        self.action_handlers: Dict[str, List[Callable]] = defaultdict(list)
        
        # Message routing rules
        self.routing_rules: Dict[str, str] = {}
        
        # Worker manager reference (to be set by server)
        self.worker_manager = None
        
        # Message statistics
        self.message_stats = {
            'total_messages': 0,
            'messages_by_action': defaultdict(int),
            'messages_by_handler': defaultdict(int),
            'errors': 0,
            'start_time': datetime.datetime.now()
        }
        
        # Broker state
        self.running = False
        self.processing_task = None
        
        debug_log(f"📨 [MessageBroker] Message broker initialized")
    
    def set_worker_manager(self, worker_manager):
        """Set the worker manager reference."""
        self.worker_manager = worker_manager
        
        debug_log(f"🔗 [MessageBroker] Worker manager reference set")
    
    def register_handler(self, action: str, handler: Callable, priority: int = 0):
        """Register a handler for a specific action type."""
        self.action_handlers[action].append((priority, handler))
        
        # Sort handlers by priority (higher priority first)
        self.action_handlers[action].sort(key=lambda x: x[0], reverse=True)
        
        debug_log(f"➕ [MessageBroker] Handler registered", {
            "action": action,
            "handler": handler.__name__,
            "priority": priority,
            "total_handlers": len(self.action_handlers[action])
        })
    
    def unregister_handler(self, action: str, handler: Callable):
        """Unregister a handler for a specific action type."""
        if action in self.action_handlers:
            # Remove handler by finding and removing the tuple
            handlers = self.action_handlers[action]
            handlers[:] = [(p, h) for p, h in handlers if h != handler]
            
            debug_log(f"➖ [MessageBroker] Handler unregistered", {
                "action": action,
                "handler": handler.__name__,
                "remaining_handlers": len(handlers)
            })
    
    def add_routing_rule(self, action: str, target_queue: str):
        """Add a routing rule for message distribution."""
        self.routing_rules[action] = target_queue
        
        debug_log(f"🛣️ [MessageBroker] Routing rule added", {
            "action": action,
            "target_queue": target_queue
        })
    
    async def route_message(self, message: Dict[str, Any]) -> bool:
        """Route a message to the appropriate queue and handlers."""
        try:
            action = message.get('action', 'unknown')
            
            debug_log(f"📨 [MessageBroker] Routing message", {
                "action": action,
                "message_keys": list(message.keys()),
                "timestamp": datetime.datetime.now().isoformat()
            })
            
            # Update statistics
            self.message_stats['total_messages'] += 1
            self.message_stats['messages_by_action'][action] += 1
            
            # Route to appropriate queue based on action type
            if action in self.routing_rules:
                target_queue = self.routing_rules[action]
                if target_queue == 'action':
                    await self.action_queue.put(message)
                    # Also submit to worker manager for processing
                    if self.worker_manager:
                        await self.worker_manager.submit_task(action, message)
            
            else:
                # Unknown action, put in action queue for processing
                await self.action_queue.put(message)
                # Also submit to worker manager for processing
                if self.worker_manager:
                    await self.worker_manager.submit_task(action, message)
            
            # Notify handlers
            await self._notify_handlers(action, message)
            
            return True
            
        except Exception as e:
            self.message_stats['errors'] += 1
            debug_log(f"❌ [MessageBroker] Message routing error", {
                "error": str(e),
                "error_type": type(e).__name__,
                "message": message
            })
            return False
    
    async def _notify_handlers(self, action: str, message: Dict[str, Any]):
        """Notify all registered handlers for an action."""
        if action in self.action_handlers:
            handlers = self.action_handlers[action]
            
            debug_log(f"🔔 [MessageBroker] Notifying handlers", {
                "action": action,
                "handler_count": len(handlers)
            })
            
            # Create tasks for all handlers
            tasks = []
            for priority, handler in handlers:
                try:
                    task = asyncio.create_task(handler(message))
                    tasks.append(task)
                    
                    debug_log(f"🔔 [MessageBroker] Handler task created", {
                        "action": action,
                        "handler": handler.__name__,
                        "priority": priority
                    })
                    
                except Exception as e:
                    debug_log(f"❌ [MessageBroker] Handler task creation error", {
                        "action": action,
                        "handler": handler.__name__,
                        "error": str(e),
                        "error_type": type(e).__name__
                    })
            
            # Wait for all handlers to complete
            if tasks:
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    
                    debug_log(f"✅ [MessageBroker] All handlers completed", {
                        "action": action,
                        "handler_count": len(tasks)
                    })
                    
                except Exception as e:
                    debug_log(f"❌ [MessageBroker] Handler execution error", {
                        "action": action,
                        "error": str(e),
                        "error_type": type(e).__name__
                    })
    
    async def broadcast_message(self, message: Dict[str, Any], exclude_client_id: Optional[str] = None):
        """Broadcast a message to all connected clients."""
        try:
            debug_log(f"📤 [MessageBroker] Broadcasting message", {
                "action": message.get('action'),
                "exclude_client_id": exclude_client_id
            })
            
            # This would integrate with the WebRTC broadcast system
            # For now, we'll just log the broadcast
            debug_log(f"📤 [MessageBroker] Broadcast message logged", {
                "message": message,
                "exclude_client_id": exclude_client_id
            })
            
            return True
            
        except Exception as e:
            debug_log(f"❌ [MessageBroker] Broadcast error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get status of all message queues."""
        return {
            'action_queue_size': self.action_queue.qsize(),
            'input_queue_size': self.input_queue.qsize(),
            'response_queue_size': self.response_queue.qsize(),
            'total_handlers': sum(len(handlers) for handlers in self.action_handlers.values()),
            'routing_rules': len(self.routing_rules)
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get message processing statistics."""
        uptime = datetime.datetime.now() - self.message_stats['start_time']
        
        return {
            'total_messages': self.message_stats['total_messages'],
            'messages_by_action': dict(self.message_stats['messages_by_action']),
            'errors': self.message_stats['errors'],
            'uptime_seconds': uptime.total_seconds(),
            'start_time': self.message_stats['start_time'].isoformat()
        }
    
    async def start(self):
        """Start the message broker."""
        if self.running:
            return
        
        self.running = True
        self.processing_task = asyncio.create_task(self._message_processor())
        
        debug_log(f"🚀 [MessageBroker] Message broker started")
    
    async def stop(self):
        """Stop the message broker."""
        if not self.running:
            return
        
        self.running = False
        
        if self.processing_task:
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass
        
        debug_log(f"🛑 [MessageBroker] Message broker stopped")
    
    async def _message_processor(self):
        """Background message processor."""
        debug_log(f"⚙️ [MessageBroker] Message processor started")
        
        while self.running:
            try:
                # Process messages from all queues
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                debug_log(f"❌ [MessageBroker] Message processor error", {
                    "error": str(e),
                    "error_type": type(e).__name__
                })
                await asyncio.sleep(1)  # Wait before retrying
        
        debug_log(f"⚙️ [MessageBroker] Message processor stopped")
    
    async def cleanup(self):
        """Clean up message broker resources."""
        debug_log(f"🧹 [MessageBroker] Cleaning up message broker")
        
        await self.stop()
        
        # Clear queues
        while not self.action_queue.empty():
            try:
                self.action_queue.get_nowait()
                self.action_queue.task_done()
            except:
                pass
        
        while not self.input_queue.empty():
            try:
                self.input_queue.get_nowait()
                self.input_queue.task_done()
            except:
                pass
        
        while not self.response_queue.empty():
            try:
                self.response_queue.get_nowait()
                self.response_queue.task_done()
            except:
                pass
        
        # Clear handlers
        self.action_handlers.clear()
        self.routing_rules.clear()
        
        debug_log(f"🧹 [MessageBroker] Message broker cleanup completed")
