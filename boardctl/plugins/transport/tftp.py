"""tftp 传输插件:设备端 tftpboot 拉取。文件就位方式由 [tftp].method 显式声明:
remote   = scp 到远端 tftp 服务器;
external = 本机已有常驻 tftpd(如 tftpd-hpa)服务 UDP 69,只把文件放进其
           根目录即可——不探测端口、不建服务器、免特权。
"""
import os
import re
import shutil
import subprocess
import sys

from ...console import ConsoleSession
from . import Transport


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


def _drop_into(local_dir, path, fname):
    """文件放进 tftp 根目录;已在目标位置则跳过(避免自拷贝)"""
    dst = os.path.join(local_dir, fname)
    if os.path.realpath(path) == os.path.realpath(dst):
        return
    os.makedirs(local_dir, exist_ok=True)
    shutil.copy(path, dst)


class TftpTransport(Transport):
    NAME = 'tftp'
    CFG_SECTION = 'tftp'
    DEFAULTS = {'method': 'remote', 'local_dir': 'tftpboot'}

    def __init__(self, cfg):
        self.cfg = cfg

    def _stage_file(self, path):
        """把文件放到 TFTP 服务器能读到的位置"""
        t = self.cfg['tftp']
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
        else:
            if method == 'local':
                sys.exit('tftp method="local"(boardctl 自建临时 TFTP 服务器)已移除:\n'
                         '本机常驻 tftpd(如 tftpd-hpa)改用 method = "external";\n'
                         '没有 tftpd 时,该目标改 method = "loady"(Ymodem 串口传输,免特权)')
            sys.exit(f'未知 tftp.method: {method}(可用: remote / external)')

    def send(self, channel, path, addr):
        """channel: 板的常驻捕获流(编排借出,插件不自开连接,用完不关)"""
        self._stage_file(path)
        fname = os.path.basename(path)
        server_ip = self.cfg['uboot'].get('server_ip')
        s = ConsoleSession(channel, self.cfg['console']['prompt'])
        ok, _ = s.wait_prompt()
        if not ok:
            sys.exit('等待 U-Boot 提示符超时,设备可能不在 U-Boot 命令行')
        if self.cfg['uboot'].get('ensure_server_ip') and server_ip:
            s.cmd(f'setenv serverip {server_ip}')
        out, hit = s.cmd(f'tftpboot {addr} {fname}', timeout=60)
        # 输出不重打:捕获事件上的显示回调(tap)已即捕即显(含回显与进度)
        m = re.search(r'Bytes transferred = (\d+)', out)
        if m:
            actual = os.path.getsize(path)
            size = int(m.group(1))
            ok = size == actual
            print(f'tftp {"OK" if ok else "大小不符"}: {size} 字节 -> {addr} (server {server_ip})'
                  + ('' if ok else f'(本地 {actual})'))
            return ok
        print('tftp 传输失败(未见 Bytes transferred'
              + ('' if hit else ';等待提示符超时,输出是截断的') + ')')
        return False


PLUGIN = TftpTransport
