"""uboot 启动模式([run.*].mode 的缺省值):冷启动 -> 传输插件上文件 -> cmd 执行。
U-Boot 特有知识的集中地:加载地址缺省链(addr <- uboot.load_addr,
entry <- addr)、{addr}/{entry} 模板变量、传输后等提示符再执行。"""
import os
import sys

from ...config import BASE_DIR
from . import RunMode, expand_cmd, target_vars


def _expand(cfg, name, t):
    """uboot 命令展开:{addr}/{entry} 缺省链——addr <- uboot.load_addr,
    entry <- addr(目标键优先)"""
    vals = target_vars(t)
    vals.setdefault('addr', cfg.uboot.load_addr)
    vals.setdefault('entry', vals['addr'])
    return expand_cmd(name, t.cmd, vals)


class UbootMode(RunMode):
    NAME = 'uboot'

    def __init__(self, cfg):
        self.cfg = cfg

    def launch(self, runner):
        board, name, t = runner.board, runner.name, runner.t   # this runner's object data
        cmdline = _expand(self.cfg, name, t) if t.cmd else None

        if t.reset_before:
            print(f'[{name}] 冷启动(断电->上电->等提示符)', flush=True)
            board.cold_boot()

        if t.file is None:
            sys.exit(f'run.{name}(mode=uboot)需要配置 file;'
                     '不传输直接执行命令用 mode = "console",被动观察用 mode = "watch"')
        path = t.file
        if not os.path.isabs(path):
            path = os.path.join(BASE_DIR, path)
        if not os.path.isfile(path):
            sys.exit(f'文件不存在: {path}(先构建?)')
        addr = t.addr or self.cfg.uboot.load_addr   # load address (entry {entry} comes from the cmd template)
        method = t.method or 'tftp'
        from .. import TRANSPORT   # function-local import: the registry is filled by the plugins package __init__
        transport = TRANSPORT.get(method)
        if transport is None:
            sys.exit(f'未知传输方式 {method!r},可用: {" ".join(sorted(TRANSPORT)) or "(无)"}')

        print(f'[{name}] 传输 {t.file} ({method}) -> {addr}', flush=True)
        if not transport(self.cfg).send(board.stream, path, addr):
            sys.exit(1)

        if cmdline is None:
            print(f'[{name}] 已加载到 {addr}(未配置 cmd,不执行)')
            return None, None, 'loaded'

        print(f'[{name}] 执行: {cmdline}', flush=True)
        s = board.session()   # the same capture stream: transport and execution share it
        ok, _ = s.wait_prompt()
        if not ok:
            sys.exit('等待 U-Boot 提示符超时')
        return s.stream, cmdline, None


PLUGIN = UbootMode
