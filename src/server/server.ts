import { WebSocket, WebSocketServer } from 'ws';

const clients: WebSocket[] = [];
const jupyter: WebSocket[] = [];

const wss = new WebSocketServer({ port: 5000 });

wss.on('connection', (ws: WebSocket) => {
  ws.onopen = () => {
    console.log('WebSocket opened');
    // ws.send(JSON.stringify({ type: 'jupyter', data: '' }));
  };

  ws.onmessage = message => {
    // console.log('Message from server ', message);
    const data = JSON.parse(message.data.toString());
    console.log(data);
    switch (data.type) {
      case 'client':
        console.log('Running cell ' + data.data);
        clients.push(ws);
        break;
      case 'jupyter':
        console.log('Setting notebook');
        jupyter.push(ws);
        break;
      case 'setNotebook':
        for (const jup of jupyter) {
          jup.send(JSON.stringify({ type: 'setNotebook', data: data.data }));
        }
        break;
      case 'runCell':
        for (const jup of jupyter) {
          jup.send(JSON.stringify({ type: 'runCell', data: data.data }));
        }
        break;
      default:
        console.log('Unknown message');
    }
  };

  ws.on('close', () => {
    console.log('WebSocket closed');
    ws.close();
  });

  ws.on('error', e => {
    console.log('WebSocket error');
    console.log(e);
  });
});
