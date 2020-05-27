#!/usr/bin/env python3
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from flask_uwsgi_websocket import GeventWebSocket

import sys
import threading 
import queue
import struct

import time

import delegate_pb2
import localstorage

from urllib.parse import quote_plus

app = Flask(__name__, template_folder='templates')
app.jinja_env.filters['quote_plus'] = lambda u: quote_plus(u)
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

save_fn = 'state'

@app.route("/")
def root():
  return render_template('index.html', url='https://github.com/secmeant/pwr-sdizo', rev='e17d3526a4627d34764f82467484d6dc428b7b1c')

@app.route("/favicon.ico")
def favicon():
  return send_from_directory(app.root_path, 'dbs.ico', mimetype='image/vnd.microsoft.icon')

@app.route("/add")
def add_item():
  url = request.args.get('url')
  rev = request.args.get('rev')

  if (url):
    repo = find_repo(url, rev)
    if repo == None:
      localstorage.projects.append(localstorage.ProjectInfo(url,rev))

  return render_template('add.html', projects=localstorage.projects)

@app.route("/clone/<url>")
@app.route("/clone/", defaults={'url':''})
def request_clone(url):
  if not url:
    url = request.args.get('url')

  pinfo = find_repo(url)

  if pinfo is None:
    return render_template('centertext.html', text='404 Not found')

  workers_lock.acquire()

  if not workers:
    workers_lock.release()
    return render_template('centertext.html', text='No workers available')

  for worker in workers:
    worker.assign_work(pinfo.buildinfo)

  workers_lock.release()

  return render_template('work.html', project_name=pinfo.url)

def find_repo(url, rev=None):
  if url.startswith('https://') or url.startswith('git://'):
    for p in localstorage.projects:
      if p.url == url:
        if rev == None or rev == p.rev:
          return p
  else:
    url = '/' + url
    for p in localstorage.projects:
      if p.url.endswith(url):
        if rev == None or rev == p.rev:
          return p

  return None

@app.route("/status/<url>")
@app.route("/status/", defaults={'url':''})
def request_status(url):
  if not url:
    url = request.args.get('url')

  p = find_repo(url)
  if not p:
    return ''

  return f'{len(p.buildinfo.objects)} {len(p.files)}'

@app.route("/remove/<url>")
@app.route("/remove/", defaults={'url':''})
def request_remove(url):
  if not url:
    url = request.args.get('url')

  p = find_repo(url)
  if p:
    localstorage.projects.remove(p)

  return redirect('/add')

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
      print(f'Worker@{id(this_worker):x} is waiting for project...')
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
        file = project.dequeue_file()

        # Project is done.
        if not file:
          print('No more files to compile for the project, going back to waiting for project')
          compile_request = delegate_pb2.CompileRequest()
          compile_request.files = ''
          ws.send(compile_request.SerializeToString())
          break

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
        print(f'File: {resp.file}, error: {resp.error}, data: {resp.data}\n')

        if len(resp.data) == 0:
          print(f'Failed to compile {resp.file} with error: {resp.error}.')
          project.enqueue_file(file)
        else:
          project.add_object(resp.file, resp.data)

if __name__ == '__main__':
  try:
    localstorage.load_from_file(save_fn)
    app.run(gevent=100)
    #http_server = WSGIServer(('localhost', 5000), app, handler_class=WebSocketHandler)
    #http_server.serve_forever()
  except KeyboardInterrupt:
    localstorage.save_to_file(save_fn)
    sys.exit()
