import asyncio
import json
from jupyter_client import KernelManager
from jupyter_client.multikernelmanager import MultiKernelManager
import threading
import time
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel, RTCConfiguration, RTCIceServer
from aiortc.contrib.signaling import object_from_string, object_to_string
import os

print("bash test")

RTC_CONFIG = RTCConfiguration(iceServers=[
    RTCIceServer(urls=["stun:stun.l.google.com:19302"])
])

class JupyterWebRTCServer:
    def __init__(self):
        self.kernel_manager = KernelManager()
        self.peer_connections = set()
        self.data_channels = set()
        self.kernel_manager.start_kernel()
        self.kc = self.kernel_manager.client()
        self.kc.start_channels()
        
        asyncio.create_task(self.execute_code('print("Hello World!")', '1'))
        
        self.action_queue = asyncio.Queue()
        self.is_working = False
        self.kernel_state = 'idle'
        self.worker_thread = None
        
        self.input_queue = asyncio.Queue()
        self.last_input = None
        
        self.interrupt_flag = False
        self.request_input = False
        
        # start worker thread
        asyncio.create_task(self.worker())
        
        # start kernel checker
        threading.Thread(target=self.check_kernel, daemon=True).start()

    def check_kernel(self):
        while True:
            if self.is_working and self.kernel_state == 'idle':
                time.sleep(5)
                if self.is_working and self.kernel_state == 'idle':
                    stuck = True
                    print("Kernel might be stuck")
                    stuck = True
                    print("Kernel might be stuck")
            time.sleep(1)

    async def worker(self):
        print("Worker started")
        while True:
            action = await self.action_queue.get()
            if action['action'] == 'execute_code':
                await self.broadcast({'action': 'execution_partial', 'output': {
                    'output_type': 'stream',
                    'name': 'stdout',
                    'text': '',
                    'cell_id': action['cell_id']
                }})
                await self.execute_code(action['code'], action['cell_id'])
            self.action_queue.task_done()

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
            self.data_channels.add(channel)
            print(f"Data channel added with ID: {client_id}")
            
            @channel.on("message")
            async def on_message(message):
                
                data = json.loads(message)
                print(f"Received message: {data}")
                if data['action'] == 'start_kernel':
                    kernel_id = self.kernel_manager.start_kernel()
                    print(f"Started kernel with ID: {kernel_id}")
                    await self.broadcast({'action': 'kernel_started', 'kernel_id': kernel_id})
                elif data['action'] == 'execute_code':
                    await self.action_queue.put(data)
                elif data['action'] == 'restart_kernel':
                    self.kernel_manager.restart_kernel()
                    self.kernel_state = 'idle'
                    self.is_working = False
                    self.kc = self.kernel_manager.client()
                    self.kc.start_channels()
                    asyncio.create_task(self.execute_code('print("Hello World!")', '1'))
                    print("Restarted kernel")
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
                    self.kernel_manager.interrupt_kernel()
                    if self.request_input:
                        self.input_queue.put_nowait('')
                    self.interrupt_flag = True
                else:
                    print(f"Unknown action: {data['action']}")

            @channel.on("close")
            def on_close():
                print(f"Client disconnected with ID: {client_id}")
                self.data_channels.remove(channel)
                if pc in self.peer_connections:
                    self.peer_connections.remove(pc)
                asyncio.create_task(
                    self.broadcast(
                        {'action': 'canvas_data', 'data': {'type': 'disconnect', 'id': str(client_id)}},
                        client_id
                    )
                )

        # Set the remote description from the offer
        await pc.setRemoteDescription(RTCSessionDescription(
            sdp=offer["sdp"],
            type=offer["type"]
        ))

        # Create and set local description
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

    async def execute_code(self, code, cell_id):
        await self.broadcast({'action': 'start_running_cell', 'cell_id': cell_id})
        
        if self.is_working and self.kernel_state == 'idle':
            print(f"Kernel is stuck")
            await self.broadcast({'action': 'execution_result', 'result': {
                'outputs': [{
                    'output_type': 'error',
                    'ename': 'KernelStuckError',
                    'evalue': 'Kernel is stuck',
                    'traceback': []
                }],
                'cell_id': cell_id
            }})
            self.is_working = False
            self.kernel_state = 'idle'
            return
        
        self.is_working = True
        self.kc.execute(code, allow_stdin=True)
        result = {'outputs': [], 'cell_id': cell_id}

        print("Executing code")
        while True:
            try:
                await asyncio.sleep(0.1)
                
                msg = await asyncio.wait_for(self.kc._async_get_iopub_msg(), timeout=10)
                
                try:
                    stdin_msg = self.kc.stdin_channel.get_msg(timeout=0.1)
                    print("Stdin message", stdin_msg)
                    
                    if stdin_msg and stdin_msg['msg_type'] == 'input_request':
                        print("Input requested")
                        self.request_input = True
                        await self.broadcast({
                            'action': 'request_input',
                            'prompt': stdin_msg['content']['prompt'],
                            'cell_id': cell_id
                        })
                        print("Waiting for input")
                        self.kc.input(await self.input_queue.get())
                        while not self.input_queue.empty():
                            await self.input_queue.get()
                except asyncio.TimeoutError:
                    print("No input")    
                except Exception:
                    self.request_input = False
                
                self.request_input = False
            
                if msg['msg_type'] == 'execute_result':
                    result['outputs'].append({
                        'output_type': 'execute_result',
                        'data': msg['content']['data']
                    })
                elif msg['msg_type'] == 'stream':
                    result['outputs'].append({
                        'output_type': 'stream',
                        'name': msg['content']['name'],
                        'text': msg['content']['text']
                    })
                    await self.broadcast({'action': 'execution_partial', 'output': {
                        'output_type': 'stream',
                        'name': msg['content']['name'],
                        'text': msg['content']['text'],
                        'cell_id': cell_id
                    }})
                elif msg['msg_type'] == 'error':
                    print("Error\n", msg['content']['ename'], msg['content']['evalue'])
                    
                    result['outputs'].append({
                        'output_type': 'error',
                        'ename': msg['content']['ename'],
                        'evalue': msg['content']['evalue'],
                        'traceback': msg['content']['traceback']
                    })
                    
                    await self.broadcast({'action': 'execution_partial', 'output': {
                        'output_type': 'error',
                        'ename': msg['content']['ename'],
                        'evalue': msg['content']['evalue'],
                        'traceback': msg['content']['traceback'],
                        'cell_id': cell_id
                    }})
                    
                elif msg['msg_type'] == 'status' and msg['content']['execution_state'] == 'idle':
                    break
                    
                if 'content' in msg and 'execution_state' in msg['content'] and msg['content']['execution_state'] == 'idle':
                    print("Execution done")
                    break
            except asyncio.TimeoutError:
                print("Execution timed out")
                result['outputs'].append({
                    'output_type': 'error',
                    'ename': 'TimeoutError',
                    'evalue': 'Execution timed out',
                    'traceback': []
                })
                break
                
        print("Broadcasting execution result")
        await self.broadcast({'action': 'execution_result', 'result': result})

        self.is_working = False
        return result

    async def broadcast(self, message, client_id=None):
        
        async def async_send(channel, message):
            print(f"Sending {message} to {channel}")
            channel.send(message)
        
        if self.data_channels:
            message_str = json.dumps(message)
            tasks = [
                async_send(channel, message_str)
                for channel in self.data_channels
            ]
            if tasks:
                await asyncio.gather(*tasks)


async def main():
    from aiohttp import web
    
    server = JupyterWebRTCServer()
    
    async def handle_offer(request):
        params = await request.json() # the json is { "type": "offer", "offer": "<sdp>" }
        response = await server.handle_client(params)
        return web.Response(
            content_type="application/json",
            text=json.dumps(response)
        )
    
    app = web.Application()
    app.router.add_post("/offer", handle_offer)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv('SIGNAL', 8765)))
    
    print(f"Server started at http://0.0.0.0:{os.getenv('SIGNAL', 8765)}")
    await site.start()
    await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())