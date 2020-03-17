import subprocess
import os

projects = []

class ProjectInfo:
  def __init__(self, url, rev):
    self.url = url
    self.rev = rev
    self.files = []

  def __eq__(self, other):
    return self.url == other.url and self.rev == other.rev

  def __ne__(self, other):
    return not self.__ne__(other)

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

  argv = [env, 'cmake', '..']

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

def project_init(url, rev, opt):
  repo_name = url2repo_name(url)
  outdir = repo_outdir(repo_name, rev)

  if not repo_clone(url, outdir, rev):
    return False

  if not cmake_configure_project(outdir, opt):
    return False

  return True


