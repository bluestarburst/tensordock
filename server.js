// create an http websocket server
const http = require('http');
const WebSocket = require('ws');
const server = http.createServer();
const wss = new WebSocket.Server({ server });

// mesage types: ['runCell,int', 'setNotebook:json']

const fs = require('fs');
var notebook = null;
fs.readFile('./notebook.ipynb', 'utf8', (error, data) => {
  if (error) {
    console.log(error);
    return;
  }
  notebook = data;
});

client = null;
jupyter = null;
wss.on('connection', function connection(ws) {
  ws.on('message', function incoming(message) {
    console.log('received: %s', message);
    const data = JSON.parse(message);
    var sendData = null;
    switch (data.type) {
      case 'client':
        client = ws;
        break;
      case 'jupyter':
        jupyter = ws;
        break;
      case 'setNotebook':
        sendData = { type: 'setNotebook', data: data.data };
        jupyter.send(JSON.stringify(sendData));
        break;
      case 'setOutput':
        sendData = { type: 'setOutput', data: data.data };
        client.send(JSON.stringify(sendData));
        break;
      case 'runCell':
        sendData = { type: 'runCell', data: data.data };
        jupyter.send(JSON.stringify(sendData));
      default:
        break;
    }
  });

  setTimeout(() => {
    // data = { type: 'setNotebook', data: notebook };
    // ws.send(JSON.stringify(data));
    // var data = { type: 'runCell', data: 1 };
    // ws.send(JSON.stringify(data));
    // data = { type: 'runCell', data: 0 };
    // ws.send(JSON.stringify(data));
  }, 2000);
});

server.listen(3000, function listening() {
  console.log('Listening on %d', server.address().port);
});
