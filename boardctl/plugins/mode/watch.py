"""watch 启动模式:被动观察——板子自己完成传输与执行(bootcmd/板上自动
脚本),boardctl 全程零写入:不发命令,连冷启动等提示符的 Ctrl-C 都不能发
(会打断板上流程)。串口先挂好再静默上电,从启动输出的第一个字节开始收。"""
import sys

from . import RunMode


class WatchMode(RunMode):
    NAME = 'watch'

    def __init__(self, cfg):
        self.cfg = cfg

    def launch(self, board, name, t):
        for k in ('file', 'cmd'):
            if t.get(k):
                sys.exit(f'run.{name}(mode=watch)为被动模式,不认 {k}'
                         '(板子自行完成传输与执行)')
        s = board.session()   # 板的通道先挂好再上电,从首字节收流
        if t.get('reset_before'):
            print(f'[{name}] 冷启动(静默:断电->上电,不写串口)', flush=True)
            board.quiet_boot()
        print(f'[{name}] 被动观察(mode=watch:不发送任何命令)', flush=True)
        return s.channel, None, None


PLUGIN = WatchMode
