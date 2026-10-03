"""控制台域:板上跑的交互载荷——U-Boot、Linux shell、其他 CLI 皆可。
boardctl 对控制台只有一个约定:有提示符的交互式会话(prompt 可配,
Ctrl-C 可打断当前输入行);提示符驱动的一切(等提示符/执行命令/收输出)
围绕它展开。U-Boot 特有的加载地址、serverip、tftpboot/loady 命令不属于
这里——它们住在 [uboot] 配置段与传输插件/cmd 模板中。
"""
import codecs
import time


class Console:
    """一块板的控制台:提示符 + 会话工厂 + 可交互判定"""

    def __init__(self, prompt):
        self.prompt = prompt

    @classmethod
    def from_cfg(cls, cfg):
        return cls(cfg['console']['prompt'])

    def session(self, channel):
        """在这截串口通道上开一个控制台会话(借用,不持有通道)"""
        return ConsoleSession(channel, self.prompt)

    def interactive_ready(self, session, timeout=6):
        """上电后系统是否已到可交互态(提示符应答)"""
        return session.wait_prompt(timeout=timeout)[0]


class ConsoleSession:
    """连接串口通道,等待控制台提示符,可执行命令并收集输出(不持有通道)"""

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
