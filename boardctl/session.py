"""U-Boot 协议(开发板域):在一截串口通道上收发 U-Boot 命令——
提示符等待、命令发送、输出收集。纯借用:通道由调用方给(通常是板上的
SerialChannel,随板关闭),会话不持有、不关闭通道"""
import codecs
import time


class UbootSession:
    """连接串口通道,等待 U-Boot 提示符,可执行命令并收集输出(不持有通道)"""

    def __init__(self, channel, prompt):
        self.channel = channel
        self.prompt = prompt

    def read_until(self, pattern, timeout):
        """读到文本里出现 pattern 为止;返回 (累计文本, 是否命中)"""
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        text = ''
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self.channel.read(256)
            if data:
                text += decoder.decode(data)
                if pattern in text:
                    return text, True
        return text, False

    def wait_prompt(self, timeout=8):
        """先 Ctrl-C 清掉可能残留的未完成输入行(引号/续行态),再等提示符;
        返回 (是否成功, 期间收到的文本)"""
        self.channel.write(b'\x03\r')
        text, hit = self.read_until(self.prompt, timeout)
        return hit, text

    def cmd(self, cmdline, timeout=30):
        """执行一条命令,收集到下一次提示符为止的输出"""
        self.channel.write(cmdline.encode() + b'\r')
        text, _ = self.read_until(self.prompt, timeout)
        return text
