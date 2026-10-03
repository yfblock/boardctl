"""控制台域:板上跑的交互载荷——U-Boot、Linux shell、其他 CLI 皆可。
boardctl 对控制台只有一个约定:有提示符的交互式会话(prompt 可配,
Ctrl-C 可打断当前输入行);提示符驱动的一切(等提示符/执行命令/收输出)
都在常驻捕获流(stream.py)的水位上展开——会话只决定"从哪起算、写什么、
等什么",字节读取统一归捕获线程。U-Boot 特有的加载地址、serverip、
tftpboot/loady 命令不属于这里——它们住在 [uboot] 配置段与传输插件/
cmd 模板中。
"""


class Console:
    """一块板的控制台:提示符 + 会话工厂 + 可交互判定"""

    def __init__(self, prompt):
        self.prompt = prompt

    @classmethod
    def from_cfg(cls, cfg):
        return cls(cfg['console']['prompt'])

    def session(self, stream):
        """在板的常驻捕获流上开一个控制台会话(借用,不持有)"""
        return ConsoleSession(stream, self.prompt)

    def interactive_ready(self, session, timeout=6):
        """上电后系统是否已到可交互态(提示符应答)"""
        return session.wait_prompt(timeout=timeout)[0]


class ConsoleSession:
    """常驻捕获流上的提示符会话(借用流,不持有)。

    水位在写之前打好:日志里躺着的旧提示符天然落在水位之外——旧模型
    靠"进门时已在提示符态"的调用纪律,现在是接口语义。cmd 只适用于会
    回到提示符的中场命令(环境准备/拉文件);启动载荷的末条指令(可能
    不归来)归 runner 的流式引擎。"""

    def __init__(self, stream, prompt):
        self.stream = stream
        self.prompt = prompt

    def read_until(self, pattern, timeout):
        """等到窗口文本里出现 pattern 为止;返回 (累计文本, 是否命中)"""
        since = self.stream.mark()
        return self.stream.wait(lambda text: pattern in text, since, timeout)

    def wait_prompt(self, timeout=8):
        """先 Ctrl-C 清掉可能残留的未完成输入行(引号/续行态),再等提示符;
        返回 (是否成功, 期间收到的文本)"""
        since = self.stream.mark()
        self.stream.write(b'\x03\r')
        text, hit = self.stream.wait(lambda text: self.prompt in text, since, timeout)
        return hit, text

    def cmd(self, cmdline, timeout=30):
        """执行一条中场命令,收集到下一次提示符为止的输出;
        返回 (输出, 是否等到提示符)——超时时输出是截断的,调用方据 False
        区分"没收全"与"收完但没有期望内容\""""
        since = self.stream.mark()
        self.stream.write(cmdline + '\r')
        return self.stream.wait(lambda text: self.prompt in text, since, timeout)
