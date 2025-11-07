#!/usr/bin/env python3
"""
Monitoring Service for TensorDock
Runs as watcher user - makes HTTP calls to Firebase Functions (no Admin SDK)
Monitors credits, heartbeat, and process health
"""
import asyncio
import os
import time
import logging
import subprocess
import sys
import requests
import socket
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MonitorService:
    def __init__(self):
        self.instance_id = os.getenv('INSTANCE_ID')
        self.user_id = os.getenv('USER_ID')
        self.resource_type = os.getenv('RESOURCE_TYPE', 'cpu')
        self.functions_url = os.getenv('FIREBASE_FUNCTIONS_URL')
        self.api_key = os.getenv('MONITOR_API_KEY')
        
        if not self.instance_id or not self.user_id:
            logger.error("Missing required environment variables: INSTANCE_ID, USER_ID")
            sys.exit(1)
        
        if not self.functions_url or not self.api_key:
            logger.error("Missing required environment variables: FIREBASE_FUNCTIONS_URL, MONITOR_API_KEY")
            sys.exit(1)
        
        self.heartbeat_threshold = 5 * 60  # 5 minutes
        self.reconnect_grace_period = 60 * 60  # 1 hour
        self.grace_period_start: Optional[float] = None
        self.is_charging = True
        self.session_started = False  # Track if we've marked session as started
        
        logger.info(f"Monitor service initialized for user {self.user_id}, instance {self.instance_id}, type {self.resource_type}")
    
    async def update_turn_credentials(self):
        """Update TURN credentials in Firestore session document"""
        try:
            turn_username = os.getenv('TURN_USERNAME', 'user')
            turn_password = os.getenv('TURN_PASSWORD')
            
            if not turn_password:
                logger.warning("TURN_PASSWORD not set, skipping TURN credentials update")
                return
            
            result = await self._call_function('updateTurnCredentials', {
                'instanceId': self.instance_id,
                'turnUsername': turn_username,
                'turnPassword': turn_password,
            })
            
            if result and result.get('success'):
                logger.info(f"TURN credentials updated in Firestore for instance {self.instance_id}")
            else:
                logger.warning(f"Failed to update TURN credentials: {result.get('error', 'Unknown error') if result else 'No response'}")
                
        except Exception as e:
            logger.error(f"Error updating TURN credentials: {e}")
    
    async def _call_function(self, function_name: str, data: dict) -> Optional[dict]:
        """Make HTTP POST request to Firebase Function"""
        try:
            url = f"{self.functions_url}/{function_name}"
            payload = {**data, "apiKey": self.api_key}
            
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if not result.get('success', False):
                logger.error(f"Function {function_name} returned error: {result.get('error', 'Unknown error')}")
                return None
            
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error calling {function_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error calling {function_name}: {e}")
            return None
    
    def _check_services_ready(self) -> bool:
        """Check if Jupyter (port 8888) and Python server (port 8765) are accepting connections"""
        try:
            # Check Jupyter on port 8888
            jupyter_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            jupyter_socket.settimeout(2)
            jupyter_result = jupyter_socket.connect_ex(('localhost', 8888))
            jupyter_socket.close()
            jupyter_ready = jupyter_result == 0
            
            # Check Python server on port 8765
            python_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            python_socket.settimeout(2)
            python_result = python_socket.connect_ex(('localhost', 8765))
            python_socket.close()
            python_ready = python_result == 0
            
            if jupyter_ready and python_ready:
                logger.info("Both Jupyter and Python server are ready")
                return True
            else:
                if not jupyter_ready:
                    logger.debug("Jupyter server not ready yet (port 8888)")
                if not python_ready:
                    logger.debug("Python server not ready yet (port 8765)")
                return False
                
        except Exception as e:
            logger.error(f"Error checking service readiness: {e}")
            return False
    
    async def _mark_session_started(self):
        """Mark session as started (set status to running and startTime)"""
        if self.session_started:
            return  # Already marked as started
        
        try:
            result = await self._call_function('markSessionStarted', {
                'instanceId': self.instance_id
            })
            
            if result and result.get('success'):
                self.session_started = True
                logger.info(f"Session marked as started for instance {self.instance_id}")
            else:
                logger.warning(f"Failed to mark session as started: {result.get('error', 'Unknown error') if result else 'No response'}")
                
        except Exception as e:
            logger.error(f"Error marking session as started: {e}")
    
    async def _check_credits_remaining(self):
        """Check if user has enough credits remaining based on elapsed time"""
        try:
            result = await self._call_function('checkCreditsRemaining', {
                'instanceId': self.instance_id
            })
            
            if not result:
                logger.warning("Failed to check credits remaining, will retry next cycle")
                return
            
            has_enough_credits = result.get('hasEnoughCredits', True)
            credits_remaining = result.get('creditsRemaining', 0)
            credits_needed = result.get('creditsNeeded', 0)
            should_terminate = result.get('shouldTerminate', False)
            
            logger.info(f"Credits check: remaining={credits_remaining:.2f} hours, needed={credits_needed:.2f} hours, has_enough={has_enough_credits}")
            
            if should_terminate:
                logger.warning(f"User {self.user_id} has insufficient credits remaining")
                await self.terminate_session("credits_exhausted")
                
        except Exception as e:
            logger.error(f"Error checking credits remaining: {e}")
    
    async def _check_heartbeat(self):
        """Check user heartbeat and handle idle detection via HTTP call"""
        try:
            result = await self._call_function('checkHeartbeat', {
                'instanceId': self.instance_id
            })
            
            if not result:
                logger.warning("Failed to check heartbeat, will retry next cycle")
                return
            
            is_idle = result.get('isIdle', False)
            grace_period_active = result.get('gracePeriodActive', False)
            should_terminate = result.get('shouldTerminate', False)
            
            if should_terminate:
                logger.warning(f"Grace period expired for user {self.user_id}")
                await self.terminate_session("idle_timeout")
                return
            
            if is_idle and not grace_period_active:
                # Grace period just started
                if self.grace_period_start is None:
                    self.grace_period_start = time.time()
                    await self.stop_charging()
                    logger.info(f"User {self.user_id} is idle, grace period started")
            elif not is_idle:
                # Heartbeat received - reset grace period
                if self.grace_period_start is not None:
                    self.grace_period_start = None
                    await self.resume_charging()
                    logger.info(f"User {self.user_id} reconnected, charging resumed")
                
        except Exception as e:
            logger.error(f"Error checking heartbeat: {e}")
    
    async def stop_charging(self):
        """Stop charging user for idle time"""
        if self.is_charging:
            self.is_charging = False
            logger.info(f"Stopped charging for user {self.user_id}")
    
    async def resume_charging(self):
        """Resume charging user"""
        if not self.is_charging:
            self.is_charging = True
            logger.info(f"Resumed charging for user {self.user_id}")
    
    def _check_process_health(self):
        """Check if processes are running via supervisorctl"""
        try:
            # Ensure socket has correct permissions (watcher user needs group access)
            # This is a workaround if supervisord.conf chown doesn't work
            socket_path = '/var/run/supervisor.sock'
            if os.path.exists(socket_path):
                try:
                    # Try to fix permissions if we can (requires root, but worth trying)
                    os.chmod(socket_path, 0o770)
                    # Try to change group to watcher (requires root)
                    import grp
                    try:
                        watcher_gid = grp.getgrnam('watcher').gr_gid
                        os.chown(socket_path, -1, watcher_gid)
                    except (OSError, KeyError):
                        pass  # Can't change ownership, but permissions might be enough
                except (OSError, PermissionError):
                    pass  # Can't fix permissions, continue anyway
            
            # Check supervisorctl status - must specify config file to use Unix socket
            result = subprocess.run(
                ['supervisorctl', '-c', '/etc/supervisor/conf.d/supervisord.conf', 'status'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                # Log both stdout and stderr for debugging
                error_msg = result.stderr.strip() if result.stderr else "No error message"
                output_msg = result.stdout.strip() if result.stdout else "No output"
                logger.warning(f"supervisorctl status failed (returncode={result.returncode}): {error_msg}")
                if output_msg:
                    logger.debug(f"supervisorctl stdout: {output_msg}")
                # Try alternative: check processes directly via ps
                return self._check_processes_via_ps()
            
            # Check if critical processes are running
            output = result.stdout
            jupyter_running = 'jupyter' in output and 'RUNNING' in output
            python_server_running = 'python_server' in output and 'RUNNING' in output
            
            if not jupyter_running:
                logger.warning("Jupyter server not running, attempting restart")
                subprocess.run(['supervisorctl', '-c', '/etc/supervisor/conf.d/supervisord.conf', 'restart', 'jupyter'], timeout=10)
            
            if not python_server_running:
                logger.warning("Python server not running, attempting restart")
                subprocess.run(['supervisorctl', '-c', '/etc/supervisor/conf.d/supervisord.conf', 'restart', 'python_server'], timeout=10)
            
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("supervisorctl command timed out")
            return self._check_processes_via_ps()
        except Exception as e:
            logger.error(f"Error checking process health: {e}")
            return self._check_processes_via_ps()
    
    def _check_processes_via_ps(self):
        """Fallback: Check if processes are running via ps command"""
        try:
            import psutil
            processes = {p.name(): p for p in psutil.process_iter(['name', 'cmdline'])}
            
            jupyter_running = any(
                'jupyter' in p.info['name'].lower() or 
                any('jupyter' in str(cmd).lower() for cmd in (p.info.get('cmdline') or []))
                for p in processes.values()
            )
            
            python_server_running = any(
                'run_modular.py' in str(p.info.get('cmdline', []))
                for p in processes.values()
            )
            
            if not jupyter_running:
                logger.warning("Jupyter server not running (checked via ps)")
            if not python_server_running:
                logger.warning("Python server not running (checked via ps)")
            
            return jupyter_running and python_server_running
        except Exception as e:
            logger.error(f"Error checking processes via ps: {e}")
            return True  # Assume OK if we can't check
    
    async def terminate_session(self, reason: str):
        """Terminate the session via HTTP call, then exit"""
        logger.info(f"Terminating session for user {self.user_id}, reason: {reason}")
        
        try:
            result = await self._call_function('terminateSession', {
                'instanceId': self.instance_id,
                'reason': reason
            })
            
            if result and result.get('success'):
                logger.info(f"Session terminated successfully for user {self.user_id}")
            else:
                logger.warning(f"Failed to terminate session via function, but exiting anyway")
                
        except Exception as e:
            logger.error(f"Error terminating session: {e}")
        
        # Exit the monitoring service (container will stop)
        sys.exit(0)
    
    async def monitor_loop(self):
        """Main monitoring loop - checks services ready, credits, heartbeat, and process health"""
        logger.info("Starting monitoring loop")
        
        # Update TURN credentials in Firestore on startup
        # This ensures the frontend can retrieve them for WebRTC connection
        await self.update_turn_credentials()
        
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                # Check process health
                self._check_process_health()
                
                # If session is still provisioning, check if services are ready
                if not self.session_started:
                    if self._check_services_ready():
                        await self._mark_session_started()
                
                # If session is started/running, check credits remaining
                if self.session_started:
                    await self._check_credits_remaining()
                
                # Check heartbeat
                await self._check_heartbeat()
                
            except KeyboardInterrupt:
                logger.info("Monitoring service interrupted by user")
                await self.terminate_session("manual_stop")
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Continue monitoring despite errors

async def main():
    """Main entry point for monitoring service"""
    monitor = MonitorService()
    await monitor.monitor_loop()

if __name__ == "__main__":
    asyncio.run(main())

