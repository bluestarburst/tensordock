import asyncio
import json
import threading
import time
import uuid
import datetime
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel, RTCConfiguration, RTCIceServer
from aiortc.contrib.signaling import object_from_string, object_to_string
import os
import logging
from pprint import pprint
import requests
from websockets.client import connect

print("bash test")

isLocal = os.environ.get('IS_LOCAL', 'false') == 'true'

print("isLocal", isLocal)

turn_server_address = os.environ.get('TURN_ADDRESS', f"0.0.0.0:{os.environ.get('VAST_UDP_PORT_70001',6000)}?transport=udp")
turn_client_address = os.environ.get('TURN_ADDRESS', f"{os.environ.get('PUBLIC_IPADDR', '0.0.0.0')}:{os.environ.get('VAST_UDP_PORT_70001',6000)}?transport=udp")
turn_username = os.environ.get('TURN_USERNAME', 'user')
turn_password = os.environ.get('TURN_PASSWORD', 'password')

logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger("webrtc")

if isLocal:
    RTC_CONFIG = RTCConfiguration([
            RTCIceServer(urls="stun:stun.l.google.com:19302")
        ])
else:
    RTC_CONFIG = RTCConfiguration([
            RTCIceServer(urls="stun:stun.l.google.com:19302"),
            RTCIceServer(
                urls=f"turn:{turn_server_address}",
                username=f"{turn_username}",
                credential=f"{turn_password}"
            )
        ])

print("RTC_CONFIG", RTC_CONFIG)

