import subprocess
import os
import json
import threading

# Used to implement conv ProjectInfo -> protobf.
# Perhaps shouldnt be here.
import delegate_pb2

projects = []

class ProjectBuild:
  def __init__(self, binfo, files):
    self.lock = threading.Lock()
    self.bootstrap_info = binfo
    self.file_queue = files
    self.objects = {}

  def dequeue_file(self):
    self.lock.acquire()

    if self.file_queue:
      ret = self.file_queue.pop()
    else:
      ret = None

    self.lock.release()

    return ret

  def enqueue_file(self, filename):
    self.lock.acquire()
    self.file_queue.insert(0, filename)
    self.lock.release()

  def add_object(self, filename, obj):
    self.lock.acquire()
    self.objects[filename] = obj
    self.lock.release()

class ProjectInfo:
  def __init__(self, url, rev, opt = ''):
    self.url = url
    self.rev = rev
    self.opt = opt

    # Clones project and fills self.files
    project_init(self)

    self.buildinfo = ProjectBuild(self.to_protobf(), self.files[:])

  # Perhaps shpuld be implemented somewhere else
  def to_protobf(self):
    req = delegate_pb2.BootstrapRequest()
    req.url = self.url
    req.rev = self.rev
    req.opt = self.opt

    return req

def repo_ready(repo_dir):
  return os.path.isdir(repo_dir)

env = '/usr/bin/env'

def repo_clone(url, outdir, commit = None):
  global env

  if repo_ready(outdir):
    return True

  proc = subprocess.run([env, 'git', 'clone', url, outdir])

  if proc.returncode:
    return False

  return True
  if not commit:
    return True

  proc = subprocess.run([env, 'git', 'checkout', commit])

  if proc.returncode:
    return False

  return True

def cmake_configure_project(project_path, opt):
  global env

  current_path = os.getcwd()
  build_path = os.path.join(project_path, 'build')

  if not os.path.isdir(build_path):
    os.makedirs(build_path)

  try:
    os.chdir(build_path)
  except:
    return False

  argv = [env, 'cmake', '..', '-DCMAKE_EXPORT_COMPILE_COMMANDS=y']

  if opt:
    argv.append(opt)

  proc = subprocess.run(argv)

  if proc.returncode:
    os.chdir(current_path)
    return False

  os.chdir(current_path)
  return True

def url2repo_name(url):
  return os.path.basename(url)

def repo_outdir(repo_name, rev):
  return os.path.join(repo_name, rev)

def read_file(path):
  return open(path, 'r').read()

def remove_prefix(src, prefix):
  print(f"remove prefix {src} {prefix}")
  if src.startswith(prefix):
      return src[len(prefix):]
  return src

def extract_targets(compile_commands, prefix):
  return [remove_prefix(entry['file'], prefix) if prefix else entry['file'] for entry in compile_commands]

def project_init(project):
  url = project.url
  rev = project.rev
  opt = project.opt

  repo_name = url2repo_name(url)
  outdir = repo_outdir(repo_name, rev)

  if not repo_clone(url, outdir, rev):
    return False

  if not cmake_configure_project(outdir, opt):
    return False

  compile_commands = json.loads(read_file(os.path.join(outdir, 'build', 'compile_commands.json')))
  prefix = os.path.join(os.getcwd(), outdir, '')
  files = extract_targets(compile_commands, prefix)
  print(files)
  project.files = files

  return True

def save_to_file(filename):
  print('Saving to file')
  with open(filename, 'w') as f:
    for p in projects:
      pickle.dump(p, f)

def load_from_file(filename):
  try:
    f = open(filename, 'r')
  except FileNotFoundError as e:
    print('Could not find data file.')
    return

  try:
    while 1:
      projects.append(pickle.load(f))
  except EOFError as e:
    print(f'Restored {len(projects)} projects')


