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
        console.log('Setting client');
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
      case 'restartNotebook':
        for (const jup of jupyter) {
          jup.send(
            JSON.stringify({ type: 'restartNotebook', data: data.data })
          );
        }
        break;
      case 'runCell':
        for (const jup of jupyter) {
          jup.send(JSON.stringify({ type: 'runCell', data: data.data }));
        }
        break;
      case 'setOutput':
        for (const c of clients) {
          c.send(JSON.stringify({ type: 'setOutput', data: data.data }));
        }
        break;
      default:
        console.log('Unknown message');
    }
  };

  ws.on('close', () => {
    console.log('WebSocket closed');
    if (clients.includes(ws)) {
      clients.splice(clients.indexOf(ws), 1);
    } else if (jupyter.includes(ws)) {
      jupyter.splice(jupyter.indexOf(ws), 1);
    }
    ws.close();
  });

  ws.on('error', e => {
    console.log('WebSocket error');
    console.log(e);
  });
});
