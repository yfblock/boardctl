"""Command execution: per the board config's ssh_host, run locally or via
ssh on a remote host

- ssh_host empty: run with local /bin/sh -c, working directory = project
  root (relative paths like ./run.sh work)
- ssh_host set: ssh <host> <command>, interpreted by the remote shell;
  commands must carry their own paths (host alias/port/user go through
  ~/.ssh/config, e.g. myserver)
"""
import subprocess

from .config import BASE_DIR


def run(cfg, command, check=True, capture=False):
    host = cfg.ssh_host
    if host:
        argv = ['ssh', '-o', 'BatchMode=yes', host, command]
        cwd = None
    else:
        argv = ['/bin/sh', '-c', command]
        cwd = BASE_DIR
    return subprocess.run(argv, cwd=cwd, check=check,
                          capture_output=capture, text=True)
