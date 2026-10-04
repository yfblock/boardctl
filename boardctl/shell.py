"""Command domain: run per cfg.ssh_host — empty: local /bin/sh -c, cwd =
BASE_DIR (relative paths work); set: ssh <host> <command>, interpreted by
the remote shell (alias/port/user go through ~/.ssh/config)."""
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
