import asyncio
import websockets
import json
from jupyter_client import KernelManager
from jupyter_client.multikernelmanager import MultiKernelManager
import threading
import time
from queue import Empty


class JupyterWebSocketServer:
    def __init__(self):
        self.kernel_manager = KernelManager()
        self.clients = set()
        self.kernel_manager.start_kernel()
        self.kc = self.kernel_manager.client()
        self.kc.start_channels()
        
        self.action_queue = asyncio.Queue()
        self.is_working = False
        self.kernel_state = 'idle'
        
        self.input_queue = asyncio.Queue()
        self.last_input = None
        
        self.interrupt_flag = False
        self.request_input = False
        self.current_cell_id = None
        
        # Start worker and message handling tasks
        asyncio.create_task(self.worker())
        asyncio.create_task(self.message_handler())
        
        # Start kernel checker
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
        finally:
            print(f"Client disconnected with ID: {client_id}")
            self.clients.remove(websocket)

    async def execute_code(self, code, cell_id):
        self.current_cell_id = cell_id
        await self.broadcast({'action': 'start_running_cell', 'cell_id': cell_id})
        
        if self.is_working and self.kernel_state == 'idle':
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

        while self.is_working:
            await asyncio.sleep(0.1)  # Allow other tasks to run

        await self.broadcast({'action': 'execution_result', 'result': result})
        return result

    async def message_handler(self):
        while True:
            await self.handle_iopub_messages()
            await self.handle_shell_messages()
            await self.handle_stdin_messages()
            await self.handle_control_messages()
            await asyncio.sleep(0.01)  # Small delay to prevent busy-waiting

    async def handle_iopub_messages(self):
        try:
            msg = self.kc.get_iopub_msg(timeout=0)
            if msg['msg_type'] == 'execute_result':
                await self.process_execute_result(msg)
            elif msg['msg_type'] == 'stream':
                await self.process_stream_output(msg)
            elif msg['msg_type'] == 'error':
                await self.process_error_output(msg)
            elif msg['msg_type'] == 'status':
                self.kernel_state = msg['content']['execution_state']
        except Empty:
            pass

    async def handle_shell_messages(self):
        try:
            msg = self.kc.get_shell_msg(timeout=0)
            print("Shell message:", msg)
            if msg['msg_type'] == 'execute_reply':
                self.is_working = False
                self.kernel_state = 'idle'
        except Empty:
            pass

    async def handle_stdin_messages(self):
        try:
            msg = self.kc.get_stdin_msg(timeout=0)
            if msg['msg_type'] == 'input_request':
                await self.process_input_request(msg)
        except Empty:
            pass

    async def handle_control_messages(self):
        try:
            msg = self.kc.get_control_msg(timeout=0)
            # Handle control messages if needed
        except Empty:
            pass

    async def process_execute_result(self, msg):
        result = {
            'output_type': 'execute_partial',
            'data': msg['content']['data'],
            'cell_id': self.current_cell_id
        }
        await self.broadcast({'action': 'execution_result', 'output': result})

    async def process_stream_output(self, msg):
        output = {
            'output_type': 'stream',
            'name': msg['content']['name'],
            'text': msg['content']['text'],
            'cell_id': self.current_cell_id
        }
        await self.broadcast({'action': 'execution_partial', 'output': output})

    async def process_error_output(self, msg):
        error = {
            'output_type': 'error',
            'ename': msg['content']['ename'],
            'evalue': msg['content']['evalue'],
            'traceback': msg['content']['traceback'],
            'cell_id': self.current_cell_id
        }
        await self.broadcast({'action': 'execution_partial', 'output': error})

    async def process_input_request(self, msg):
        self.request_input = True
        await self.broadcast({
            'action': 'request_input',
            'prompt': msg['content']['prompt'],
            'cell_id': msg['parent_header']['msg_id']
        })
        user_input = await self.input_queue.get()
        self.kc.input(user_input)
        self.request_input = False

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