class JupyterWebRTCServer:
    
    def __init__(self):
        self.peer_connections = set()
        self.data_channels = {}
        self.session = uuid.uuid1().hex
        self.session_id = None
        self.kernel_id = None
        self.kernel_ws = None
        self.event_ws = None
        
        self.action_queue = asyncio.Queue()
        self.input_queue = asyncio.Queue()
        self.response_queue = asyncio.Queue()
        
        self.interrupt_flag = False
        self.request_input = False
        
        # Widget state tracking
        self.widget_states = {}
        self.widget_models = {}
        self.comm_managers = {}
        
        # Start worker thread
        asyncio.create_task(self.worker())
        
        # Start kernel checker
        threading.Thread(target=self.check_kernel, daemon=True).start()
        
        # Start message listeners (they will handle reconnection internally)
        asyncio.create_task(self.listen_for_messages())
        # Disable events WebSocket for now as it's not needed for basic functionality
        # asyncio.create_task(self.listen_for_events_messages())
        
        # # wait for 1 second
        time.sleep(5)
        # create a new kernel
        print("Creating new kernel")
        asyncio.create_task(self.connect_to_jupyter())

    def check_kernel(self):
        print("Kernel checker started")

    async def connect_to_jupyter(self):
        try:
            base_url = os.environ.get('JUPYTER_URL', 'http://localhost:8888')
            token = os.environ.get('JUPYTER_TOKEN', 'test')
            
            headers = {'Authorization': f'Token {token}'}
            
            # Try to reuse existing session if we have one
            if self.session_id and self.kernel_id:
                try:
                    # Check if existing session is still valid
                    url = f"{base_url}/api/sessions/{self.session_id}"
                    response = requests.get(url, headers=headers)
                    if response.status_code == 200:
                        session_info = json.loads(response.text)
                        print(f"Reusing existing session: {self.session_id}")
                        
                        # Check if kernel is still alive
                        url = f"{base_url}/api/kernels/{self.kernel_id}"
                        response = requests.get(url, headers=headers)
                        if response.status_code == 200:
                            print(f"Reusing existing kernel: {self.kernel_id}")
                        else:
                            # Kernel is dead, create new session
                            print("Existing kernel is dead, creating new session...")
                            self.session_id = None
                            self.kernel_id = None
                    else:
                        # Session is dead, create new one
                        print("Existing session is dead, creating new session...")
                        self.session_id = None
                        self.kernel_id = None
                except Exception as e:
                    print(f"Error checking existing session: {e}")
                    self.session_id = None
                    self.kernel_id = None
            
            # Create new session if needed
            if not self.session_id:
                url = f"{base_url}/api/sessions"
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
                    print(f"Failed to create session: {response.status_code} - {response.text}")
                    raise Exception(f"Session creation failed: {response.status_code}")
                
                session_info = json.loads(response.text)
                self.session_id = session_info['id']
                print(f"Created new session with ID: {self.session_id}")
                
                # get kernel info
                url = f"{base_url}/api/kernels/{session_info['kernel']['id']}"
                response = requests.get(url, headers=headers)
                if response.status_code != 200:
                    print(f"Failed to get kernel info: {response.status_code} - {response.text}")
                    raise Exception(f"Kernel info retrieval failed: {response.status_code}")
                
                kernel_info = json.loads(response.text)
                self.kernel_id = kernel_info['id']
                print(f"Connected to kernel with ID: {self.kernel_id}")
            
            # Connect to WebSocket with session ID
            ws_url = f"ws://{base_url.split('://')[-1]}/api/kernels/{self.kernel_id}/channels?session_id={self.session_id}"
            self.kernel_ws = await connect(
                ws_url, 
                extra_headers=headers
            )   
            
            # Connect to events WebSocket with proper parameters
            # Note: Jupyter events WebSocket doesn't exist in standard Jupyter server
            # We'll skip events WebSocket for now and focus on kernel messages
            self.event_ws = None
            print("Connected to kernel WebSocket")
            
            return self.session_id
        except Exception as e:
            print(f"Error connecting to Jupyter: {e}")
            self.kernel_ws = None
            self.event_ws = None
            raise
    
    async def listen_for_messages(self):
        retry_count = 0
        max_retries = 10
        
        while True:  # Outer loop for reconnection
            if not self.kernel_ws:
                if retry_count >= max_retries:
                    print(f"Max retries ({max_retries}) reached for kernel WebSocket. Stopping reconnection attempts.")
                    break
                    
                print(f"WebSocket not connected, attempting to reconnect... (attempt {retry_count + 1}/{max_retries})")
                try:
                    await self.connect_to_jupyter()
                    retry_count = 0  # Reset retry count on successful connection
                except Exception as e:
                    retry_count += 1
                    print(f"Failed to reconnect to Jupyter: {e}")
                    await asyncio.sleep(min(5 * retry_count, 30))  # Exponential backoff with max 30s
                    continue
            
            message_queue = asyncio.Queue()
            
            async def message_consumer():
                while True:
                    try:
                        message = await message_queue.get()
                        
                        # Check if message is binary or text
                        if isinstance(message, bytes):
                            print(f"Received binary message, length: {len(message)}")
                            # Skip binary messages (likely WebSocket control frames)
                            message_queue.task_done()
                            continue
                        
                        # Try to parse as JSON
                        try:
                            msg = json.loads(message)
                            
                            # Log the message type for debugging
                            msg_type = msg.get('header', {}).get('msg_type', 'unknown')
                            print(f"Broadcasting kernel message: {msg_type}")
                            
                            # Broadcast all kernel messages to clients
                            await self.broadcast({
                                'action': 'kernel',
                                'data': message,
                            })
                            
                            # Store the message in response queue for processing
                            await self.response_queue.put(msg)
                            
                        except json.JSONDecodeError as e:
                            print(f"Failed to parse message as JSON: {e}")
                            print(f"Message content: {message[:200]}...")  # Show first 200 chars
                        except UnicodeDecodeError as e:
                            print(f"Unicode decode error: {e}")
                            print(f"Message type: {type(message)}, length: {len(message) if hasattr(message, '__len__') else 'unknown'}")
                        
                        message_queue.task_done()
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        import traceback
                        traceback.print_exc()
                        await asyncio.sleep(0.1)

            # Start the consumer task
            consumer_task = asyncio.create_task(message_consumer())
            
            # Start ping task to keep connection alive
            async def ping_task():
                while True:
                    try:
                        if self.kernel_ws and self.kernel_ws.open:
                            await self.kernel_ws.ping()
                            print("WebSocket ping sent successfully")
                        else:
                            print("WebSocket not open, skipping ping")
                        await asyncio.sleep(10)  # Ping every 10 seconds (more frequent)
                    except Exception as e:
                        print(f"Ping failed: {e}")
                        break
            
            ping_task_obj = asyncio.create_task(ping_task())
            
            # Main message receiver loop
            try:
                while True:
                    try:
                        message = await self.kernel_ws.recv()
                        
                        # Filter out WebSocket control frames and binary messages
                        if isinstance(message, bytes):
                            print(f"Received binary WebSocket message, length: {len(message)}")
                            # Skip binary messages (control frames, etc.)
                            continue
                        
                        # Only process text messages
                        if isinstance(message, str):
                            await message_queue.put(message)
                        else:
                            print(f"Received non-text message: {type(message)}")
                            
                    except Exception as e:
                        print(f"Error receiving message: {e}")
                        # Check if it's a connection close error
                        if "1005" in str(e) or "closed" in str(e).lower():
                            print("WebSocket connection closed, will attempt to reconnect...")
                            self.kernel_ws = None
                            break
                        elif "timeout" in str(e).lower():
                            print("WebSocket timeout, will attempt to reconnect...")
                            self.kernel_ws = None
                            break
                        await asyncio.sleep(0.1)
                        if not self.kernel_ws:
                            break
            except Exception as e:
                print(f"Fatal error in message listener: {e}")
                self.kernel_ws = None
            
            # Cancel the tasks
            consumer_task.cancel()
            ping_task_obj.cancel()
            try:
                await consumer_task
                await ping_task_obj
            except asyncio.CancelledError:
                pass
            
            # Wait before attempting reconnection
            await asyncio.sleep(2)
                
    async def listen_for_events_messages(self):
        retry_count = 0
        max_retries = 10
        
        while True:  # Outer loop for reconnection
            # If we've been trying to reconnect for too long, reset the connection
            if retry_count > 5:
                print("Too many reconnection attempts, resetting connection...")
                self.event_ws = None
                self.kernel_ws = None
                retry_count = 0
            if not self.event_ws:
                if retry_count >= max_retries:
                    print(f"Max retries ({max_retries}) reached for events WebSocket. Stopping reconnection attempts.")
                    break
                    
                print(f"Events WebSocket not connected, attempting to reconnect... (attempt {retry_count + 1}/{max_retries})")
                try:
                    await self.connect_to_jupyter()  # This will also reconnect events
                    retry_count = 0  # Reset retry count on successful connection
                except Exception as e:
                    retry_count += 1
                    print(f"Failed to reconnect events to Jupyter: {e}")
                    await asyncio.sleep(min(5 * retry_count, 30))  # Exponential backoff with max 30s
                    continue
            
            message_queue = asyncio.Queue()
            
            async def message_consumer():
                while True:
                    try:
                        message = await message_queue.get()
                        
                        # Check if message is binary or text
                        if isinstance(message, bytes):
                            print(f"Received binary events message, length: {len(message)}")
                            # Skip binary messages (likely WebSocket control frames)
                            message_queue.task_done()
                            continue
                        
                        # Try to parse as JSON
                        try:
                            msg = json.loads(message)
                            
                            # Log the event message type for debugging
                            event_type = msg.get('event_type', 'unknown')
                            print(f"Broadcasting event message: {event_type}")
                            
                            await self.broadcast({
                                'action': 'events',
                                'data': msg,
                            })
                            
                            # Store the message in response queue
                            await self.response_queue.put(msg)
                            
                        except json.JSONDecodeError as e:
                            print(f"Failed to parse events message as JSON: {e}")
                            print(f"Message content: {message[:200]}...")  # Show first 200 chars
                        except UnicodeDecodeError as e:
                            print(f"Unicode decode error in events: {e}")
                            print(f"Message type: {type(message)}, length: {len(message) if hasattr(message, '__len__') else 'unknown'}")
                        
                        message_queue.task_done()
                    except Exception as e:
                        print(f"Error processing events message: {e}")
                        import traceback
                        traceback.print_exc()
                        await asyncio.sleep(0.1)

            # Start the consumer task
            consumer_task = asyncio.create_task(message_consumer())
            
            # Start ping task to keep connection alive
            async def ping_task():
                while True:
                    try:
                        if self.event_ws and self.event_ws.open:
                            await self.event_ws.ping()
                        await asyncio.sleep(10)  # Ping every 10 seconds (more frequent)
                    except Exception as e:
                        print(f"Events ping failed: {e}")
                        break
            
            ping_task_obj = asyncio.create_task(ping_task())
            
            # Main message receiver loop
            try:
                while True:
                    try:
                        message = await self.event_ws.recv()
                        await message_queue.put(message)
                    except Exception as e:
                        print(f"Error receiving events message: {e}")
                        # Check if it's a connection close error
                        if "1005" in str(e) or "closed" in str(e).lower():
                            print("Events WebSocket connection closed, will attempt to reconnect...")
                            self.event_ws = None
                            break
                        await asyncio.sleep(0.1)
                        if not self.event_ws:
                            break
            except Exception as e:
                print(f"Fatal error in events listener: {e}")
                self.event_ws = None
            
            # Cancel the tasks
            consumer_task.cancel()
            ping_task_obj.cancel()
            try:
                await consumer_task
                await ping_task_obj
            except asyncio.CancelledError:
                pass
            
            # Wait before attempting reconnection
            await asyncio.sleep(2)

    async def send_execute_request(self, code, cell_id):
        if not self.kernel_ws:
            await self.connect_to_jupyter()
        
        msg_id = cell_id or uuid.uuid1().hex
        msg_type = 'execute_request'
        content = {
            'code': code,
            'silent': False,
            'store_history': True,
            'user_expressions': {},
            'allow_stdin': True,
            'stop_on_error': True
        }
        
        hdr = {
            'msg_id': msg_id,
            'username': 'user',
            'session': self.session,
            'date': datetime.datetime.now().isoformat(),
            'msg_type': msg_type,
            'version': '5.0'
        }
        
        msg = {
            'header': hdr,
            'parent_header': {},
            'metadata': {},
            'content': content
        }
        
        await self.kernel_ws.send(json.dumps(msg))
        return msg_id

    async def send_input_reply(self, parent_header, value):
        if not self.kernel_ws:
            return
        
        msg_type = 'input_reply'
        content = {'value': value}
        
        hdr = {
            'msg_id': uuid.uuid1().hex,
            'username': 'user',
            'session': self.session,
            'date': datetime.datetime.now().isoformat(),
            'msg_type': msg_type,
            'version': '5.0'
        }
        
        msg = {
            'header': hdr,
            'parent_header': parent_header,
            'metadata': {},
            'content': content
        }
        
        await self.kernel_ws.send(json.dumps(msg))
        
    async def send_comm_msg(self, comm_id, data):
        if not self.kernel_ws:
            return
        
        
