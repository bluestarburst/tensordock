import asyncio
import websockets
import json
from jupyter_client import KernelManager
from jupyter_client.multikernelmanager import MultiKernelManager


class JupyterWebSocketServer:
    def __init__(self):
        self.kernel_manager = MultiKernelManager()
        # self.kernel_manager.start_kernel()
        self.clients = set()

    async def handle_client(self, websocket, path):
        self.clients.add(websocket)
        try:
            async for message in websocket:
                data = json.loads(message)
                if data['action'] == 'start_kernel':
                    kernel_id = self.kernel_manager.start_kernel()
                    print(f"Started kernel with ID: {kernel_id}")
                    await self.broadcast({'action': 'kernel_started', 'kernel_id': kernel_id})
                elif data['action'] == 'execute_code':
                    kernel_id = data['kernel_id']
                    code = data['code']
                    kernel = self.kernel_manager.get_kernel(kernel_id)
                    result = await self.execute_code(kernel, code)
                    await self.broadcast({'action': 'execution_result', 'kernel_id': kernel_id, 'result': result})
        finally:
            self.clients.remove(websocket)

    async def execute_code(self, kernel, code):
        client = kernel.client()
        msg_id = client.execute(code)
        result = {'outputs': []}

        while True:
            try:
                # msg = await asyncio.wait_for(client.get_iopub_msg(), timeout=10)
                # TypeError: object dict can't be used in 'await' expression
                msg = client.get_iopub_msg()
                
                print("\n\n\n", msg)
                
                
                if msg['parent_header'].get('msg_id') == msg_id:
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
                        await self.broadcast({'action': 'execution_partial', 'kernel_id': kernel.kernel_id, 'output': {
                            'output_type': 'stream',
                            'name': msg['content']['name'],
                            'text': msg['content']['text']
                        }})
                    elif msg['msg_type'] == 'error':
                        result['outputs'].append({
                            'output_type': 'error',
                            'ename': msg['content']['ename'],
                            'evalue': msg['content']['evalue'],
                            'traceback': msg['content']['traceback']
                        })
                    elif msg['msg_type'] == 'status' and msg['content']['execution_state'] == 'idle':
                        break
            except asyncio.TimeoutError:
                result['outputs'].append({
                    'output_type': 'error',
                    'ename': 'TimeoutError',
                    'evalue': 'Execution timed out',
                    'traceback': []
                })
                break

        return result

    async def broadcast(self, message):
        if self.clients:
            # await asyncio.wait([client.send(json.dumps(message)) for client in self.clients])
            # TypeError: Passing coroutines is forbidden, use tasks explicitly.
            await asyncio.gather(*[client.send(json.dumps(message)) for client in self.clients])


async def main():
    server = JupyterWebSocketServer()
    async with websockets.serve(server.handle_client, "localhost", 8765):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())