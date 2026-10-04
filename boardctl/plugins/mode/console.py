"""console 启动模式:不传输,上电到提示符后直接执行 cmd——Linux shell 等
提示符驱动控制台的典型形态。无地址语义:{addr}/{entry} 不可用(未配置
即报错指名),变量取本目标键。将来若出现面向 shell 的串口传输插件
(如 base64 粘贴),再放开 file/method。"""
import sys

from . import RunMode, expand_cmd, target_vars


class ConsoleMode(RunMode):
    NAME = 'console'

    def __init__(self, cfg):
        self.cfg = cfg

    def launch(self, runner):
        board, name, t = runner.board, runner.name, runner.t   # this runner's object data
        for k in ('file', 'method', 'addr', 'entry'):
            if getattr(t, k):
                sys.exit(f'run.{name}(mode=console)不认 {k}:控制台模式只执行命令,'
                         '无传输/地址语义(要传文件用 mode = "uboot")')
        if not t.cmd:
            sys.exit(f'run.{name}(mode=console)需要配置 cmd(直接在控制台执行的命令)')
        cmdline = expand_cmd(name, t.cmd, target_vars(t))

        if t.reset_before:
            print(f'[{name}] 冷启动(断电->上电->等提示符)', flush=True)
            board.cold_boot()

        print(f'[{name}] 执行: {cmdline}', flush=True)
        return board.stream, cmdline, None   # cold_boot already confirmed the prompt; the streaming engine marks its own watermark


PLUGIN = ConsoleMode
