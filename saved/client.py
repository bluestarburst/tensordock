import asyncio
import websockets
import json


async def jupyter_client():
    uri = "ws://localhost:8765"
    async with websockets.connect(uri) as websocket:
        # Start a new kernel
        await websocket.send(json.dumps({"action": "start_kernel"}))
        response = await websocket.recv()
        kernel_info = json.loads(response)
        kernel_id = kernel_info['kernel_id']
        print(f"Started kernel with ID: {kernel_id}")

        # Execute "Hello, World!" code
        code = f'''
        
        %ls
        
        import time

        for i in range(10):

	print(i)

	time.sleep(1)
        '''
        await websocket.send(json.dumps({
            "action": "execute_code",
            "code": code
        }))

        #
        # response = await websocket.recv()
        # result = json.loads(response)
        # print("Execution result:")
        # for output in result['result']['outputs']:
        #     if output['output_type'] == 'stream':
        #         print(output['text'].strip())
        #     elif output['output_type'] == 'execute_result':
        #         print(output['data'].get('text/plain', ''))
        #     elif output['output_type'] == 'error':
        #         print(f"Error: {output['ename']}: {output['evalue']}")
        #         print("\n".join(output['traceback']))
        
        # print the partial (execution_partial) output as it comes then print the final output (execution_result) when it's done executing
        while True:
            response = await websocket.recv()
            result = json.loads(response)
            if result['action'] == 'execution_partial':
                output = result['output']
                
                if 'output_type' not in output:
                    continue
                
                if output['output_type'] == 'stream':
                    print(output['text'].strip())
                elif output['output_type'] == 'execute_result':
                    print(output['data'].get('text/plain', ''))
                elif output['output_type'] == 'error':
                    print(f"Error: {output['ename']}: {output['evalue']}")
                    print("\n".join(output['traceback']))
            elif result['action'] == 'execution_result':
                result = result['result']
                print("\nExecution result:")
                for output in result['outputs']:
                    if output['output_type'] == 'stream':
                        print(output['text'].strip())
                    elif output['output_type'] == 'execute_result':
                        print(output['data'].get('text/plain', ''))
                    elif output['output_type'] == 'error':
                        print(f"Error: {output['ename']}: {output['evalue']}")
                        print("\n".join(output['traceback']))
                break

asyncio.get_event_loop().run_until_complete(jupyter_client())