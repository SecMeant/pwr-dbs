#!/usr/bin/env python3
from flask import Flask, request, send_from_directory
from flask_uwsgi_websocket import GeventWebSocket

import sys
import threading 
import queue
import struct

from pathlib import Path

import delegate_pb2

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
websocket = GeventWebSocket(app)

class Worker:
  def __init__(self):
    self.work_queue = queue.Queue()

  def wait_for_work(self):
    return self.work_queue.get()

  def assign_work(self, project):
    self.work_queue.put(project)

class Project:
  def __init__(self, binfo, files):
    self.lock = threading.Lock()
    self.bootstrap_info = binfo
    self.files = files
    self.objects = []

  def get_file(self):
    self.lock.acquire()

    if self.files:
      ret = self.files.pop()
    else:
      ret = None

    self.lock.release()

    return ret

  def add_object(self, obj):
    self.lock.acquire()
    self.objects.append(obj)
    self.lock.release()

class ProjectQueue:
  def __init__(self):
    self.lock = threading.Lock()
    self.projects = []

  def enqueue_project(project):
    self.lock.acquire()
    self.projects.append(project)
    self.lock.release()

workers_lock = threading.Lock()
workers = []

def internal_register_worker(worker):
  workers_lock.acquire()
  workers.append(worker)
  workers_lock.release()

def internal_unregister_worker(worker):
  workers_lock.acquire()
  workers.remove(worker)
  workers_lock.release()

def ws_read_any(ws):
  while True:
    msg = ws.recv()
    if msg:
      return msg

def ws_read_n(ws, size):
  message = b''
  while len(message) < size:
    msg = ws.recv()
    if msg:
      message += msg
  return message

def ws_recv_protobuf(ws):
  size = struct.unpack("<I", ws_read_n(ws, 4))
  return ws_read_n(ws, size)

index = """
<head>
  <script type="text/javascript" src="index.js"></script>
</head>
<body>
  <h1>asdf</h1>
  <form action="/add">
    <label for="url">URL:</label>
    <input type="text" id="url" name="url"><br>
    <label for="rev">Commit:</label>
    <input type="text" id="rev" name="rev"><br>
    <input type="submit" value="Submit">
  </form>
</body>

"""

indexjs = """
function checkJS() {
  document.body.innerHTML = document.body.innerHTML + "</br>JS works</br>";
}

setTimeout(checkJS, 1000);

"""

save_fn = 'state'
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

@app.route("/add")
def add_item():
  global items
  url = request.args.get('url')
  rev = request.args.get('rev')
  if (url):
    item = f'{url}@{rev}'
    if not item in items:
      items.append(item)
  return "<h1>Items</h1></br>" + "</br>".join(items)

@app.route("/clone/<repo>")
def request_clone(repo):
  req = delegate_pb2.BootstrapRequest()
  req.url = 'https://github.com/secmeant/sets'
  req.rev = '6784848e4ed40a42b9016654330c3d0edc4bbdfc'
  req.opt = ''

  project = Project(req, ['asdf.cc'])

  workers_lock.acquire()

  if not workers:
    return 'No workers available'

  workers[0].assign_work(project)

  workers_lock.release()

  return 'Work started'

import time

@websocket.route('/ws')
def handle_node_register(ws):
  req = delegate_pb2.RegisterNodeRequest()
  msg = ws_read_any(ws)
  req.ParseFromString(msg)
  print('Request:\n\tVersion: {}\n'.format(req.version))

  resp = delegate_pb2.RegisterNodeResponse()
  resp.code = 0
  ws.send(resp.SerializeToString())

  local_worker = Worker()
  internal_register_worker(local_worker)
  project = local_worker.wait_for_work()

  #req = delegate_pb2.BootstrapRequest()
  #req.url = 'https://github.com/secmeant/sets'
  #req.rev = '6784848e4ed40a42b9016654330c3d0edc4bbdfc'
  #req.opt = ''

  req = project.bootstrap_info
  ws.send(req.SerializeToString())

  resp = delegate_pb2.BootstrapResponse()
  msg = ws_read_any(ws)
  resp.ParseFromString(msg)
  print(f'Data: {msg} Status: {resp.code}\n')

  file = project.get_file()
  compile_request = delegate_pb2.CompileRequest()
  compile_request.files = file
  ws.send(compile_request.SerializeToString())

  msg = b''

  resp = delegate_pb2.CompileResponse()
  msg = ws_read_any(ws)
  resp.ParseFromString(msg)
  print(f'msg: {msg}, File: {resp.file}, error: {resp.error}, data: {resp.data}\n')

  internal_unregister_worker(local_worker)
  return ''

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
    app.run(gevent=100)
    #http_server = WSGIServer(('localhost', 5000), app, handler_class=WebSocketHandler)
    #http_server.serve_forever()
  except KeyboardInterrupt:
    safe_exit()
    sys.exit()
