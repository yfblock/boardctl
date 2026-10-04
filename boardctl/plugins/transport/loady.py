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
        time.sleep(1.5)  # 等设备进入 Ymodem 接收态

        # 把串口 fd 借给发送器:捕获线程先让位(park),借出期间的 Ymodem
        # 协议字节归发送器、不进捕获日志;resume 后剩余字节无缝接上
        # (清 O_NONBLOCK 等底层细节是串口域 SerialChannel 的职责,插件不碰)
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
        # 串口侧输出不重打:tap 已即捕即显(loady 回显在借出前落日志,
        # Total Size 在 resume 后无缝接上——全程都在显示);成功不报告,
        # 只有本地才有的知识(文件大小核对)或失败判定才开口
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
