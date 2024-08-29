import { WebSocket, WebSocketServer } from 'ws';

const clients: { [key: string]: WebSocket } = {};
const jupyter: WebSocket[] = [];

console.log('Starting server');

const wss = new WebSocketServer({ port: 5000 });

const createId = () => {
  let id = Math.random().toString(36).substring(7);
  while (clients[id]) {
    id = Math.random().toString(36).substring(7);
  }
  return id;
};

const findId = (ws: WebSocket) => {
  return Object.keys(clients).find(key => clients[key] === ws) ?? '-1';
};

wss.on('connection', (ws: WebSocket) => {
  ws.onopen = () => {
    console.log('WebSocket opened');
    // ws.send(JSON.stringify({ type: 'jupyter', data: '' }));
  };

  ws.onmessage = message => {
    // console.log('Message from server ', message);
    const data = JSON.parse(message.data.toString());
    console.log(data);

    const id = findId(ws);

    switch (data.type) {
      case 'canvasData':
        for (const c of Object.values(clients)) {
          c.send(
            JSON.stringify({ type: 'canvasData', data: { ...data.data, id } })
          );
        }
        break;
      case 'client':
        console.log('Setting client');
        clients[createId()] = ws;
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
      case 'setPartial':
      case 'setOutput':
        for (const c of Object.values(clients)) {
          c.send(JSON.stringify({ type: data.type, data: data.data }));
        }
        break;
      default:
        console.log('Unknown message');
    }
  };

  ws.on('close', () => {
    console.log('WebSocket closed');
    if (
      Object.values(clients).includes(ws) &&
      Object.keys(clients).find(key => clients[key] === ws)
    ) {
      delete clients[Object.keys(clients).find(key => clients[key] === ws)!];
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
