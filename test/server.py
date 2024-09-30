import asyncio
import websockets
import json
from jupyter_client import KernelManager
from jupyter_client.multikernelmanager import MultiKernelManager
import threading
import time


class JupyterWebSocketServer:
    def __init__(self):
        self.kernel_manager = KernelManager()
        self.clients = set()
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
        
        # start worker thread
        asyncio.create_task(self.worker())
        
        # # start kernel checker
        threading.Thread(target=self.check_kernel, daemon=True).start()
        
    def check_kernel(self):
        while True:
            # self.is_working = not self.is_working
            
            # print("Checking kernel state", self.is_working, self.kernel_state)
            if self.is_working and self.kernel_state == 'idle':
                time.sleep(5)
                if self.is_working and self.kernel_state == 'idle':
                    print("Kernel might be stuck!!!")
                    # interrupt the worker thread
                    # self.worker_thread.interrupt()
            
            time.sleep(1)
        
    async def worker(self):
        print("Worker started")
        while True:
            action = await self.action_queue.get()
            if action['action'] == 'execute_code':
                # await self.execute_code(action['code'], action['cell_id'])
                await self.broadcast({'action': 'execution_partial', 'output': {
                    'output_type': 'stream',
                    'name': 'stdout',
                    'text': '',
                    'cell_id': action['cell_id']
                }})
                await self.execute_code(action['code'], action['cell_id'])
                                
            self.action_queue.task_done()        
    

    async def handle_client(self, websocket, path):
        self.clients.add(websocket)
        client_id = id(websocket)
        print(f"New client connected with ID: {client_id}")
        try:
            async for message in websocket:
                data = json.loads(message)
                if data['action'] == 'start_kernel':
                    kernel_id = self.kernel_manager.start_kernel()
                    print(f"Started kernel with ID: {kernel_id}")
                    await self.broadcast({'action': 'kernel_started', 'kernel_id': kernel_id})
                elif data['action'] == 'execute_code':
                    # kernel_id = data['kernel_id']
                    # code = data['code']
                    # cell_id = data['cell_id']
                    # result = await self.execute_code(code, cell_id)
                    # await self.broadcast({'action': 'execution_result', 'result': result})
                    await self.action_queue.put(data)
                
                elif data['action'] == 'restart_kernel':
                    self.kernel_manager.restart_kernel()
                    self.kernel_state = 'idle'
                    self.is_working = False
                    self.kc = self.kernel_manager.client()
                    self.kc.start_channels()
                    print("Restarted kernel")
                    await self.broadcast({'action': 'kernel_restarted'})
                elif data['action'] == 'canvas_data':
                    tmp = data['data']
                    tmp['id'] = str(client_id)
                    await self.broadcast({'action': 'canvas_data', 'data': tmp}, client_id)
                elif data['action'] == 'input':
                    print("Received input", data['input'])
                    await self.input_queue.put(data['input'])
                else:
                    print(f"Unknown action: {data['action']}")      
        finally:
            print(f"Client disconnected with ID: {client_id}")
            self.clients.remove(websocket)

    async def execute_code(self, code, cell_id):
        
        if self.is_working and self.kernel_state == 'idle':
            print("Kernel is stuck!!!")
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
        msg_id = self.kc.execute(code, allow_stdin=True)
        result = {'outputs': [], 'cell_id': cell_id}
        is_error = False
        

        print("Executing code")
        while True:
            try:
                print("Waiting for message")                
                msg = await asyncio.wait_for(self.kc._async_get_iopub_msg(), timeout=10)
                print("\n\n\nReceived message", msg)
                
                try:
                    stdin_msg = self.kc.stdin_channel.get_msg(timeout=0.1)
                    print("Stdin message", stdin_msg)
                    
                    if stdin_msg and stdin_msg['msg_type'] == 'input_request':
                        print("Input requested")
                        await self.broadcast({'action': 'request_input', 'prompt': stdin_msg['content']['prompt'], 'cell_id': cell_id})
                        print("Waiting for input")
                        self.kc.input(await self.input_queue.get())
                        while not self.input_queue.empty():
                            await self.input_queue.get()
                except asyncio.TimeoutError:
                    print("No input")    
                except Exception as e:
                    print("INPUT Error", e)
            
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
                    # broadcast to all clients
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
        if self.clients:
            await asyncio.gather(*[client.send(json.dumps(message)) for client in self.clients if id(client) != client_id])
            # await asyncio.gather(*[client.send(json.dumps(message)) for client in self.clients])


async def main():
    server = JupyterWebSocketServer()
    async with websockets.serve(server.handle_client, "localhost", 8765):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())