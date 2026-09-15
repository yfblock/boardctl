"""命令执行:按板卡配置 ssh_host 决定在本机还是经 ssh 在远端主机执行

- ssh_host 为空:本机 /bin/sh -c 执行,工作目录 = 项目根(./run.sh 这类相对路径可用)
- ssh_host 非空:ssh <host> <command>,由远端 shell 解释;命令需自含路径
  (主机别名/端口/用户走 ~/.ssh/config,如 myserver)
"""
import subprocess

from .config import BASE_DIR


def run(cfg, command, check=True, capture=False):
    host = cfg.get('ssh_host', '')
    if host:
        argv = ['ssh', '-o', 'BatchMode=yes', host, command]
        cwd = None
    else:
        argv = ['/bin/sh', '-c', command]
        cwd = BASE_DIR
    return subprocess.run(argv, cwd=cwd, check=check,
                          capture_output=capture, text=True)
