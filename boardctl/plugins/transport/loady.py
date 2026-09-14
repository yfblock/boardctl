"""loady 传输插件:设备端 loady(Ymodem)+ 本机 lrzsz 发送器,走串口,零网络依赖"""
import fcntl
import os
import re
import shutil
import subprocess
import sys
import time

from ...session import UbootSession

NAME = 'loady'
CFG_SECTION = 'loady'
DEFAULTS = {'sender': ''}   # Ymodem 发送器;空则自动找 lrzsz-sb / sb


def find_sender(cfg):
    sender = cfg['loady'].get('sender')
    if sender and os.path.isfile(sender):
        return sender
    return shutil.which('lrzsz-sb') or shutil.which('sb')


def send(cfg, path, addr):
    sender = find_sender(cfg)
    if not sender:
        sys.exit('找不到 Ymodem 发送器(Arch: lrzsz 包的 lrzsz-sb;Debian: lrzsz 的 sb)')
    with UbootSession(cfg) as s:
        ok, _ = s.wait_prompt()
        if not ok:
            sys.exit('等待 U-Boot 提示符超时,设备可能不在 U-Boot 命令行')
        s.ser.write(f'loady {addr}\r'.encode())
        time.sleep(1.5)  # 等设备进入 Ymodem 接收态

        # socket:// 的 pyserial 对象没有 fileno(),用底层 socket
        raw = getattr(s.ser, 'sock', None)
        fd = raw.fileno() if raw is not None else None
        if fd is None:
            try:
                fd = s.ser.fileno()
            except Exception:
                fd = None
        if fd is None:
            sys.exit('该串口 URL 不支持把 fd 交给 Ymodem 发送器')
        # 关键: 清掉 settimeout() 设置的 O_NONBLOCK,否则子进程 read 得到 EAGAIN 被当成超时
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)

        p = subprocess.Popen([sender, os.path.abspath(path)],
                             stdin=fd, stdout=fd, stderr=subprocess.PIPE)
        try:
            _, err = p.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            print('Ymodem 发送器超时(180s),已终止')
            return False
        tail, _ = s.read_until(s.cfg['uboot']['prompt'], 10)
        print(err.decode('utf-8', 'replace').strip())
        print(tail.strip('\r\n'))
        m = re.search(r'Total Size\s*=\s*(0x[0-9a-fA-F]+|\d+)', tail)
        if m:
            size = int(m.group(1), 0)
            actual = os.path.getsize(path)
            ok = size == actual
            print(f'loady {"OK" if ok else "大小不符"}: {size} 字节 -> {addr}'
                  + ('' if ok else f'(本地 {actual})'))
            return ok
        print('loady 传输失败(未见 Total Size 报告)')
        return False
