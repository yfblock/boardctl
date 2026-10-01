#!/usr/bin/env python3
"""纯软件冒烟测试:不需要真机/串口/网络,CI 与本地都应能跑"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from boardctl.config import BASE_DIR, available_boards, load_board
from boardctl.plugins import EXECUTORS, POWER, TRANSPORT

# 1. 插件注册表齐全
assert {'loady', 'tftp'} <= set(TRANSPORT), TRANSPORT
assert {'go', 'source', 'none', 'booti', 'bootm', 'watch'} <= set(EXECUTORS), EXECUTORS
assert {'mijia', 'command'} <= set(POWER), POWER

# 2. 执行插件命令构造(新接口 build_cmd(addr, t))
assert EXECUTORS['go'].build_cmd('0x80080000') == 'go 0x80080000'
assert EXECUTORS['source'].build_cmd('0x80080000', {}) == 'source 0x80080000'
assert EXECUTORS['none'].build_cmd('0x80080000', {}) is None
assert EXECUTORS['watch'].PASSIVE is True          # 被动标记:runner 零写入分支
assert EXECUTORS['watch'].build_cmd('0x80080000', {}) is None
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

# 5. run 目标引用的文件真实存在(示例模板的占位路径除外;
#    watch 等被动目标无 file——板子自己获取)
for name, t in cfg['run'].items():
    if not t.get('file'):
        continue
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
        return _runner._stream_run(ser, kw.get('cmd', 'go x'), kw.get('prompt', 'soph#'),
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

# fail_re 流式即时命中(判负优先于判正);命中后先续收 fail_linger 秒再收工,
# 让错误信息/栈输出完整(默认 2s,0 = 立即)
out, ended = _stream(_FakeSer([b'boot ok\n', b'thread panicked at root.rs:401\n', b'never reached']),
                     {'expect': ['TEST_RUNNER_DONE'], 'fail_re': ['(?i)panic'], 'fail_linger': 0.3})
assert ended == 'fail' and 'panicked' in out and 'never reached' in out, (ended, out)

out, ended = _stream(_FakeSer([b'boot ok\n', b'thread panicked at root.rs:401\n', b'never reached']),
                     {'expect': ['TEST_RUNNER_DONE'], 'fail_re': ['(?i)panic'], 'fail_linger': 0})
assert ended == 'fail' and 'never reached' not in out, (ended, out)

out, ended = _stream(_FakeSer([b'DONE\npanic!\n']), {'expect': ['DONE'], 'fail_re': ['panic'],
                                                     'fail_linger': 0})
assert ended == 'fail', ended

# 被动观察(cmdline=None):零写入(连命令行回车都不发),输出照收、
# 结束条件(断言命中/提示符/超时/fail_re)与主动模式完全一致
ser = _FakeSer([b'U-Boot 2021.10\r\n', b'autoboot...\r\n', b'soph# '])
out, ended = _stream(ser, {}, cmd=None)
assert ended == 'prompt' and ser.written == b'' and 'U-Boot 2021.10' in out, (ended, out, ser.written)

ser = _FakeSer([b'autoboot\r\n', b'TEST_RUNNER_DONE\r\n', b'never printed'])
out, ended = _stream(ser, {'expect': ['TEST_RUNNER_DONE']}, cmd=None)
assert ended == 'matched' and ser.written == b'', (ended, ser.written)

ser = _FakeSer([])
out, ended = _stream(ser, {}, cmd=None, timeout=0.2)
assert ended == 'timeout' and ser.written == b'', (ended, ser.written)

# 被动目标整链路(_execute_target):exec=watch 走静默上电分支
# (不碰 power_cycle_and_wait——那个会发 Ctrl-C)、全程零写入、断言照常
import unittest.mock as _mock  # noqa: E402

_wser = _FakeSer([b'U-Boot 2021.10\r\n', b'TEST_RUNNER_DONE\r\n', b'soph# '])
_pcalls = []


class _FakeSession:
    def __init__(self, cfg):
        self.ser = _wser

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_mincfg = {'name': 'fake', 'serial': {'url': '', 'timeout': 0.05},
           'uboot': {'prompt': 'soph#', 'load_addr': '0x80080000'}, 'power': {}}
import contextlib, io as _io2  # noqa: E402

with contextlib.redirect_stdout(_io2.StringIO()), \
        _mock.patch.object(_runner, 'UbootSession', _FakeSession), \
        _mock.patch.object(_runner.power, 'power_cycle_quiet',
                           lambda cfg, ser: _pcalls.append('quiet')), \
        _mock.patch.object(_runner.power, 'power_cycle_and_wait',
                           lambda cfg, boot_timeout=60: _pcalls.append('WAIT')):
    ok, ended = _runner._execute_target(_mincfg, 'watch-t',
                                        {'exec': 'watch', 'reset_before': True,
                                         'after': 'none', 'timeout': 1.0,
                                         'expect': ['TEST_RUNNER_DONE']})
# 被动整链路:expect 一命中即收工(matched,不等提示符——与主动模式一致)
assert ok and ended == 'matched' and _pcalls == ['quiet'], (ok, ended, _pcalls)
assert _wser.written == b'', _wser.written   # 整链路零写入

# 被动模式拒绝 file(板子自己获取,传了必是配错)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner._execute_target(_mincfg, 'watch-t',
                                {'exec': 'watch', 'file': 'hello.bin', 'after': 'none'})
    raise AssertionError('watch 带 file 应被拒绝')
except SystemExit as e:
    assert 'file' in str(e.code), e.code

# 主动模式缺 file 给明确报错(此前是裸 KeyError)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner._execute_target(_mincfg, 'go-t', {'exec': 'go', 'after': 'none'})
    raise AssertionError('主动模式缺 file 应报错')
except SystemExit as e:
    assert 'file' in str(e.code), e.code

# 7. 电源语义层导入无误
from boardctl import power  # noqa: E402,F401

# 8. tftp 文件就位:external 只落文件、不探测不建服务器(已在根目录不自拷贝,
#    SameFileError 回归);local 自建路径快速失败——被占用指引 external、
#    无特权指引 sudo(占用判定读 /proc/net/udp,不受特权端口 EACCES 影响)
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from boardctl.plugins.transport import tftp as _tftp  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    # 8.1 /proc/net/udp 解析:端口按十六进制匹配
    fake = Path(td) / 'fakeudp'
    fake.write_text('  Sl  local_address            remote_address\n'
                    '   0: 0100007F:0045 00000000:0000 07 00000000:00000000\n'
                    '   1: 00000000:1F90 00000000:0000 07 00000000:00000000\n')
    assert len(_tftp._port_listeners(69, files=(str(fake),))) == 1     # 0x0045
    assert len(_tftp._port_listeners(8080, files=(str(fake),))) == 1   # 0x1F90
    assert _tftp._port_listeners(12345, files=(str(fake),)) == []
    assert _tftp._port_listeners(69, files=()) == []

    # 8.2 external:文件已在 tftp 根目录不重复落盘;异地文件复制到位
    root = Path(td) / 'srv'
    root.mkdir()
    (root / 'hello.bin').write_bytes(b'BM-TEST')
    outside = Path(td) / 'elsewhere.bin'
    outside.write_bytes(b'OTHER')
    cfg_x = {'tftp': {'method': 'external', 'local_dir': str(root)}}
    _tftp._stage_file(cfg_x, str(root / 'hello.bin'))     # 原地:不抛 SameFileError
    assert (root / 'hello.bin').read_bytes() == b'BM-TEST'
    _tftp._stage_file(cfg_x, str(outside))                # 异地:落盘进 tftp 根
    assert (root / 'elsewhere.bin').read_bytes() == b'OTHER'

    # 8.3 local 自建:occupied → 指引 external;privileged → 指引 sudo
    _orig_state = _tftp.udp69_state
    cfg_l = {'tftp': {'method': 'local', 'local_dir': str(root)}}
    try:
        for state, hint in (('occupied', 'external'), ('privileged', 'sudo')):
            _tftp.udp69_state = lambda s=state: s
            try:
                _tftp._stage_file(cfg_l, str(root / 'hello.bin'))
                raise AssertionError(f'{state} 应 sys.exit 退出')
            except SystemExit as e:
                assert hint in str(e), (state, e)
    finally:
        _tftp.udp69_state = _orig_state

# 9. 电源:mijia 开关量属性名可配(默认 on);power 子命令语义(on/off/status 经当前插件)
from boardctl import power as _power_mod  # noqa: E402
from boardctl.plugins import POWER as _POWER_REG  # noqa: E402
from boardctl.plugins.power import mijia as _mijia  # noqa: E402

assert _mijia._prop({'power': {}}) == 'on'                      # 缺省:多数插座
assert _mijia._prop({'power': {'mijia': {}}}) == 'on'
assert _mijia._prop({'power': {'mijia': {'prop': 'power'}}}) == 'power'


class _FakePowerPlugin:
    NAME = 'fake'
    calls = []
    state = True

    @classmethod
    def set_power(cls, cfg, on):
        cls.calls.append(on)

    @classmethod
    def get_power(cls, cfg):
        return cls.state


_POWER_REG['fake'] = _FakePowerPlugin
try:
    _fcfg = {'name': 'fake', 'power': {'method': 'fake'},
             'serial': {}, 'uboot': {}}
    for st, want in (('on', True), ('off', False)):
        try:
            _power_mod.do_power(_fcfg, st)
            raise AssertionError('do_power 完成 action 后应 exit(0)')
        except SystemExit as e:
            assert e.code == 0, e.code
        assert _FakePowerPlugin.calls[-1] is want, _FakePowerPlugin.calls
    _FakePowerPlugin.state = False
    with contextlib.redirect_stdout(_io2.StringIO()) as _so:
        try:
            _power_mod.do_power(_fcfg, 'status')
        except SystemExit as e:
            assert e.code == 0, e.code
    assert _so.getvalue().strip() == '关', _so.getvalue()
finally:
    del _POWER_REG['fake']

# 10. CLI 接线(cyclopts):走真实入口 app.meta 分发,叶子打桩
#     (do_run/板卡目录/do_power),不碰文件系统与硬件
from boardctl import cli as _cli  # noqa: E402

_runcalls = []
with _mock.patch.object(_cli, 'do_run',
                        lambda cfg, name, repeat=1: _runcalls.append((cfg['name'], name, repeat))), \
        _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/example.toml'}), \
        _mock.patch.object(_cli, 'load_board', lambda n: {'name': n, 'power': {}}):
    # 全局 -b 前置于子命令 + 位置参数 + 短旗标 -r
    _cli.app.meta(['-b', 'example', 'run', 'hello', '-r', '3'])
    assert _runcalls == [('example', 'hello', 3)], _runcalls
    # 缺省 -b:仅一块用户板时自动选中
    _runcalls.clear()
    _cli.app.meta(['run', 'hello'])
    assert _runcalls == [('example', 'hello', 1)], _runcalls
    # 省略目标名 = 列出目标(do_run 收到 None)
    _runcalls.clear()
    _cli.app.meta(['run'])
    assert _runcalls == [('example', None, 1)], _runcalls

# 多块用户板且未 -b:明确报错退出
with _mock.patch.object(_cli, 'available_boards',
                        lambda: {'a': '/x/a.toml', 'b': '/x/b.toml'}):
    try:
        _cli.app.meta(['run'])
        raise AssertionError('多板未指定 -b 应报错退出')
    except SystemExit as e:
        assert '请用 -b' in str(e.code), e.code

# power 分发:state 与板卡配置送抵 do_power(on/off 前的提示行照打)
_pcalls = []
with _mock.patch.object(_cli, 'load_board', lambda n: {'name': n, 'power': {}}), \
        _mock.patch.object(_cli.power, 'do_power',
                           lambda cfg, st: _pcalls.append((cfg['name'], st))), \
        contextlib.redirect_stdout(_io2.StringIO()):
    _cli.app.meta(['-b', 'ex', 'power', 'off'])
assert _pcalls == [('ex', 'off')], _pcalls

# power 非法 state:Literal 校验拒绝
try:
    _cli.app.meta(['power', 'bogus'])
    raise AssertionError('非法 power state 应被拒绝')
except SystemExit as e:
    assert e.code == 1, e.code

# ls 分发
with _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/example.toml'}), \
        _mock.patch.object(_cli, 'load_board', lambda n: {'name': n, 'description': '示例'}):
    with contextlib.redirect_stdout(_io2.StringIO()) as _so:
        _cli.app.meta(['ls'])
assert 'example' in _so.getvalue(), _so.getvalue()

# 无参数:打印帮助,退出码 0
with contextlib.redirect_stdout(_io2.StringIO()) as _so:
    try:
        _cli.app.meta([])
    except SystemExit as e:
        assert e.code == 0, e.code
assert 'run' in _so.getvalue(), _so.getvalue()

print('software tests: OK')
