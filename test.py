import json
import requests
import datetime
import uuid
from pprint import pprint
from websocket import create_connection
from time import sleep

# https://jupyter-client.readthedocs.io/en/latest/messaging.html

# The token is written on stdout when you start the notebook
base = 'http://localhost:8888'
headers = {'Authorization': 'Token test'}


url = base + '/api/kernels'
response = requests.post(url,headers=headers)
kernel = json.loads(response.text)

# Execution request/reply is done on websockets channels
ws = create_connection("ws://localhost:8888/api/kernels/"+kernel["id"]+"/channels",
     header=headers)

session = uuid.uuid1().hex

def send_execute_request(code):
    msg_type = 'execute_request'
    content = { 'code' : code, 'silent':False, 'allow_stdin':True, 'store_history':True }
    hdr = { 'msg_id' : uuid.uuid1().hex, 
        'username': 'test', 
        'session': session, 
        'data': datetime.datetime.now().isoformat(),
        'msg_type': msg_type,
        'version' : '5.0' }
    msg = { 'header': hdr, 'parent_header': hdr, 
        'metadata': {},
        'content': content }
    return msg

def send_input_reply(parent_hdr, value):
    
    msg_type = 'input_reply'
    content = { 'value' : value }
    hdr = { 'msg_id' : uuid.uuid1().hex, 
        'username': 'test', 
        'session': session, 
        'data': datetime.datetime.now().isoformat(),
        'msg_type': msg_type,
        'version' : '5.0' }
    msg = { 'header': hdr, 'parent_header': parent_hdr, 
        'metadata': {},
        'content': content,
        'channel': 'stdin' }
    return msg

# create an asyncronous thread for receiving messages

working = True

def receive():
    
    while True:
        msg = ws.recv()
        msg = json.loads(msg)
        print("\n\n\n\n\n\n\n\n")
        pprint(msg)
        
        if msg['msg_type'] == 'status':
            pprint("status")
        elif msg['msg_type'] == 'input_request':
            pprint("input_request")
            # send a temporary response
            ws.send(json.dumps(send_input_reply(msg['parent_header'], "hello")))
        else:
            print("other")
            
import threading
t = threading.Thread(target=receive)
t.start()

# Send a request to execute code
msg = send_execute_request('tmp = input("Enter something: ")')
ws.send(json.dumps(msg))
sleep(4)

msg = send_execute_request('print(tmp)')
ws.send(json.dumps(msg))

# Wait for the thread to finish

t.join()

# Close the websocket
ws.close()
