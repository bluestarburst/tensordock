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
        
        # # wait for 1 second
        time.sleep(5)
        # create a new kernel
        print("Creating new kernel")
        asyncio.create_task(self.connect_to_jupyter())

    def check_kernel(self):
        print("Kernel checker started")

    async def connect_to_jupyter(self):
        base_url = os.environ.get('JUPYTER_URL', 'http://localhost:8888')
        token = os.environ.get('JUPYTER_TOKEN', 'test')
        
        
        headers = {'Authorization': f'Token {token}'}
        
        # Create session
        url = f"{base_url}/api/sessions"
        response = requests.post(url, headers=headers, json={'name': 'python3', 'path': '/tmp/test.ipynb', 'type': 'notebook'})
        session_info = json.loads(response.text)
        self.session_id = session_info['id']
        
        # get kernel info
        url = f"{base_url}/api/kernels/{session_info['kernel']['id']}"
        response = requests.get(url, headers=headers)
        kernel_info = json.loads(response.text)
        self.kernel_id = kernel_info['id']
        
        # Connect to WebSocket
        ws_url = f"ws://{base_url.split('://')[-1]}/api/kernels/{self.kernel_id}/channels"
        self.kernel_ws = await connect(ws_url, extra_headers=headers)   
        
        # Start message listener
        asyncio.create_task(self.listen_for_messages())
        
        return self.session_id
    
    async def listen_for_messages(self):
        if not self.kernel_ws:
            print("WebSocket not connected")
            return
        
        message_queue = asyncio.Queue()
        
        async def message_consumer():
            while True:
                try:
                    message = await message_queue.get()
                    msg = json.loads(message)
                    
                    await self.broadcast({
                        'action': 'kernel',
                        'data': msg,
                    })
                    
                    # pprint(msg.get('msg_type'))
                    # pprint(msg.get('content'))
                    
                    # if msg.get('msg_type') == 'status':
                    #     if msg['content'].get('execution_state') == 'idle':
                    #         self.kernel_state = 'idle'
                    #     elif msg['content'].get('execution_state') == 'busy':
                    #         self.kernel_state = 'busy'
                    
                    # # Handle widget comm messages
                    # if msg.get('msg_type') == 'comm_open':
                    #     comm_id = msg['content'].get('comm_id')
                    #     if comm_id:
                    #         # Extract widget data from the message
                    #         widget_data = msg['content'].get('data', {})
                    #         state = widget_data.get('state', {})
                    #         model_module = state.get('_model_module')
                    #         model_name = state.get('_model_name')
                    #         view_module = state.get('_view_module')
                    #         view_name = state.get('_view_name')
                            
                    #         # Store widget state and model info
                    #         self.widget_states[comm_id] = {
                    #             'state': state,
                    #             'model': {
                    #                 'model_name': model_name,
                    #                 'model_module': model_module,
                    #                 'view_name': view_name,
                    #                 'view_module': view_module
                    #             },
                    #             'visible': True
                    #         }
                    
                    # elif msg.get('msg_type') == 'comm_msg':
                    #     comm_id = msg['content'].get('comm_id')
                    #     if comm_id in self.widget_states:
                    #         # Update widget state
                    #         new_state = msg['content'].get('data', {}).get('state', {})
                    #         self.widget_states[comm_id]['state'].update(new_state)
                    
                    # # Handle display data messages
                    # elif msg.get('msg_type') == 'display_data':
                    #     display_data = msg['content'].get('data', {})
                    #     cell_id = msg.get('parent_header', {}).get('msg_id', '')
                        
                    #     # Handle widget views
                    #     if 'application/vnd.jupyter.widget-view+json' in display_data:
                    #         widget_data = display_data['application/vnd.jupyter.widget-view+json']
                    #         model_id = widget_data['model_id']
                            
                    #         # Add widget to cell's output if it exists
                    #         if model_id in self.widget_states:
                    #             await self.broadcast({
                    #                 'action': 'kernel_message',
                    #                 'data': msg,
                    #                 'cell_id': cell_id,
                    #                 'widgets': {
                    #                     model_id: self.widget_states[model_id]
                    #                 }
                    #             })
                    #             continue

                    # # broadcast the message to all clients
                    # await self.broadcast({
                    #     'action': 'kernel_message',
                    #     'data': msg,
                    #     'cell_id': msg.get('parent_header', {}).get('msg_id', ''),
                    #     'widget_state': self.widget_states.get(msg['content'].get('comm_id')) if msg.get('msg_type') in ['comm_open', 'comm_msg'] else None
                    # })
                    
                    # if msg.get('msg_type') == 'input_request':
                    #     self.request_input = True
                        
                    #     # Wait for input from client
                    #     input_value = await self.input_queue.get()
                    #     await self.send_input_reply(msg.get('header', {}), input_value)
                    #     self.request_input = False
                    
                    # Store the message in response queue
                    await self.response_queue.put(msg)
                    
                    message_queue.task_done()
                except Exception as e:
                    print(f"Error processing message: {e}")
                    await asyncio.sleep(0.1)

        # Start the consumer task
        consumer_task = asyncio.create_task(message_consumer())
        
        # Main message receiver loop
        while True:
            try:
                message = await self.kernel_ws.recv()
                await message_queue.put(message)
            except Exception as e:
                print(f"Error receiving message: {e}")
                await asyncio.sleep(0.1)
                if not self.kernel_ws:
                    break

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
            'content': content,
            'channel': 'shell'
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
            'content': content,
            'channel': 'stdin'
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
            print("ACTION", action)
            try:
                if action['action'] == 'kernel':
                    await self.kernel_ws.send(action['data'])
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
            except Exception as e:
                print(f"Error in worker: {e}")
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
        # send the request
        token = os.environ.get('JUPYTER_TOKEN', 'test')
        headers = {'Authorization': f'Token {token}'}
        response = None
        if method == 'POST':
            response = requests.post("http://localhost:8888/" + url, headers=headers, data=body)
        elif method == 'GET':
            response = requests.get("http://localhost:8888/" + url, headers=headers)
        elif method == 'PUT':
            response = requests.put("http://localhost:8888/" + url, headers=headers, data=body)
        elif method == 'DELETE':
            response = requests.delete("http://localhost:8888/" + url, headers=headers)     
        
        return {
            'status': response.status_code,
            'data': response.text,
            'headers': dict(response.headers)
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
                
                data = json.loads(message)
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
                    print("Received sudo HTTP", data['url'], data['method'], body)
                    res = await self.sudo_http_request(data['url'], data['method'], body)
                    await self.broadcast({'action': 'sudo_http_response', 'data': res})
                elif data['action'] == 'kernel':
                    # send message to websocket
                    await self.action_queue.put(data)
                else:
                    print(f"Unknown action: {data['action']}")

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