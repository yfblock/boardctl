"""watch 启动模式:被动观察——板子自己完成传输与执行(bootcmd/板上自动
脚本),boardctl 全程零写入:不发命令,连冷启动等提示符的 Ctrl-C 都不能发
(会打断板上流程)。捕获流常驻(连接在 Board 构造时已建立),静默上电前
清噪——启动输出从第一个字节起全数落进捕获日志。"""
import sys

from . import RunMode


class WatchMode(RunMode):
    NAME = 'watch'

    def __init__(self, cfg):
        self.cfg = cfg

    def launch(self, runner):
        board, name, t = runner.board, runner.name, runner.t   # 该 runner 的对象数据
        for k in ('file', 'cmd'):
            if t.get(k):
                sys.exit(f'run.{name}(mode=watch)为被动模式,不认 {k}'
                         '(板子自行完成传输与执行)')
        if t.get('reset_before'):
            print(f'[{name}] 冷启动(静默:断电->上电,不写串口)', flush=True)
            board.quiet_boot()   # 内部清噪+上电:捕获日志的起点即上电
        print(f'[{name}] 被动观察(mode=watch:不发送任何命令)', flush=True)
        return board.stream, None, None


PLUGIN = WatchMode
