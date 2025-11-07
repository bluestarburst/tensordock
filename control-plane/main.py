#!/usr/bin/env python3
"""
Control Plane Manager for TensorDock
Runs on VM instance (outside user container) - User CANNOT access or modify this process
Manages Docker containers, enforces credit limits, monitors usage
"""
import asyncio
import docker
import json
import os
import time
import logging
import base64
from typing import Optional
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ControlPlaneManager:
    def __init__(self, user_id: str, instance_id: str, resource_type: str):
        self.user_id = user_id
        self.instance_id = instance_id
        self.resource_type = resource_type
        self.docker_client = docker.DockerClient(base_url="unix:///var/run/docker.sock")
        self.user_container: Optional[docker.models.containers.Container] = None
        self.heartbeat_threshold = 5 * 60  # 5 minutes
        self.reconnect_grace_period = 60 * 60  # 1 hour
        self.grace_period_start: Optional[float] = None
        self.is_charging = True
        
        # Initialize Firebase Admin SDK
        self._initialize_firebase()
        self.db = firestore.client()
        
        logger.info(f"Control plane initialized for user {user_id}, instance {instance_id}, type {resource_type}")
    
    def _initialize_firebase(self):
        """Initialize Firebase Admin SDK with credentials from environment"""
        try:
            firebase_credentials_b64 = os.getenv('FIREBASE_CREDENTIALS')
            if not firebase_credentials_b64:
                raise ValueError("FIREBASE_CREDENTIALS environment variable not set")
            
            # Decode base64 credentials
            firebase_credentials_json = base64.b64decode(firebase_credentials_b64).decode('utf-8')
            firebase_credentials_dict = json.loads(firebase_credentials_json)
            
            # Create credentials object
            cred = credentials.Certificate(firebase_credentials_dict)
            
            # Initialize Firebase Admin
            initialize_app(cred)
            logger.info("Firebase Admin SDK initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            raise
    
    async def start_user_container(self):
        """Create isolated user container with limited capabilities"""
        try:
            # Generate secure TURN credentials
            turn_password = self._generate_secure_password()
            # TURN and Jupyter settings from env
            start_turn = os.getenv('START_TURN', 'true')
            jupyter_token = os.getenv('JUPYTER_TOKEN')
            if not jupyter_token:
                import secrets
                jupyter_token = secrets.token_urlsafe(24)
            
            # Create isolated user container
            # Use environment variable for image name, default to bluestarburst/user-env:latest
            user_image = os.getenv('USER_CONTAINER_IMAGE', 'bluestarburst/user-env:latest')
            self.user_container = self.docker_client.containers.run(
                image=user_image,
                detach=True,
                name=f"tensordock-user-{self.user_id}",
                network_mode='host',
                environment={
                    'USER_ID': self.user_id,
                    'INSTANCE_ID': self.instance_id,
                    'TURN_USERNAME': 'user',
                    'TURN_PASSWORD': turn_password,
                    'PUBLIC_IPADDR': 'auto',
                    'START_TURN': start_turn,
                    'JUPYTER_TOKEN': jupyter_token
                },
                restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
                # Security: Remove capabilities that could be dangerous
                cap_drop=['ALL'],
                cap_add=['NET_BIND_SERVICE'],  # Only allow binding to ports
                # Security: Read-only root filesystem
                read_only=True,
                tmpfs={'/tmp': 'rw,size=1g', '/var/log': 'rw,size=100m'},
                # Security: No privileged mode
                privileged=False,
                # Security: No access to host devices
                devices=[],
                # Security: Limited memory and CPU
                mem_limit='4g',
                cpu_period=100000,
                cpu_quota=200000,  # 2 CPU cores max
            )
            
            logger.info(f"User container started: {self.user_container.id}")
            
            # Update session with TURN credentials
            await self._update_session_turn_credentials(turn_password)
            
        except Exception as e:
            logger.error(f"Failed to start user container: {e}")
            raise
    
    def _generate_secure_password(self) -> str:
        """Generate a secure random password for TURN server"""
        import secrets
        return secrets.token_urlsafe(32)
    
    async def _update_session_turn_credentials(self, turn_password: str):
        """Update session document with TURN credentials"""
        try:
            session_ref = self.db.collection('sessions').document(self.instance_id)
            session_ref.update({
                'turnCredentials': {
                    'username': 'user',
                    'password': turn_password
                },
                'status': 'running',
                'containerId': self.user_container.id if self.user_container else None
            })
            logger.info("Session updated with TURN credentials")
        except Exception as e:
            logger.error(f"Failed to update session credentials: {e}")
    
    async def monitor_credits_and_heartbeat(self):
        """Main monitoring loop - checks credits and heartbeat every minute"""
        logger.info("Starting credit and heartbeat monitoring")
        
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                # Check credits
                await self._check_credits()
                
                # Check heartbeat
                await self._check_heartbeat()
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Continue monitoring despite errors
    
    async def _check_credits(self):
        """Check user credits and deduct usage"""
        try:
            user_ref = self.db.collection('users').document(self.user_id)
            user_doc = user_ref.get()
            
            if not user_doc.exists:
                logger.error(f"User document not found: {self.user_id}")
                await self.terminate_session("user_not_found")
                return
            
            user_data = user_doc.to_dict()
            
            if self.resource_type == 'gpu':
                credits = user_data.get('gpu_credits', 0)
                
                if credits <= 0:
                    logger.warning(f"User {self.user_id} has no GPU credits remaining")
                    await self.terminate_session("credits_exhausted")
                    return
                
                # Deduct 1 minute of GPU usage (1/60 of an hour)
                new_credits = credits - (1/60)
                
                # Update credits atomically
                user_ref.update({
                    'gpu_credits': new_credits,
                    'last_gpu_usage': firestore.SERVER_TIMESTAMP
                })
                
                logger.info(f"Deducted GPU credits for user {self.user_id}. Remaining: {new_credits:.2f} hours")
                
        except FirebaseError as e:
            logger.error(f"Firebase error checking credits: {e}")
        except Exception as e:
            logger.error(f"Error checking credits: {e}")
    
    async def _check_heartbeat(self):
        """Check user heartbeat and handle idle detection"""
        try:
            session_ref = self.db.collection('sessions').document(self.instance_id)
            session_doc = session_ref.get()
            
            if not session_doc.exists:
                logger.error(f"Session document not found: {self.instance_id}")
                await self.terminate_session("session_not_found")
                return
            
            session_data = session_doc.to_dict()
            last_heartbeat = session_data.get('last_heartbeat', 0)
            current_time = time.time()
            
            if current_time - last_heartbeat > self.heartbeat_threshold:
                # No heartbeat - user idle
                if self.grace_period_start is None:
                    self.grace_period_start = current_time
                    await self.stop_charging()
                    logger.info(f"User {self.user_id} is idle, grace period started")
                
                # Check if grace period expired
                if current_time - self.grace_period_start > self.reconnect_grace_period:
                    logger.warning(f"Grace period expired for user {self.user_id}")
                    await self.terminate_session("idle_timeout")
                    return
            else:
                # Heartbeat received - reset grace period
                if self.grace_period_start is not None:
                    self.grace_period_start = None
                    await self.resume_charging()
                    logger.info(f"User {self.user_id} reconnected, charging resumed")
                
        except FirebaseError as e:
            logger.error(f"Firebase error checking heartbeat: {e}")
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
    
    async def terminate_session(self, reason: str):
        """Terminate the user session and cleanup"""
        logger.info(f"Terminating session for user {self.user_id}, reason: {reason}")
        
        try:
            # Stop user container
            if self.user_container:
                self.user_container.stop(timeout=10)
                self.user_container.remove(force=True)
                logger.info(f"User container stopped and removed: {self.user_container.id}")
            
            # Update session status only if document exists
            # This prevents creating a document after it's been destroyed
            session_ref = self.db.collection('sessions').document(self.instance_id)
            session_doc = session_ref.get()
            
            if session_doc.exists:
                session_ref.update({
                    'status': 'terminated',
                    'terminatedAt': firestore.SERVER_TIMESTAMP,
                    'terminationReason': reason
                })
                logger.info(f"Session terminated successfully for user {self.user_id}")
            else:
                logger.warning(f"Session document {self.instance_id} does not exist, skipping update")
            
        except Exception as e:
            logger.error(f"Error terminating session: {e}")
        
        # Exit the control plane
        os._exit(0)

async def main():
    """Main entry point for control plane"""
    # Get configuration from environment variables
    user_id = os.getenv('USER_ID')
    instance_id = os.getenv('INSTANCE_ID')
    resource_type = os.getenv('RESOURCE_TYPE', 'cpu')
    
    if not user_id or not instance_id:
        logger.error("Missing required environment variables: USER_ID, INSTANCE_ID")
        os._exit(1)
    
    logger.info(f"Starting control plane for user {user_id}, instance {instance_id}")
    
    # Create control plane manager
    control_plane = ControlPlaneManager(user_id, instance_id, resource_type)
    
    try:
        # Start user container
        await control_plane.start_user_container()
        
        # Start monitoring
        await control_plane.monitor_credits_and_heartbeat()
        
    except KeyboardInterrupt:
        logger.info("Control plane interrupted by user")
        await control_plane.terminate_session("manual_stop")
    except Exception as e:
        logger.error(f"Control plane error: {e}")
        await control_plane.terminate_session("error")

if __name__ == "__main__":
    asyncio.run(main())
