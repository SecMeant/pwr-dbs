#!/usr/bin/env python3
from flask import Flask, request, send_from_directory
from flask_uwsgi_websocket import GeventWebSocket

import sys
import threading 
import queue
import struct

import time

import delegate_pb2
from localstorage import *

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
websocket = GeventWebSocket(app)

class Worker:
  def __init__(self):
    self.work_queue = queue.Queue()

  def __enter__(self):
    print(f'New Worker@{id(self):x}')
    internal_register_worker(self)
    return self

  def __exit__(self, exception_type, exception_value, traceback):
    print(f'Destroying Worker@{id(self):x}')
    internal_unregister_worker(self)

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
    <input type="text" id="url" name="url", value="https://github.com/secmeant/pwr-sdizo"><br>
    <label for="rev">Commit:</label>
    <input type="text" id="rev" name="rev" value="e17d3526a4627d34764f82467484d6dc428b7b1c"><br>
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

@app.route("/")
def root():
  return index

@app.route("/favicon.ico")
def favicon():
  return send_from_directory(app.root_path, 'dbs.ico', mimetype='image/vnd.microsoft.icon')

@app.route("/index.js")
def js():
  return indexjs

def html_gen_button(text, url, fields = {}):
  button = f'<form method="get" action="{url}">'
  for field in fields:
    button += f'<input type="hidden" name="{field}" value="{fields[field]}">'
  button += f'<button type="submit">{text}</button></form>'

  return button

@app.route("/add")
def add_item():
  global projects
  url = request.args.get('url')
  rev = request.args.get('rev')

  if (url):
    p = ProjectInfo(url,rev)
    if not p in projects:
      if project_init(p):
        projects.append(p)

  site = '<h1>Projects</h1><h4><a href="/">/</a></h4>'
  for p in projects:
    site += f'{p.url}@{p.rev}</br>'
    site += '</br>'.join(p.files)
    site += html_gen_button('Clone', '/clone/', {'url':f'{url}'})
    site += '</br>'*3

  return site

@app.route("/clone/<repo>")
@app.route("/clone/", defaults={'repo':''})
def request_clone(repo):
  global projects

  if not repo:
    repo = request.args.get('url')

  pinfo = None

  if repo:
    for p in projects:
      if p.url.endswith(repo):
        pinfo = p
        break

  if pinfo is None:
    return 'No such project'

  project = Project(pinfo.to_protobf(), pinfo.files)

  workers_lock.acquire()

  if not workers:
    workers_lock.release()
    return 'No workers available'

  for worker in workers:
    worker.assign_work(project)

  workers_lock.release()

  return 'Work started'

@websocket.route('/ws')
def handle_node_register(ws):
  req = delegate_pb2.RegisterNodeRequest()
  msg = ws_read_any(ws)
  req.ParseFromString(msg)
  print('Request:\n\tVersion: {}\n'.format(req.version))

  resp = delegate_pb2.RegisterNodeResponse()
  resp.code = 0
  ws.send(resp.SerializeToString())

  with Worker() as this_worker:
    while True:
      project = this_worker.wait_for_work()

      req = project.bootstrap_info
      ws.send(req.SerializeToString())

      resp = delegate_pb2.BootstrapResponse()
      msg = ws_read_any(ws)
      resp.ParseFromString(msg)
      print(f'Data: {msg} Status: {resp.code}\n')

      if resp.code != 0:
        print(f'Bootstraping failed with {resp.code}, going back to waiting for project.')
        continue

      while True:
        file = project.get_file()

        # Project is done.
        if not file:
          print('No more files to compile for the project, going back to waiting for project')
          break

        # TODO this is slow
        if not file.endswith('.o'):
          file += '.o'

        compile_request = delegate_pb2.CompileRequest()
        compile_request.files = file
        ws.send(compile_request.SerializeToString())
        print(f'Sending compilation request, files: {file}')

        msg = b''

        resp = delegate_pb2.CompileResponse()
        msg = ws_read_any(ws)
        resp.ParseFromString(msg)
        print(f'msg: {msg}, File: {resp.file}, error: {resp.error}, data: {resp.data}\n')
        project.add_object(resp.data)

def restore():
  global projects
  print('Restoring saved data')
  try:
    with open(save_fn, 'r') as f:
      projects = f.readlines()
  except FileNotFoundError:
    print('Could not find data file.')
    return
  print('Restored')

def safe_exit():
  global projects
  with open(save_fn, 'w') as f:
    f.write('\n'.join(projects))

if __name__ == '__main__':
  try:
    #restore()
    app.run(gevent=100)
    #http_server = WSGIServer(('localhost', 5000), app, handler_class=WebSocketHandler)
    #http_server.serve_forever()
  except KeyboardInterrupt:
    #safe_exit()
    sys.exit()
