"""U-Boot 串口会话:连接、等待提示符、执行命令收集输出"""
import codecs
import time

import serial


class UbootSession:
    """连接串口,等待 U-Boot 提示符,可执行命令并收集输出"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.ser = serial.serial_for_url(
            cfg['serial']['url'], timeout=cfg['serial']['timeout'])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self.ser.close()
        except OSError:
            pass

    def read_until(self, pattern, timeout):
        """读到文本里出现 pattern 为止;返回 (累计文本, 是否命中)"""
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        text = ''
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self.ser.read(256)
            if data:
                text += decoder.decode(data)
                if pattern in text:
                    return text, True
        return text, False

    def wait_prompt(self, timeout=8):
        """先 Ctrl-C 清掉可能残留的未完成输入行(引号/续行态),再等提示符;
        返回 (是否成功, 期间收到的文本)"""
        self.ser.write(b'\x03\r')
        text, hit = self.read_until(self.cfg['uboot']['prompt'], timeout)
        return hit, text

    def cmd(self, cmdline, timeout=30):
        """执行一条命令,收集到下一次提示符为止的输出"""
        self.ser.write(cmdline.encode() + b'\r')
        text, _ = self.read_until(self.cfg['uboot']['prompt'], timeout)
        return text
