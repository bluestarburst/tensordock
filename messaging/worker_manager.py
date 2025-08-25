"""
Worker manager for TensorDock server.
Handles background task processing and worker lifecycle management.
"""

import asyncio
import threading
import datetime
from typing import Dict, Any, Callable, Optional, List
from concurrent.futures import ThreadPoolExecutor

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log


class WorkerManager(LoggerMixin):
    """Manages background workers and task processing."""
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        
        # Worker pools
        self.async_workers: List[asyncio.Task] = []
        self.thread_workers: List[threading.Thread] = []
        self.thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        
        # Task queues
        self.task_queue = asyncio.Queue()
        self.priority_queue = asyncio.Queue()
        
        # Worker state
        self.running = False
        self.worker_count = 0
        self.active_tasks = 0
        
        # Task statistics
        self.task_stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'tasks_by_type': {},
            'start_time': datetime.datetime.now()
        }
        
        # Task handlers
        self.task_handlers: Dict[str, Callable] = {}
        
        debug_log(f"👷 [WorkerManager] Worker manager initialized", {
            "max_workers": max_workers
        })
    
    def register_task_handler(self, task_type: str, handler: Callable):
        """Register a handler for a specific task type."""
        self.task_handlers[task_type] = handler
        
        debug_log(f"➕ [WorkerManager] Task handler registered", {
            "task_type": task_type,
            "handler": handler.__name__,
            "total_handlers": len(self.task_handlers)
        })
    
    def unregister_task_handler(self, task_type: str):
        """Unregister a task handler."""
        if task_type in self.task_handlers:
            del self.task_handlers[task_type]
            
            debug_log(f"➖ [WorkerManager] Task handler unregistered", {
                "task_type": task_type,
                "total_handlers": len(self.task_handlers)
            })
    
    async def submit_task(self, task_type: str, data: Dict[str, Any], priority: int = 0) -> str:
        """Submit a task for processing."""
        try:
            task_id = f"{task_type}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            
            task = {
                'id': task_id,
                'type': task_type,
                'data': data,
                'priority': priority,
                'submitted_at': datetime.datetime.now(),
                'status': 'pending'
            }
            
            if priority > 0:
                await self.priority_queue.put(task)
            else:
                await self.task_queue.put(task)
            
            self.task_stats['total_tasks'] += 1
            self.task_stats['tasks_by_type'][task_type] = self.task_stats['tasks_by_type'].get(task_type, 0) + 1
            
            debug_log(f"📋 [WorkerManager] Task submitted", {
                "task_id": task_id,
                "task_type": task_type,
                "priority": priority,
                "queue_size": self.task_queue.qsize() + self.priority_queue.qsize()
            })
            
            return task_id
            
        except Exception as e:
            debug_log(f"❌ [WorkerManager] Task submission error", {
                "error": str(e),
                "error_type": type(e).__name__,
                "task_type": task_type
            })
            raise
    
    async def start_workers(self):
        """Start the worker pool."""
        if self.running:
            return
        
        self.running = True
        
        # Start async workers
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._async_worker(f"async_worker_{i}"))
            self.async_workers.append(worker)
        
        # Start priority worker
        priority_worker = asyncio.create_task(self._priority_worker())
        self.async_workers.append(priority_worker)
        
        debug_log(f"🚀 [WorkerManager] Workers started", {
            "async_workers": len(self.async_workers),
            "max_workers": self.max_workers
        })
    
    async def stop_workers(self):
        """Stop all workers."""
        if not self.running:
            return
        
        self.running = False
        
        # Cancel async workers
        for worker in self.async_workers:
            worker.cancel()
        
        # Wait for workers to finish
        if self.async_workers:
            await asyncio.gather(*self.async_workers, return_exceptions=True)
        
        # Shutdown thread pool
        self.thread_pool.shutdown(wait=True)
        
        debug_log(f"🛑 [WorkerManager] Workers stopped")
    
    async def _async_worker(self, worker_name: str):
        """Async worker that processes tasks from the queue."""
        debug_log(f"👷 [WorkerManager] {worker_name} started")
        
        while self.running:
            try:
                # Get task from queue with timeout
                try:
                    task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                if task is None:
                    break
                
                await self._process_task(task, worker_name)
                self.task_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                debug_log(f"❌ [WorkerManager] {worker_name} error", {
                    "error": str(e),
                    "error_type": type(e).__name__
                })
                await asyncio.sleep(1)  # Wait before retrying
        
        debug_log(f"👷 [WorkerManager] {worker_name} stopped")
    
    async def _priority_worker(self):
        """Priority worker that processes high-priority tasks."""
        debug_log(f"👷 [WorkerManager] Priority worker started")
        
        while self.running:
            try:
                # Get priority task from queue with timeout
                try:
                    task = await asyncio.wait_for(self.priority_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                if task is None:
                    break
                
                await self._process_task(task, "priority_worker")
                self.priority_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                debug_log(f"❌ [WorkerManager] Priority worker error", {
                    "error": str(e),
                    "error_type": type(e).__name__
                })
                await asyncio.sleep(1)  # Wait before retrying
        
        debug_log(f"👷 [WorkerManager] Priority worker stopped")
    
    async def _process_task(self, task: Dict[str, Any], worker_name: str):
        """Process a single task."""
        task_id = task['id']
        task_type = task['type']
        task_data = task['data']
        
        try:
            debug_log(f"⚙️ [WorkerManager] Processing task", {
                "worker": worker_name,
                "task_id": task_id,
                "task_type": task_type
            })
            
            task['status'] = 'processing'
            task['worker'] = worker_name
            task['started_at'] = datetime.datetime.now()
            self.active_tasks += 1
            
            # Check if we have a handler for this task type
            if task_type in self.task_handlers:
                handler = self.task_handlers[task_type]
                
                # Execute handler
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(task_data)
                else:
                    # Run in thread pool for sync handlers
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(self.thread_pool, handler, task_data)
                
                task['status'] = 'completed'
                task['result'] = result
                task['completed_at'] = datetime.datetime.now()
                
                self.task_stats['completed_tasks'] += 1
                
                debug_log(f"✅ [WorkerManager] Task completed", {
                    "worker": worker_name,
                    "task_id": task_id,
                    "task_type": task_type
                })
                
            else:
                task['status'] = 'failed'
                task['error'] = f"No handler registered for task type: {task_type}"
                task['failed_at'] = datetime.datetime.now()
                
                self.task_stats['failed_tasks'] += 1
                
                debug_log(f"❌ [WorkerManager] Task failed - no handler", {
                    "worker": worker_name,
                    "task_id": task_id,
                    "task_type": task_type
                })
                
        except Exception as e:
            task['status'] = 'failed'
            task['error'] = str(e)
            task['error_type'] = type(e).__name__
            task['failed_at'] = datetime.datetime.now()
            
            self.task_stats['failed_tasks'] += 1
            
            debug_log(f"❌ [WorkerManager] Task processing error", {
                "worker": worker_name,
                "task_id": task_id,
                "task_type": task_type,
                "error": str(e),
                "error_type": type(e).__name__
            })
        
        finally:
            self.active_tasks -= 1
    
    def get_worker_status(self) -> Dict[str, Any]:
        """Get current worker status."""
        return {
            'running': self.running,
            'max_workers': self.max_workers,
            'active_workers': len(self.async_workers),
            'active_tasks': self.active_tasks,
            'task_queue_size': self.task_queue.qsize(),
            'priority_queue_size': self.priority_queue.qsize(),
            'total_handlers': len(self.task_handlers)
        }
    
    def get_task_statistics(self) -> Dict[str, Any]:
        """Get task processing statistics."""
        uptime = datetime.datetime.now() - self.task_stats['start_time']
        
        return {
            'total_tasks': self.task_stats['total_tasks'],
            'completed_tasks': self.task_stats['completed_tasks'],
            'failed_tasks': self.task_stats['failed_tasks'],
            'success_rate': (self.task_stats['completed_tasks'] / max(self.task_stats['total_tasks'], 1)) * 100,
            'tasks_by_type': dict(self.task_stats['tasks_by_type']),
            'uptime_seconds': uptime.total_seconds(),
            'start_time': self.task_stats['start_time'].isoformat()
        }
    
    async def wait_for_completion(self, timeout: Optional[float] = None):
        """Wait for all tasks to complete."""
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    self.task_queue.join(),
                    self.priority_queue.join()
                ),
                timeout=timeout
            )
            
            debug_log(f"✅ [WorkerManager] All tasks completed")
            
        except asyncio.TimeoutError:
            debug_log(f"⏰ [WorkerManager] Wait timeout reached")
        except Exception as e:
            debug_log(f"❌ [WorkerManager] Wait error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    async def cleanup(self):
        """Clean up worker manager resources."""
        debug_log(f"🧹 [WorkerManager] Cleaning up worker manager")
        
        await self.stop_workers()
        
        # Clear queues
        while not self.task_queue.empty():
            try:
                self.task_queue.get_nowait()
                self.task_queue.task_done()
            except:
                pass
        
        while not self.priority_queue.empty():
            try:
                self.priority_queue.get_nowait()
                self.priority_queue.task_done()
            except:
                pass
        
        # Clear handlers
        self.task_handlers.clear()
        
        debug_log(f"🧹 [WorkerManager] Worker manager cleanup completed")
