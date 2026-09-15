#!/usr/bin/env python3
"""纯软件冒烟测试:不需要真机/串口/网络,CI 与本地都应能跑"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from boardctl.config import BASE_DIR, available_boards, load_board
from boardctl.plugins import EXECUTORS, POWER, TRANSPORT

# 1. 插件注册表齐全
assert {'loady', 'tftp'} <= set(TRANSPORT), TRANSPORT
assert {'go', 'source', 'none', 'booti', 'bootm'} <= set(EXECUTORS), EXECUTORS
assert {'mijia', 'command'} <= set(POWER), POWER

# 2. 执行插件命令构造(新接口 build_cmd(addr, t))
assert EXECUTORS['go'].build_cmd('0x80080000') == 'go 0x80080000'
assert EXECUTORS['source'].build_cmd('0x80080000', {}) == 'source 0x80080000'
assert EXECUTORS['none'].build_cmd('0x80080000', {}) is None
assert EXECUTORS['bootm'].build_cmd('0x80080000', {}) == 'bootm 0x80080000'
assert EXECUTORS['bootm'].build_cmd('0x80080000', {'initrd': '0x82000000', 'fdt': '0x83000000'}) \
    == 'bootm 0x80080000 0x82000000 0x83000000'
assert EXECUTORS['booti'].build_cmd('0x80080000', {'fdt': '0x83000000'}) \
    == 'booti 0x80080000 - 0x83000000'
assert EXECUTORS['booti'].build_cmd('0x80080000', {'fdt': '0x83000000', 'initrd': '0x82000000'}) \
    == 'booti 0x80080000 0x82000000 0x83000000'
try:
    EXECUTORS['booti'].build_cmd('0x80080000', {})
    raise AssertionError('booti 缺 fdt 应报错退出')
except SystemExit:
    pass

# 3. 断言引擎 evaluate(expect 子串 / expect_re 正则 / fail_re 禁止命中)
from boardctl.runner import evaluate  # noqa: E402

ok, detail, checked = evaluate('hello PASS world', {'expect': ['PASS']})
assert ok and checked and detail == ''
ok, detail, _ = evaluate('abc', {'expect': ['PASS']})
assert not ok and 'PASS' in detail
ok, _, _ = evaluate('Kernel panic - not syncing', {'expect_re': [r'(?i)panic']})
assert ok
ok, detail, _ = evaluate('Starting kernel', {'expect_re': [r'(?i)panic']})
assert not ok
ok, detail, _ = evaluate('kernel panic here', {'fail_re': ['panic']})
assert not ok and 'fail_re' in detail
ok, detail, checked = evaluate('anything', {})
assert ok and not checked

# 4. 板卡配置加载 + 插件默认值合并(用包内置通用示例验证,不依赖个人环境)
boards = available_boards()
assert 'example' in boards, boards
cfg = load_board('example')
assert 'sender' in cfg['loady'], cfg['loady']          # loady 插件自带 DEFAULTS
assert cfg['tftp']['method'] == 'remote', cfg['tftp']
assert cfg['power'].get('method') == 'command', cfg['power']
assert cfg['run']['hello']['reset_before'] is True     # 示例即全自动开关机

# 5. run 目标引用的文件真实存在(示例模板的占位路径除外)
for name, t in cfg['run'].items():
    path = t['file']
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    assert os.path.isfile(path) or cfg['name'] == 'example', \
        f'run.{name} 文件缺失: {path}'

# 6. 流式执行引擎(伪串口,无需硬件)
import time as _time  # noqa: E402

from boardctl import runner as _runner  # noqa: E402


class _FakeSer:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.written = b''

    def read(self, n):
        _time.sleep(0.01)
        return self.chunks.pop(0) if self.chunks else b''

    def write(self, b):
        self.written += b


def _stream(ser, t, **kw):
    import contextlib, io as _io
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        return _runner._stream_run(ser, 'go x', kw.get('prompt', 'soph#'),
                                   t, False, kw.get('timeout', 1.0))


out, ended = _stream(_FakeSer([b'BM-TEST-START\nBM-TEST-DONE\n']),
                     {'expect': ['BM-TEST-START', 'BM-TEST-DONE']})
assert ended == 'matched' and 'BM-TEST-DONE' in out, (ended, out)

out, ended = _stream(_FakeSer([b'output line\r\nsoph# ']), {})
assert ended == 'prompt', ended

out, ended = _stream(_FakeSer([]), {}, timeout=0.3)
assert ended == 'timeout', ended

out, ended = _stream(_FakeSer([b'kernel booting...']), {}, timeout=0.3)
assert ended == 'timeout' and 'kernel booting' in out, (ended, out)

# 7. 电源语义层导入无误
from boardctl import power  # noqa: E402,F401

print('software tests: OK')
