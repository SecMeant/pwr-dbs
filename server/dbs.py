#!/usr/bin/env python3
import sys
from geventwebsocket.handler import WebSocketHandler
from geventwebsocket.exceptions import WebSocketError
from gevent.pywsgi import WSGIServer
from flask import Flask, request, send_from_directory

from pathlib import Path

import delegate_pb2

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

index = """
<head>
  <script type="text/javascript" src="index.js"></script>
</head>
<body>
  <h1>asdf</h1>
</body>

"""

indexjs = """
function checkJS() {
  document.body.innerHTML = document.body.innerHTML + "</br>JS works</br>";
}

setTimeout(checkJS, 1000);

"""

items = []

@app.route("/")
def root():
  return index

@app.route("/favicon.ico")
def favicon():
  return send_from_directory(app.root_path, 'dbs.ico', mimetype='image/vnd.microsoft.icon')

@app.route("/index.js")
def js():
  return indexjs

@app.route("/add", defaults={'item': None})
@app.route("/add/<item>")
def add_item(item):
  if (item):
    items.append(item)
  return "<h1>Items</h1></br>" + "</br>".join(items)

@app.route('/ws')
def handle_ws():
  if request.environ.get('wsgi.websocket'):
    ws = request.environ['wsgi.websocket']
    message = ws.receive()

    req = delegate_pb2.RegisterNodeRequest()
    req.ParseFromString(message.encode('utf-8')) 
    print('Request:\n\tVersion: {}\n'.format(req.version))

    res = delegate_pb2.RegisterNodeResponse()
    res.code = 0
    ws.send(res.SerializeToString())

  return ''

save_fn = 'state'

def restore():
  global items
  print('Restoring saved data')
  try:
    with open(save_fn, 'r') as f:
      items = f.readlines()
  except FileNotFoundError:
    print('Could not find data file.')
    return
  print('Restored')

def safe_exit():
  global items
  with open(save_fn, 'w') as f:
    f.write('\n'.join(items))

if __name__ == '__main__':
  try:
    restore()
    http_server = WSGIServer(('localhost', 5000), app, handler_class=WebSocketHandler)
    http_server.serve_forever()
  except KeyboardInterrupt:
    safe_exit()
    sys.exit()