#         {'buffers': [],
#  'channel': 'iopub',
#  'content': {'comm_id': 'bb6e1b195de34b029196f901f5e02d7f',
#              'data': {'buffer_paths': [],
#                       'state': {'_dom_classes': [],
#                                 '_model_module': '@jupyter-widgets/controls',
#                                 '_model_module_version': '2.0.0',
#                                 '_model_name': 'VBoxModel',
#                                 '_view_count': None,
#                                 '_view_module': '@jupyter-widgets/controls',
#                                 '_view_module_version': '2.0.0',
#                                 '_view_name': 'VBoxView',
#                                 'box_style': '',
#                                 'children': ['IPY_MODEL_f1107eef729e45708845195d5281adf9',
#                                              'IPY_MODEL_1862a436d8544f0492c7ee2c90774f24',
#                                              'IPY_MODEL_de531056b8194b9ea026ed0c82e15ceb',
#                                              'IPY_MODEL_1316f51c85c14244be74d454e06fccd6',
#                                              'IPY_MODEL_2c9b4272037447dda59cfca0d85f498e'],
#                                 'layout': 'IPY_MODEL_90e6a713474844fab98ae7cb88d1a00e',
#                                 'tabbable': None,
#                                 'tooltip': None}},
#              'target_module': None,
#              'target_name': 'jupyter.widget'},
#  'header': {'date': '2025-03-02T03:32:43.328438Z',
#             'msg_id': '53a8b12c-e11db8b7f8b847bec1cbd158_152927_39',
#             'msg_type': 'comm_open',
#             'session': '53a8b12c-e11db8b7f8b847bec1cbd158',
#             'username': 'bluestarburst',
#             'version': '5.3'},
#  'metadata': {'version': '2.1.0'},
#  'msg_id': '53a8b12c-e11db8b7f8b847bec1cbd158_152927_39',
#  'msg_type': 'comm_open',
#  'parent_header': {'date': '2025-03-01T21:32:42.251808-06:00',
#                    'msg_id': '656361',
#                    'msg_type': 'execute_request',
#                    'session': 'e727e6baf71611ef98bf00155d12dbef',
#                    'username': 'user',
#                    'version': '5.0'}}
        
        hdr = {
            'msg_id': uuid.uuid1().hex,
            'username': 'user',
            'session': self.session,
            'date': datetime.datetime.now().isoformat(),
            'msg_type': 'comm_msg',
            'version': '5.0'
        }
        
        msg = {
            'header': hdr,
            'parent_header': {},
            'metadata': {},
            'content': {'comm_id': comm_id, 'data': data},
            'channel': 'shell'
        }
        
        print("Sending comm message", msg)
        
        await self.kernel_ws.send(json.dumps(msg))

    async def worker(self):
        print("Worker started")
        while True:
            action = await self.action_queue.get()
            print("WORKER ACTION", action['action'])
            try:
                if action['action'] == 'kernel':
                    # Send kernel message to Jupyter server
                    if self.kernel_ws and self.kernel_ws.open:
                        await self.kernel_ws.send(action['data'])
                        try:
                            # Handle both string and dict data formats
                            if isinstance(action.get('data'), str):
                                # Parse string data to get message type
                                parsed_data = json.loads(action['data'])
                                msg_type = parsed_data.get('header', {}).get('msg_type', 'unknown')
                            else:
                                # Handle dict data format
                                msg_type = action.get('data', {}).get('header', {}).get('msg_type', 'unknown')
                            print(f"Sent kernel message to Jupyter: {msg_type}")
                        except Exception as e:
                            print(f"Error parsing kernel message in worker: {e}")
                            msg_type = 'unknown'
                    else:
                        print("Kernel WebSocket not connected, cannot send message")
                elif action['action'] == 'execute_code':
                    await self.broadcast({
                        'action': 'execution_partial',
                        'output': {
                            'output_type': 'stream',
                            'name': 'stdout',
                            'text': '',
                            'cell_id': action['cell_id']
                        }
                    })
                    await self.execute_code(action['code'], action['cell_id'])
                elif action['action'] == 'comm_msg':
                    await self.send_comm_msg(action['comm_id'], action['data'])

                elif action['action'] == 'kernel_message':
                    # Alternative kernel message format
                    if self.kernel_ws and self.kernel_ws.open:
                        await self.kernel_ws.send(action['data'])
                        try:
                            # Handle both string and dict data formats
                            if isinstance(action.get('data'), str):
                                # Parse string data to get message type
                                parsed_data = json.loads(action['data'])
                                msg_type = parsed_data.get('header', {}).get('msg_type', 'unknown')
                            else:
                                # Handle dict data format
                                msg_type = action.get('data', {}).get('header', {}).get('msg_type', 'unknown')
                            print(f"Sent kernel_message to Jupyter: {msg_type}")
                        except Exception as e:
                            print(f"Error parsing kernel_message in worker: {e}")
                            msg_type = 'unknown'
                    else:
                        print("Kernel WebSocket not connected, cannot send kernel_message")
                else:
                    print(f"Unknown worker action: {action['action']}")
            except Exception as e:
                print(f"Error in worker: {e}")
                import traceback
                traceback.print_exc()
            self.action_queue.task_done()
            await asyncio.sleep(0.1)

    async def restart_kernel(self):
        if self.kernel_ws:
            await self.kernel_ws.close()
        
        self.kernel_id = None
        self.kernel_ws = None
        await self.connect_to_jupyter()
        
        print("Restarted kernel")
        return "Kernel restarted"

    async def execute_code(self, code, cell_id, no_broadcast=False):
        print("Executing code")
        if not self.kernel_ws:
            await self.connect_to_jupyter()
        
        msg_id = await self.send_execute_request(code, cell_id)
        
        # Wait for execution to complete
        execution_count = None
        while True:
            if not self.response_queue.empty():
                msg = await self.response_queue.get()
                if (msg.get('parent_header', {}).get('msg_id') == msg_id and 
                    msg.get('msg_type') == 'execute_reply'):
                    execution_count = msg['content'].get('execution_count')
                    break
            await asyncio.sleep(0.1)
        
        if not no_broadcast:
            await self.broadcast({
                'action': 'execution_complete',
                'cell_id': cell_id,
                'execution_count': execution_count
            })
            
    async def sudo_http_request(self, url, method, body):
        try:
            # send the request
            token = os.environ.get('JUPYTER_TOKEN', 'test')
            headers = {'Authorization': f'Token {token}'}
            response = None
            
            if method == 'POST':
                response = requests.post("http://localhost:8888/" + url, headers=headers, data=json.dumps(body))
            elif method == 'GET':
                response = requests.get("http://localhost:8888/" + url, headers=headers)
            elif method == 'PUT':
                response = requests.put("http://localhost:8888/" + url, headers=headers, data=json.dumps(body))
            elif method == 'DELETE':
                response = requests.delete("http://localhost:8888/" + url, headers=headers)     
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            # print("Sudo HTTP response", response.status_code, response.text)
            
            return {
                'status': response.status_code,
                'data': response.text,
                'headers': dict(response.headers)
            }
        except Exception as e:
            print(f"Error in sudo_http_request: {e}")
            return {
                'status': 500,
                'data': f"Error: {str(e)}",
                'headers': {}
            }

    async def handle_client(self, offer):
        print("Handling client")
        
        pc = RTCPeerConnection(configuration=RTC_CONFIG)
        self.peer_connections.add(pc)
        client_id = id(pc)
        
        @pc.on("iceconnectionstatechange")
        async def on_ice_connection_state_change():
            print(f"ICE connection state is {pc.iceConnectionState}")
        
        @pc.on("datachannel")
        def on_datachannel(channel):
            self.data_channels[client_id] = channel
            print(f"Data channel added with ID: {client_id}")
            
            @channel.on("message")
            async def on_message(message):
                try:
                    data = json.loads(message)
                    
                    if data['action'] != 'canvas_data':
                      print(f"Received WebRTC message: {data['action']}")
                    
                    # Handle all message types bidirectionally
                    if data['action'] == 'start_kernel':
                        kernel_id = await self.connect_to_jupyter()
                        print(f"Started kernel with ID: {kernel_id}")
                        await self.broadcast({'action': 'kernel_started', 'kernel_id': kernel_id})
                    elif data['action'] == 'execute_code':
                        await self.action_queue.put(data)
                    elif data['action'] == 'restart_kernel':
                        asyncio.create_task(self.restart_kernel())
                        await self.broadcast({'action': 'kernel_restarted'})
                    elif data['action'] == 'canvas_data':
                        tmp = data['data']
                        tmp['id'] = str(client_id)
                        await self.broadcast({'action': 'canvas_data', 'data': tmp}, client_id)
                    elif data['action'] == 'input':
                        print("Received input", data['input'])
                        await self.input_queue.put(data['input'])
                    elif data['action'] == 'interrupt_kernel':
                        print("Interrupting kernel")
                        if self.request_input:
                            await self.input_queue.put('')
                        self.interrupt_flag = True
                    elif data['action'] == 'comm_msg':
                        print("Received comm message", data['comm_id'])
                        await self.action_queue.put(data)
                    elif data['action'] == 'sudo_http_request':
                        # body may not be present
                        body = data.get('body', {})
                        msg_id = data.get('msgId', 'sudo_http_response')  # Default fallback
                        print("Received sudo HTTP", data['url'], data['method'], body)
                        res = await self.sudo_http_request(data['url'], data['method'], body)
                        await self.broadcast({'action': msg_id, 'data': res})
                    elif data['action'] == 'kernel':
                        # Relay all kernel messages to Jupyter server
                        try:
                            # Handle both string and dict data formats
                            if isinstance(data.get('data'), str):
                                # Parse string data to get message type
                                parsed_data = json.loads(data['data'])
                                msg_type = parsed_data.get('header', {}).get('msg_type', 'unknown')
                            else:
                                # Handle dict data format
                                msg_type = data.get('data', {}).get('header', {}).get('msg_type', 'unknown')
                            print(f"Relaying kernel message to Jupyter: {msg_type}")
                        except Exception as e:
                            print(f"Error parsing kernel message: {e}")
                            msg_type = 'unknown'
                        
                        # Send the message directly to Jupyter using the same format as existing code
                        try:
                            if isinstance(data.get('data'), str):
                                # If it's already a JSON string, use it directly
                                message_data = data['data']
                            else:
                                # If it's a dict, convert to JSON string
                                message_data = json.dumps(data['data'])
                            
                            # Put the message in the queue for the worker to send
                            await self.action_queue.put({
                                'action': 'kernel',
                                'data': message_data
                            })
                            
                        except Exception as e:
                            print(f"Error formatting kernel message for Jupyter: {e}")
                            import traceback
                            traceback.print_exc()
                    elif data['action'] == 'kernel_message':
                        # Alternative kernel message format
                        try:
                            # Handle both string and dict data formats
                            if isinstance(data.get('data'), str):
                                # Parse string data to get message type
                                parsed_data = json.loads(data['data'])
                                msg_type = parsed_data.get('header', {}).get('msg_type', 'unknown')
                            else:
                                # Handle dict data format
                                msg_type = data.get('data', {}).get('header', {}).get('msg_type', 'unknown')
                            print(f"Relaying kernel_message to Jupyter: {msg_type}")
                        except Exception as e:
                            print(f"Error parsing kernel_message: {e}")
                            msg_type = 'unknown'
                        
                        # Send the message using the same format as existing code
                        try:
                            if isinstance(data.get('data'), str):
                                # If it's already a JSON string, use it directly
                                message_data = data['data']
                            else:
                                # If it's a dict, convert to JSON string
                                message_data = json.dumps(data['data'])
                            
                            await self.action_queue.put({'action': 'kernel', 'data': message_data})
                        except Exception as e:
                            print(f"Error formatting kernel_message for Jupyter: {e}")
                            import traceback
                            traceback.print_exc()
                    elif data['action'] == 'events':
                        # Handle events messages
                        try:
                            # Handle both string and dict data formats
                            if isinstance(data.get('data'), str):
                                # Parse string data to get event type
                                parsed_data = json.loads(data['data'])
                                event_type = parsed_data.get('event_type', 'unknown')
                            else:
                                # Handle dict data format
                                event_type = data.get('data', {}).get('event_type', 'unknown')
                            print(f"Received events message: {event_type}")
                        except Exception as e:
                            print(f"Error parsing events message: {e}")
                            event_type = 'unknown'
                        await self.broadcast({'action': 'events', 'data': data['data']})
                    elif data['action'] == 'ping':
                        # Handle ping messages
                        await self.broadcast({'action': 'pong', 'timestamp': data.get('timestamp')})
                    elif data['action'] == 'status':
                        # Handle status messages
                        await self.broadcast({'action': 'status', 'data': data.get('data')})
                    else:
                        # Relay unknown messages to all clients (for debugging)
                        print(f"Unknown action: {data['action']}, relaying to all clients")
                        await self.broadcast(data)
                except Exception as e:
                    print(f"Error handling message: {e}")
                    import traceback
                    traceback.print_exc()

            @channel.on("close")
            def on_close():
                print(f"Client disconnected with ID: {client_id}")
                self.data_channels.pop(client_id)
                if pc in self.peer_connections:
                    self.peer_connections.remove(pc)
                asyncio.create_task(
                    self.broadcast(
                        {'action': 'canvas_data', 'data': {'type': 'disconnect', 'id': str(client_id)}},
                        client_id
                    )
                )
                
        @pc.on("icecandidate")
        async def on_ice_candidate(candidate):
            await self.broadcast({'action': 'ice_candidate', 'candidate': candidate}, client_id)
            
        @pc.on("icegatheringstatechange")
        async def on_ice_gathering_state_change():
            print(f"ICE gathering state is {pc.iceGatheringState}")
            
        @pc.on("signalingstatechange")
        async def on_signaling_state_change():
            print(f"Signaling state is {pc.signalingState}")
            
        @pc.on("connectionstatechange")
        async def on_connection_state_change():
            print(f"Connection state is {pc.connectionState}")
            
        @pc.on("negotiationneeded")
        async def on_negotiation_needed():
            print("Negotiation needed")

        # Set the remote description from the offer
        await pc.setRemoteDescription(RTCSessionDescription(
            sdp=offer["sdp"],
            type=offer["type"]
        ))

        # Create and set local description
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

    async def broadcast(self, message, client_id=None):
        async def async_send(channel, message):
            channel.send(message)
        
        if self.data_channels:
            message_str = json.dumps(message)
            tasks = [
                async_send(channel, message_str)
                for channel_id, channel in self.data_channels.items() if channel_id != client_id
            ]
            if tasks:
                await asyncio.gather(*tasks)


async def main():
    from aiohttp import web
    
    server = JupyterWebRTCServer()
    
    async def handle_offer(request):
        params = await request.json()
        response = await server.handle_client(params)
        return web.Response(
            content_type="application/json",
            text=json.dumps(response)
        )
    
    app = web.Application()
    app.router.add_post("/offer", handle_offer)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get('VAST_TCP_PORT_70000', 8765)))
    
    print(f"Server started at http://0.0.0.0:{os.environ.get('VAST_TCP_PORT_70000', 8765)}")
    await site.start()
    await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())