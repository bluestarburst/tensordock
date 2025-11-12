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
        self.start_turn = os.getenv('START_TURN', 'true').lower() == 'true'
        
        logger.info(f"Monitor service initialized for user {self.user_id}, instance {self.instance_id}, type {self.resource_type}")
        
        # Log environment variables for debugging (excluding sensitive values)
        logger.info("=== Environment Variables ===")
        logger.info(f"  USER_ID: {self.user_id}")
        logger.info(f"  INSTANCE_ID: {self.instance_id}")
        logger.info(f"  RESOURCE_TYPE: {self.resource_type}")
        logger.info(f"  FIREBASE_FUNCTIONS_URL: {self.functions_url}")
        logger.info(f"  MONITOR_API_KEY: {'<set>' if self.api_key else '<not set>'}")
        
        # Port mapping variables (VastAI identity ports)
        vast_tcp_70000 = os.getenv('VAST_TCP_PORT_70000')
        vast_udp_70001 = os.getenv('VAST_UDP_PORT_70001')
        vast_tcp_70002 = os.getenv('VAST_TCP_PORT_70002')
        vast_tcp_22 = os.getenv('VAST_TCP_PORT_22')
        logger.info("  === Port Mapping Variables ===")
        logger.info(f"  VAST_TCP_PORT_70000 (Python server): {vast_tcp_70000 or '<not set>'}")
        logger.info(f"  VAST_UDP_PORT_70001 (TURN server): {vast_udp_70001 or '<not set>'}")
        logger.info(f"  VAST_TCP_PORT_70002 (Jupyter): {vast_tcp_70002 or '<not set>'}")
        logger.info(f"  VAST_TCP_PORT_22 (SSH): {vast_tcp_22 or '<not set>'}")
        
        # Network variables
        public_ip = os.getenv('PUBLIC_IPADDR', '')
        logger.info("  === Network Variables ===")
        logger.info(f"  PUBLIC_IPADDR: {public_ip or '<not set>'}")
        
        # Service configuration
        start_turn = os.getenv('START_TURN', '')
        jupyter_token = os.getenv('JUPYTER_TOKEN', '')
        turn_username = os.getenv('TURN_USERNAME', '')
        turn_password = os.getenv('TURN_PASSWORD', '')
        logger.info("  === Service Configuration ===")
        logger.info(f"  START_TURN: {start_turn or '<not set>'}")
        logger.info(f"  JUPYTER_TOKEN: {'<set>' if jupyter_token else '<not set>'}")
        logger.info(f"  TURN_USERNAME: {turn_username or '<not set>'}")
        logger.info(f"  TURN_PASSWORD: {'<set>' if turn_password else '<not set>'}")
        logger.info("================================")
    
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
    
    def _check_turn_server_process(self) -> bool:
        """Check if the TURN server process is running using psutil."""
        if not self.start_turn:
            return True  # Not required to be running
        try:
            import psutil
            for proc in psutil.process_iter(['name', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline') or []
                    cmdline_str = ' '.join(str(c) for c in cmdline)
                    if 'turnserver' in cmdline_str:
                        logger.debug("TURN server process found.")
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            logger.debug("TURN server process not found.")
            return False
        except ImportError:
            logger.warning("psutil is not installed, cannot check TURN server process health. Assuming it's running.")
            return True # Fail open if psutil isn't installed
        except Exception as e:
            logger.error(f"Error checking TURN server process: {e}")
            return False

    def _check_services_ready(self) -> bool:
        """Check if Jupyter (port 8888) and Python server (port 8765) are accepting connections"""
        try:
            # Check Jupyter on port 8888 - try both localhost and 127.0.0.1
            jupyter_ready = False
            jupyter_error = None
            for host in ['127.0.0.1', 'localhost']:
                try:
                    jupyter_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    jupyter_socket.settimeout(2)
                    jupyter_result = jupyter_socket.connect_ex((host, 8888))
                    jupyter_socket.close()
                    if jupyter_result == 0:
                        jupyter_ready = True
                        break
                    else:
                        jupyter_error = f"Connection failed with error code {jupyter_result}"
                except Exception as e:
                    jupyter_error = str(e)
                    logger.debug(f"Error connecting to Jupyter on {host}:8888: {e}")
                    continue
            
            # Check Python server on port 8765 - try both localhost and 127.0.0.1
            python_ready = False
            python_error = None
            for host in ['127.0.0.1', 'localhost']:
                try:
                    python_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    python_socket.settimeout(2)
                    python_result = python_socket.connect_ex((host, 8765))
                    python_socket.close()
                    if python_result == 0:
                        python_ready = True
                        break
                    else:
                        python_error = f"Connection failed with error code {python_result}"
                except Exception as e:
                    python_error = str(e)
                    logger.debug(f"Error connecting to Python server on {host}:8765: {e}")
                    continue
            
            # If socket checks fail, try checking if ports are listening using ss/netstat
            if not jupyter_ready:
                port_listening = self._check_port_listening(8888)
                if port_listening:
                    # Port is listening but not accepting connections - might be starting up
                    if not hasattr(self, '_jupyter_port_listening_logged'):
                        logger.info("Jupyter port 8888 is listening but not accepting connections yet (service may be starting)")
                        self._jupyter_port_listening_logged = True
                else:
                    # Log first time we detect port not listening
                    if not hasattr(self, '_jupyter_port_not_listening_logged'):
                        logger.info(f"Jupyter port 8888 not listening: {jupyter_error or 'connection refused'}")
                        self._jupyter_port_not_listening_logged = True
                    else:
                        logger.debug(f"Jupyter port 8888 not listening: {jupyter_error or 'connection refused'}")
            
            if not python_ready:
                port_listening = self._check_port_listening(8765)
                if port_listening:
                    # Port is listening but not accepting connections - might be starting up
                    if not hasattr(self, '_python_port_listening_logged'):
                        logger.info("Python server port 8765 is listening but not accepting connections yet (service may be starting)")
                        self._python_port_listening_logged = True
                else:
                    # Log first time we detect port not listening
                    if not hasattr(self, '_python_port_not_listening_logged'):
                        logger.info(f"Python server port 8765 not listening: {python_error or 'connection refused'}")
                        self._python_port_not_listening_logged = True
                    else:
                        logger.debug(f"Python server port 8765 not listening: {python_error or 'connection refused'}")
            
            # Check TURN server process if it's supposed to start
            turn_ready = self._check_turn_server_process()

            if jupyter_ready and python_ready and turn_ready:
                # Only log at info level if this is the first time services are ready
                # (to avoid spam when called from process health check)
                if not hasattr(self, '_services_ready_logged'):
                    logger.info("All services (Jupyter, Python server, TURN server) are ready")
                    self._services_ready_logged = True
                return True
            else:
                # Reset flag if services become unavailable
                if hasattr(self, '_services_ready_logged'):
                    self._services_ready_logged = False
                # Only log at debug level to avoid spam - detailed info already logged above
                return False
                
        except Exception as e:
            logger.error(f"Error checking service readiness: {e}")
            return False
    
    def _check_port_listening(self, port: int) -> bool:
        """Check if a port is listening using ss or netstat as fallback"""
        try:
            # Try ss first (more common on modern systems)
            result = subprocess.run(
                ['ss', '-tln', f'sport = :{port}'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and str(port) in result.stdout:
                return True
            
            # Fallback to netstat
            result = subprocess.run(
                ['netstat', '-tln'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and f':{port}' in result.stdout:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug(f"Could not check port {port} via ss/netstat: {e}")
        
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
        """Check if processes are running via supervisorctl, with fallback to socket checks"""
        supervisorctl_available = False
        
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
            
            if result.returncode == 0:
                supervisorctl_available = True
                # Check if critical processes are running
                output = result.stdout
                jupyter_running = 'jupyter' in output and 'RUNNING' in output
                python_server_running = 'python_server' in output and 'RUNNING' in output
                turn_server_running = not self.start_turn or ('turn_server' in output and 'RUNNING' in output)
                
                # Log what we found for debugging
                if not hasattr(self, '_last_supervisorctl_check'):
                    logger.info(f"supervisorctl check: jupyter={'RUNNING' if jupyter_running else 'NOT RUNNING'}, "
                              f"python_server={'RUNNING' if python_server_running else 'NOT RUNNING'}, "
                              f"turn_server={'RUNNING' if turn_server_running else 'NOT RUNNING'}")
                    self._last_supervisorctl_check = True
                
                if not jupyter_running:
                    logger.warning("Jupyter server not running (supervisorctl), attempting restart")
                    subprocess.run(['supervisorctl', '-c', '/etc/supervisor/conf.d/supervisord.conf', 'restart', 'jupyter'], timeout=10, capture_output=True)
                
                if not python_server_running:
                    logger.warning("Python server not running (supervisorctl), attempting restart")
                    subprocess.run(['supervisorctl', '-c', '/etc/supervisor/conf.d/supervisord.conf', 'restart', 'python_server'], timeout=10, capture_output=True)
                
                if not turn_server_running and self.start_turn:
                    logger.warning("TURN server not running (supervisorctl), attempting restart")
                    subprocess.run(['supervisorctl', '-c', '/etc/supervisor/conf.d/supervisord.conf', 'restart', 'turn_server'], timeout=10, capture_output=True)

                # If supervisorctl shows RUNNING, trust it even if socket checks might fail
                # (services might be starting up and not ready to accept connections yet)
                return jupyter_running and python_server_running and turn_server_running
            else:
                # supervisorctl failed - log at info level first time, then debug
                error_msg = result.stderr.strip() if result.stderr else "No error message"
                output_msg = result.stdout.strip() if result.stdout else "No output"
                if not hasattr(self, '_supervisorctl_failed_logged'):
                    logger.info(f"supervisorctl unavailable (returncode={result.returncode}): {error_msg}. Using fallback checks.")
                    if output_msg:
                        logger.info(f"supervisorctl stdout: {output_msg}")
                    self._supervisorctl_failed_logged = True
                else:
                    logger.debug(f"supervisorctl unavailable (returncode={result.returncode}): {error_msg}. Using fallback checks.")
            
        except subprocess.TimeoutExpired:
            if not hasattr(self, '_supervisorctl_timeout_logged'):
                logger.info("supervisorctl command timed out, using fallback checks")
                self._supervisorctl_timeout_logged = True
            else:
                logger.debug("supervisorctl command timed out, using fallback checks")
        except Exception as e:
            if not hasattr(self, '_supervisorctl_error_logged'):
                logger.info(f"supervisorctl error: {e}, using fallback checks")
                self._supervisorctl_error_logged = True
            else:
                logger.debug(f"supervisorctl error: {e}, using fallback checks")
        
        # Fallback: Use socket checks (most reliable) and process checks
        return self._check_processes_via_socket_and_ps()
    
    def _check_processes_via_socket_and_ps(self):
        """Fallback: Check if processes are running via socket connections (most reliable) and psutil"""
        # First, check sockets (most reliable method)
        socket_check_passed = self._check_services_ready()
        
        if socket_check_passed:
            # Services are accepting connections - they're definitely running
            # Only log process check failures at debug level since socket check passed
            try:
                import psutil
                processes = list(psutil.process_iter(['name', 'cmdline', 'pid', 'username']))
                
                jupyter_found = False
                python_found = False
                turn_found = not self.start_turn # True if not required
                
                for proc in processes:
                    try:
                        cmdline = proc.info.get('cmdline') or []
                        cmdline_str = ' '.join(str(c) for c in cmdline)
                        name = proc.info.get('name', '').lower()
                        
                        # Check for Jupyter
                        if not jupyter_found:
                            if 'jupyter' in name or 'jupyter' in cmdline_str.lower():
                                jupyter_found = True
                        
                        # Check for Python server - look for multiple patterns
                        if not python_found:
                            if ('run_modular.py' in cmdline_str or 
                                'server_modular' in cmdline_str or
                                ('python' in name and 'run_modular' in cmdline_str)):
                                python_found = True

                        # Check for TURN server
                        if not turn_found and self.start_turn:
                            if 'turnserver' in cmdline_str:
                                turn_found = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                
                # Only log if socket check passed but process check failed (unusual case)
                if not jupyter_found:
                    logger.debug("Jupyter process not found via psutil (but socket check passed - service is running)")
                if not python_found:
                    logger.debug("Python server process not found via psutil (but socket check passed - service is running)")
                if not turn_found and self.start_turn:
                    logger.debug("TURN server process not found via psutil (but socket check passed for others)")
                
                # Return socket check result (more reliable)
                return socket_check_passed and turn_found
                
            except Exception as e:
                logger.debug(f"Error checking processes via psutil: {e}, but socket check passed")
                return socket_check_passed  # Trust socket check
        else:
            # Socket check failed - services might not be running, or might be starting up
            # Check processes to see if they exist but aren't listening yet
            try:
                import psutil
                processes = list(psutil.process_iter(['name', 'cmdline', 'pid', 'username']))
                
                jupyter_found = False
                python_found = False
                turn_found = not self.start_turn # True if not required
                
                for proc in processes:
                    try:
                        cmdline = proc.info.get('cmdline') or []
                        cmdline_str = ' '.join(str(c) for c in cmdline)
                        name = proc.info.get('name', '').lower()
                        
                        # Check for Jupyter
                        if not jupyter_found:
                            if 'jupyter' in name or 'jupyter' in cmdline_str.lower():
                                jupyter_found = True
                        
                        # Check for Python server - look for multiple patterns
                        if not python_found:
                            if ('run_modular.py' in cmdline_str or 
                                'server_modular' in cmdline_str or
                                ('python' in name and 'run_modular' in cmdline_str)):
                                python_found = True

                        # Check for TURN server
                        if not turn_found and self.start_turn:
                            if 'turnserver' in cmdline_str:
                                turn_found = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                
                # If processes are found but sockets aren't ready, they might be starting up
                # Trust that processes are running if found (give them time to start listening)
                if jupyter_found and python_found and turn_found:
                    # Processes exist - trust they're running even if sockets not ready yet
                    if not hasattr(self, '_processes_found_but_sockets_not_ready'):
                        logger.info("Processes found (jupyter, python_server, turn_server) but sockets not ready yet - services may be starting up")
                        self._processes_found_but_sockets_not_ready = True
                    return True  # Trust process existence
                else:
                    # Processes not found - services are definitely not running
                    if not jupyter_found:
                        logger.warning("Jupyter server not running: process not found and port 8888 not accepting connections")
                    if not python_found:
                        logger.warning("Python server not running: process not found and port 8765 not accepting connections")
                    if not turn_found and self.start_turn:
                        logger.warning("TURN server not running: process not found")
                    
                    return False
                
            except Exception as e:
                logger.error(f"Error checking processes via psutil: {e}")
                # If we can't check processes, trust socket check (more reliable)
                return socket_check_passed
    
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
    
    async def update_session_ports_and_ip(self):
        """Update session document with ports and public IP from environment variables"""
        try:
            # Read VastAI identity port mappings from environment
            # Identity ports (70000+) map to random external ports where internal = external
            # VAST_TCP_PORT_70000 → Python server (internal: 8765)
            # VAST_UDP_PORT_70001 → TURN server (internal: 3478)
            # VAST_TCP_PORT_70002 → Jupyter (internal: 8888)
            # VAST_TCP_PORT_22 → SSH (internal: 22)
            vast_tcp_port_70000 = os.getenv('VAST_TCP_PORT_70000')  # Python server
            vast_udp_port_70001 = os.getenv('VAST_UDP_PORT_70001')  # TURN server
            vast_tcp_port_70002 = os.getenv('VAST_TCP_PORT_70002')  # Jupyter
            vast_tcp_port_22 = os.getenv('VAST_TCP_PORT_22')  # SSH
            public_ip = os.getenv('PUBLIC_IPADDR', '')
            
            # If PUBLIC_IPADDR is "auto" or empty, try to detect it
            if not public_ip or public_ip == "auto":
                try:
                    # Try DigitalOcean metadata first
                    import urllib.request
                    try:
                        with urllib.request.urlopen('http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address', timeout=2) as response:
                            public_ip = response.read().decode('utf-8').strip()
                            logger.info(f"Detected public IP from metadata: {public_ip}")
                    except Exception:
                        # Fallback to external service
                        try:
                            with urllib.request.urlopen('https://ifconfig.co', timeout=3) as response:
                                public_ip = response.read().decode('utf-8').strip()
                                logger.info(f"Detected public IP from ifconfig.co: {public_ip}")
                        except Exception as e:
                            logger.warning(f"Could not detect public IP: {e}")
                            public_ip = None
                except Exception as e:
                    logger.warning(f"Error detecting public IP: {e}")
                    public_ip = None
            
            # Build ports array with objects containing label, internal, external, and protocol
            # Format: [{"label": "python", "internal": 8765, "external": 63562, "protocol": "tcp"}, ...]
            ports = []
            
            # Python server: 70000 → 8765
            if vast_tcp_port_70000:
                try:
                    external_port = int(vast_tcp_port_70000)
                    ports.append({
                        "label": "python",
                        "internal": 8765,
                        "external": external_port,
                        "protocol": "tcp"
                    })
                except ValueError:
                    logger.warning(f"Invalid VAST_TCP_PORT_70000: {vast_tcp_port_70000}")
            
            # TURN server: 70001 → 3478
            if vast_udp_port_70001:
                try:
                    external_port = int(vast_udp_port_70001)
                    ports.append({
                        "label": "turn",
                        "internal": 3478,
                        "external": external_port,
                        "protocol": "udp"
                    })
                except ValueError:
                    logger.warning(f"Invalid VAST_UDP_PORT_70001: {vast_udp_port_70001}")
            
            # Jupyter: 70002 → 8888
            if vast_tcp_port_70002:
                try:
                    external_port = int(vast_tcp_port_70002)
                    ports.append({
                        "label": "jupyter",
                        "internal": 8888,
                        "external": external_port,
                        "protocol": "tcp"
                    })
                except ValueError:
                    logger.warning(f"Invalid VAST_TCP_PORT_70002: {vast_tcp_port_70002}")
            
            # SSH: 22 → 22
            if vast_tcp_port_22:
                try:
                    external_port = int(vast_tcp_port_22)
                    ports.append({
                        "label": "ssh",
                        "internal": 22,
                        "external": external_port,
                        "protocol": "tcp"
                    })
                except ValueError:
                    logger.warning(f"Invalid VAST_TCP_PORT_22: {vast_tcp_port_22}")
            
            # Only update if we have at least ports or IP
            if ports or public_ip:
                result = await self._call_function('updateSessionPorts', {
                    'instanceId': self.instance_id,
                    'publicIp': public_ip if public_ip else None,
                    'ports': ports if ports else None,
                })
                
                if result and result.get('success'):
                    logger.info(f"Session ports and IP updated: ports={ports}, publicIp={public_ip}")
                else:
                    logger.warning(f"Failed to update session ports/IP: {result.get('error', 'Unknown error') if result else 'No response'}")
            else:
                logger.debug("No port/IP information available from environment variables yet")
                
        except Exception as e:
            logger.error(f"Error updating session ports/IP: {e}")
    
    async def monitor_loop(self):
        """Main monitoring loop - checks services ready, credits, heartbeat, and process health"""
        logger.info("Starting monitoring loop")
        
        # Update session ports and IP from environment variables on startup
        # This ensures the session document has the correct external ports and IP
        await self.update_session_ports_and_ip()
        
        # Update TURN credentials in Firestore on startup
        # This ensures the frontend can retrieve them for WebRTC connection
        await self.update_turn_credentials()
        
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                # Check process health (logs warnings only if services are actually down)
                process_health_ok = self._check_process_health()
                
                # If session is still provisioning, check if services are ready
                if not self.session_started:
                    services_ready = self._check_services_ready()
                    
                    # If supervisorctl shows processes as RUNNING, trust that even if socket checks fail
                    # (services might be starting up and not ready to accept connections yet)
                    if process_health_ok and not services_ready:
                        # Processes are running but sockets not ready - give them more time
                        if not hasattr(self, '_services_starting_logged'):
                            logger.info("Services are running (supervisorctl) but not yet accepting connections - waiting for them to fully start")
                            self._services_starting_logged = True
                        # Don't mark as started yet, but also don't log warning
                    elif services_ready:
                        await self._mark_session_started()
                    elif not process_health_ok:
                        # Services not ready and process health check failed
                        logger.warning("Services not ready yet - waiting for Jupyter and Python server to start")
                
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

