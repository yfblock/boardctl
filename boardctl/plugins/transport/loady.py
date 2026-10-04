"""loady 传输插件:设备端 loady(Ymodem)+ 本机 lrzsz 发送器,走串口,零网络依赖"""
import os
import re
import shutil
import subprocess
import sys
import time

from ...console import ConsoleSession
from . import Transport


class LoadyTransport(Transport):
    NAME = 'loady'

    def __init__(self, cfg):
        self.cfg = cfg

    def _sender(self):
        sender = self.cfg.loady.sender
        if sender and os.path.isfile(sender):
            return sender
        return shutil.which('lrzsz-sb') or shutil.which('sb')

    def send(self, channel, path, addr):
        """channel: 板的常驻捕获流(编排借出,插件不自开连接,用完不关)"""
        sender = self._sender()
        if not sender:
            sys.exit('找不到 Ymodem 发送器(Arch: lrzsz 包的 lrzsz-sb;Debian: lrzsz 的 sb)')
        s = ConsoleSession(channel, self.cfg.console.prompt)
        ok, _ = s.wait_prompt()
        if not ok:
            sys.exit('等待 U-Boot 提示符超时,设备可能不在 U-Boot 命令行')
        channel.write(f'loady {addr}\r')
        time.sleep(1.5)  # wait for the device to enter Ymodem receive mode

        # lend the serial fd to the sender: the capture thread stands down
        # first (park); Ymodem protocol bytes during the lend belong to the
        # sender and stay out of the capture log; after resume the remaining
        # bytes pick up seamlessly (low-level details like clearing O_NONBLOCK
        # are the serial-domain SerialChannel's job, not the plugin's)
        channel.park()
        try:
            fd = channel.blocking_fd()
            if fd is None:
                sys.exit('该串口 URL 不支持把 fd 交给 Ymodem 发送器')

            p = subprocess.Popen([sender, os.path.abspath(path)],
                                 stdin=fd, stdout=fd, stderr=subprocess.PIPE)
            try:
                _, err = p.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()
                print('Ymodem 发送器超时(180s),已终止')
                return False
        finally:
            channel.resume()
        tail, _ = s.read_until(s.prompt, 10)
        print(err.decode('utf-8', 'replace').strip())
        # serial-side output isn't reprinted: the tap already shows it live
        # (the loady echo lands in the log before the lend, Total Size picks
        # up after resume — on screen throughout); success stays silent, only
        # locally-known facts (size check) or failure verdicts get printed
        m = re.search(r'Total Size\s*=\s*(0x[0-9a-fA-F]+|\d+)', tail)
        if m:
            size = int(m.group(1), 0)
            actual = os.path.getsize(path)
            ok = size == actual
            if not ok:
                print(f'loady 大小不符: 设备收到 {size} 字节(本地 {actual})')
            return ok
        print('loady 传输失败(未见 Total Size 报告)')
        return False


PLUGIN = LoadyTransport
