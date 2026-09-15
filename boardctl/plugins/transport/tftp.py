"""tftp 传输插件:设备端 tftpboot 拉取。文件就位方式由 [tftp].method 决定:
remote = scp 到远端 tftp 服务器(如 tftpd-hpa);
local  = 本机临时拉起 tftp_server.py(UDP 69 需要特权)。
"""
import atexit
import os
import re
import shutil
import socket
import subprocess
import sys
import time

from ...session import UbootSession

NAME = 'tftp'
CFG_SECTION = 'tftp'
DEFAULTS = {'method': 'remote', 'local_dir': 'tftpboot'}

# 内置 TFTP 服务器随包分发(boardctl/tftp_server.py)
_TFTP_SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'tftp_server.py')


def udp69_state():
    """探测本机 UDP 69:free / privileged / occupied"""
    t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        t.bind(('0.0.0.0', 69))
    except PermissionError:
        return 'privileged'
    except OSError:
        return 'occupied'
    finally:
        t.close()
    return 'free'


def _stage_file(cfg, path):
    """把文件放到 TFTP 服务器能读到的位置"""
    t = cfg['tftp']
    method = t.get('method', 'remote')
    fname = os.path.basename(path)

    if method == 'remote':
        ssh, rdir = t.get('ssh_host'), t.get('remote_dir')
        if not (ssh and rdir):
            sys.exit('tftp.method=remote 需要 tftp.ssh_host 和 tftp.remote_dir')
        r = subprocess.run(['scp', '-q', os.path.abspath(path), f'{ssh}:{rdir}/'],
                           timeout=60)
        if r.returncode != 0:
            sys.exit(f'scp 到 {ssh}:{rdir} 失败——多半是目录权限。\n'
                     f'一次性修复: ssh -t {ssh} "sudo chown $USER {rdir}"\n'
                     '或改用 --method loady(免权限,速度较慢)')
    elif method == 'local':
        state = udp69_state()
        if state == 'privileged':
            sys.exit('本机 UDP 69 需要特权:先执行 `! sudo -v`(凭证缓存 15 分钟),\n'
                     '再以 sudo 运行本命令;或改用 --method loady / remote')
        local_dir = os.path.abspath(t.get('local_dir', 'tftpboot'))
        os.makedirs(local_dir, exist_ok=True)
        shutil.copy(path, os.path.join(local_dir, fname))
        if state == 'free':
            # 临时拉起内置 TFTP 服务器,退出时一并回收
            srv = subprocess.Popen(
                [sys.executable, _TFTP_SERVER, local_dir],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            atexit.register(lambda: srv.poll() is None and srv.terminate())
            time.sleep(0.5)
        else:
            print(f'注意: UDP 69 已被占用——若占用者根目录不是 {local_dir},拉取会失败')
    else:
        sys.exit(f'未知 tftp.method: {method}')


def send(cfg, path, addr):
    _stage_file(cfg, path)
    fname = os.path.basename(path)
    server_ip = cfg['uboot'].get('server_ip')
    with UbootSession(cfg) as s:
        ok, _ = s.wait_prompt()
        if not ok:
            sys.exit('等待 U-Boot 提示符超时,设备可能不在 U-Boot 命令行')
        if cfg['uboot'].get('ensure_server_ip') and server_ip:
            s.cmd(f'setenv serverip {server_ip}')
        out = s.cmd(f'tftpboot {addr} {fname}', timeout=60)
        print(out.strip('\r\n'))
        m = re.search(r'Bytes transferred = (\d+)', out)
        if m:
            actual = os.path.getsize(path)
            size = int(m.group(1))
            ok = size == actual
            print(f'tftp {"OK" if ok else "大小不符"}: {size} 字节 -> {addr} (server {server_ip})'
                  + ('' if ok else f'(本地 {actual})'))
            return ok
        print('tftp 传输失败(未见 Bytes transferred)')
        return False
