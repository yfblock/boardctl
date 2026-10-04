"""command 电源插件:执行 [power] 里配置的 on_cmd / off_cmd / status_cmd 命令

"特制开关机命令"方式:任意 shell 命令,经顶层 ssh_host 决定本机/远端执行。
status_cmd 可缺省;命令输出无法可靠解析时 status 返回 None(上层原样打印)。
method 未配置时默认即本插件。
"""
import sys

from ...shell import run as run_shell
from . import PowerDevice


class CommandPower(PowerDevice):
    NAME = 'command'

    def __init__(self, cfg):
        self.cfg = cfg

    def _cmd(self, key):
        command = getattr(self.cfg.power, key)
        if not command:
            sys.exit(f'[power] 缺少 {key}(command 电源插件需要 on_cmd/off_cmd)')
        return command

    def on(self):
        run_shell(self.cfg, self._cmd('on_cmd'), check=True)

    def off(self):
        run_shell(self.cfg, self._cmd('off_cmd'), check=True)

    def status(self):
        status = self.cfg.power.status_cmd
        if status:
            run_shell(self.cfg, status, check=False)
        return None   # 任意命令的输出无法可靠解析为 bool


PLUGIN = CommandPower
