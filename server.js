// create an http websocket server
const http = require('http');
const WebSocket = require('ws');
const server = http.createServer();
const wss = new WebSocket.Server({ server });

wss.on('connection', function connection(ws) {
  ws.on('message', function incoming(message) {
    console.log('received: %s', message);
  });

  setTimeout(() => {
    var data = { type: 'runCell' };
    ws.send(JSON.stringify(data));
  }, 2000);
});

server.listen(3000, function listening() {
  console.log('Listening on %d', server.address().port);
});
