"""tftp 传输插件:设备端 tftpboot 拉取。文件就位方式由 [tftp].method 显式声明:
remote   = scp 到远端 tftp 服务器;
external = 本机已有常驻 tftpd(如 tftpd-hpa)服务 UDP 69,只把文件放进其
           根目录即可——不探测端口、不建服务器、免特权;
local    = boardctl 自建临时 tftp_server.py(UDP 69 需特权,退出自动回收)。
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


def _port_listeners(port, files=('/proc/net/udp', '/proc/net/udp6')):
    """从 /proc/net/udp{,6} 找绑定该本地 UDP 端口的套接字(无特权可见)。
    返回非空 = 有进程占着该端口(如常驻 tftpd-hpa)。"""
    found = []
    for f in files:
        try:
            with open(f) as fh:
                next(fh, None)   # 表头
                for line in fh:
                    cols = line.split()
                    if len(cols) > 1 and ':' in cols[1]:
                        try:
                            if int(cols[1].rsplit(':', 1)[1], 16) == port:
                                found.append(f'{f}: {cols[1]}')
                        except ValueError:
                            continue
        except OSError:
            continue
    return found


def udp69_state():
    """探测本机 UDP 69 能否自建服务器:free / privileged / occupied。
    占用判定优先读 /proc/net/udp:非 root 试绑特权端口只会得到 EACCES
    (内核先查 CAP_NET_BIND_SERVICE 再查端口冲突),区分不出被占用。"""
    if _port_listeners(69):
        return 'occupied'
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


def _drop_into(local_dir, path, fname):
    """文件放进 tftp 根目录;已在目标位置则跳过(避免自拷贝)"""
    dst = os.path.join(local_dir, fname)
    if os.path.realpath(path) == os.path.realpath(dst):
        return
    os.makedirs(local_dir, exist_ok=True)
    shutil.copy(path, dst)


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
                     '或该目标 method = "loady"(免权限,速度较慢)')
    elif method == 'external':
        # 常驻 tftpd 已在本机服务 UDP 69:boardctl 只落文件,服务器是否在跑
        # 由声明者负责——探测端口属于猜测意图,不猜(仅提醒一句疑似没在跑)
        local_dir = os.path.abspath(t.get('local_dir', 'tftpboot'))
        _drop_into(local_dir, path, fname)
        if os.path.exists('/proc/net/udp') and not _port_listeners(69):
            print('警告: 本机未见 UDP 69 监听——常驻 tftpd 好像没在运行,设备拉取大概率失败',
                  file=sys.stderr, flush=True)
    elif method == 'local':
        # boardctl 自建临时 TFTP 服务器;探测只为快速失败,给出明确替代方案
        state = udp69_state()
        if state == 'occupied':
            sys.exit('UDP 69 已被其他进程占用(常驻 tftpd?)。\n'
                     '若它就是你的 TFTP 服务器,改 tftp.method = "external"'
                     '(只落文件,免特权、不探测);\n'
                     '若要 boardctl 自建服务器,先停掉占用者再试')
        if state == 'privileged':
            sys.exit('UDP 69 空闲,但 boardctl 自建 TFTP 服务器需要特权:\n'
                     '先 `sudo -v`(凭证缓存约 15 分钟)再以 sudo 运行;\n'
                     '或常驻一个 tftpd 改用 method = "external",或该目标 method = "loady"')
        local_dir = os.path.abspath(t.get('local_dir', 'tftpboot'))
        _drop_into(local_dir, path, fname)
        # 临时拉起内置 TFTP 服务器,退出时一并回收
        srv = subprocess.Popen(
            [sys.executable, _TFTP_SERVER, local_dir],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        atexit.register(lambda: srv.poll() is None and srv.terminate())
        time.sleep(0.5)
    else:
        sys.exit(f'未知 tftp.method: {method}(可用: remote / external / local)')


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
