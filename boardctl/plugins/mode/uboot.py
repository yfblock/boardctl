"""uboot 启动模式([run.*].mode 的缺省值):冷启动 -> 传输插件上文件 -> cmd 执行。
U-Boot 特有知识的集中地:加载地址缺省链(addr <- uboot.load_addr,
entry <- addr)、{addr}/{entry} 模板变量、传输后等提示符再执行。"""
import os
import sys

from ...config import BASE_DIR
from . import RunMode, expand_cmd


def _expand(cfg, name, t):
    """uboot 命令展开:{addr}/{entry} 缺省链——addr <- uboot.load_addr,
    entry <- addr(目标键优先)"""
    tt = dict(t)
    tt.setdefault('addr', cfg['uboot']['load_addr'])
    tt.setdefault('entry', tt['addr'])
    return expand_cmd(name, tt)


class UbootMode(RunMode):
    NAME = 'uboot'

    def __init__(self, cfg):
        self.cfg = cfg

    def launch(self, runner):
        board, name, t = runner.board, runner.name, runner.t   # 该 runner 的对象数据
        cmdline = _expand(self.cfg, name, t) if t.get('cmd') else None

        if t.get('reset_before'):
            print(f'[{name}] 冷启动(断电->上电->等提示符)', flush=True)
            board.cold_boot()

        if 'file' not in t:
            sys.exit(f'run.{name}(mode=uboot)需要配置 file;'
                     '不传输直接执行命令用 mode = "console",被动观察用 mode = "watch"')
        path = t['file']
        if not os.path.isabs(path):
            path = os.path.join(BASE_DIR, path)
        if not os.path.isfile(path):
            sys.exit(f'文件不存在: {path}(先构建?)')
        addr = t.get('addr', self.cfg['uboot']['load_addr'])   # 加载地址(跳转地址 {entry} 由 cmd 模板取)
        method = t.get('method', 'tftp')
        from .. import TRANSPORT   # 函数内 import:注册表由插件包 __init__ 填充
        transport = TRANSPORT.get(method)
        if transport is None:
            sys.exit(f'未知传输方式 {method!r},可用: {" ".join(sorted(TRANSPORT)) or "(无)"}')

        print(f'[{name}] 传输 {t["file"]} ({method}) -> {addr}', flush=True)
        if not transport(self.cfg).send(board.stream, path, addr):
            sys.exit(1)

        if cmdline is None:
            print(f'[{name}] 已加载到 {addr}(未配置 cmd,不执行)')
            return None, None, 'loaded'

        print(f'[{name}] 执行: {cmdline}', flush=True)
        s = board.session()   # 同一条捕获流:传输、执行不分家
        ok, _ = s.wait_prompt()
        if not ok:
            sys.exit('等待 U-Boot 提示符超时')
        return s.stream, cmdline, None


PLUGIN = UbootMode
