#!/usr/bin/env python3
"""纯软件冒烟测试:不需要真机/串口/网络,CI 与本地都应能跑"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from boardctl.config import BASE_DIR, available_boards, load_board
from boardctl.plugins import MODE, POWER, TRANSPORT

# 1. 插件注册表齐全(0.11.0 起执行插件族退役:执行命令回归 cmd 模板配置;
#    0.13 起"目标怎么弄起来"归 mode 插件族,[run.*].mode 选择)
assert {'loady', 'tftp'} <= set(TRANSPORT), TRANSPORT
assert {'mijia', 'command'} <= set(POWER), POWER
assert {'uboot', 'console', 'watch'} <= set(MODE), MODE

# 2. cmd 模板展开(执行命令是配置数据;展开器住 mode 族,{addr}/{entry}
#    缺省链由 uboot 模式注入:addr <- uboot.load_addr,entry <- addr;
#    console 模式无缺省,变量只取本目标键;未知变量报错指名)
from boardctl.plugins.mode import expand_cmd  # noqa: E402
from boardctl.plugins.mode.uboot import _expand  # noqa: E402

_mc = {'uboot': {'load_addr': '0x80080000'}}
assert _expand(_mc, 't', {'cmd': 'go {addr}'}) == 'go 0x80080000'
assert _expand(_mc, 't', {'cmd': 'source {entry}'}) == 'source 0x80080000'
assert _expand(_mc, 't', {'cmd': 'go {entry}', 'entry': '0x80090000'}) == 'go 0x80090000'
assert _expand(_mc, 't', {'cmd': 'booti {addr} - {fdt}', 'fdt': '0x83000000'}) \
    == 'booti 0x80080000 - 0x83000000'
assert _expand(_mc, 't', {'cmd': 'bootm {addr} {initrd} {fdt}',
                          'initrd': '0x82000000', 'fdt': '0x83000000'}) \
    == 'bootm 0x80080000 0x82000000 0x83000000'
assert expand_cmd('t', {'cmd': 'echo {{not var}}'}) == 'echo {{not var}}'  # 非变量花括号原样
assert expand_cmd('t', {'cmd': 'tester {slot}', 'slot': 3}) == 'tester 3'  # console:变量取目标键
try:
    _expand(_mc, 't', {'cmd': 'booti {addr} - {fdt}'})
    raise AssertionError('cmd 缺变量应报错退出')
except SystemExit as e:
    assert 'fdt' in str(e) and 'run.t' in str(e), e
try:
    expand_cmd('t', {'cmd': 'go {addr}'})   # console 无地址缺省,{addr} 即未知变量
    raise AssertionError('console 模式 {addr} 应报错退出')
except SystemExit as e:
    assert 'addr' in str(e) and 'run.t' in str(e), e

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

# 被动目标整链路(Runner.run):mode=watch 走静默上电分支
# (不碰 Board.cold_boot——那个会发 Ctrl-C)、全程零写入、断言照常
import unittest.mock as _mock  # noqa: E402

_wser = _FakeSer([b'U-Boot 2021.10\r\n', b'TEST_RUNNER_DONE\r\n', b'soph# '])
_pcalls = []


class _FakeSession:
    """ConsoleSession 桩:纯借用,不持有不关通道"""

    def __init__(self, channel, prompt):
        self.channel = channel
        self.prompt = prompt


class _FakeBoard:
    """Board 桩:serial 即伪串口(可注入),session 借它开;记录冷启动
    走哪条路径(after=none 时 power 不触)"""

    def __init__(self, cfg, ser=None):
        self.cfg = cfg
        self.power = None
        self.serial = ser or _wser

    @property
    def prompt(self):
        return self.cfg['console']['prompt']

    def session(self):
        return _FakeSession(self.serial, self.cfg['console']['prompt'])

    def cold_boot(self, boot_timeout=60):
        _pcalls.append('WAIT')

    def quiet_boot(self):
        _pcalls.append('quiet')


_mincfg = {'name': 'fake', 'serial': {'url': '', 'timeout': 0.05},
           'console': {'prompt': 'soph#'},
           'uboot': {'load_addr': '0x80080000'}, 'power': {}}
import contextlib, io as _io2  # noqa: E402

with contextlib.redirect_stdout(_io2.StringIO()):
    ok, ended = _runner.Runner(_FakeBoard(_mincfg), 'watch-t',
                               {'mode': 'watch', 'reset_before': True,
                                'after': 'none', 'timeout': 1.0,
                                'expect': ['TEST_RUNNER_DONE']}).run()
# 被动整链路:expect 一命中即收工(matched,不等提示符——与主动模式一致)
assert ok and ended == 'matched' and _pcalls == ['quiet'], (ok, ended, _pcalls)
assert _wser.written == b'', _wser.written   # 整链路零写入

# 模式解析:mode 显式声明;旧 exec="watch" 等价(存量配置零改动);缺省 uboot
assert _runner._resolve_mode('t', {}) == 'uboot'
assert _runner._resolve_mode('t', {'exec': 'watch'}) == 'watch'
assert _runner._resolve_mode('t', {'mode': 'console'}) == 'console'
assert _runner._resolve_mode('t', {'mode': 'watch', 'exec': 'watch'}) == 'watch'

# console 模式整链路:不传输,冷启动到提示符后直接执行 cmd(Linux shell 形态)
_pcalls.clear()
_cser = _FakeSer([b'ALL PASS\r\n', b'soph# '])
with contextlib.redirect_stdout(_io2.StringIO()):
    ok, ended = _runner.Runner(_FakeBoard(_mincfg, _cser), 'sh-t',
                               {'mode': 'console', 'cmd': './selftest.sh',
                                'reset_before': True, 'after': 'none',
                                'timeout': 1.0, 'expect': ['ALL PASS']}).run()
assert ok and ended == 'matched' and _pcalls == ['WAIT'], (ok, ended, _pcalls)
assert _cser.written == b'./selftest.sh\r', _cser.written   # 只发命令本身

# console 模式拒绝 file/method/addr(无传输/地址语义)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 'sh-t',
                       {'mode': 'console', 'cmd': 'x', 'file': 'f.bin',
                        'after': 'none'}).run()
    raise AssertionError('console 带 file 应被拒绝')
except SystemExit as e:
    assert 'file' in str(e.code) and 'console' in str(e.code), e.code

# 未知模式给明确报错(注册表里有什么就报什么)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 't', {'mode': 'gdb', 'after': 'none'}).run()
    raise AssertionError('未知 mode 应被拒绝')
except SystemExit as e:
    assert 'gdb' in str(e.code) and 'uboot' in str(e.code), e.code

# 被动模式拒绝 file(旧写法 exec="watch" 走同一条路——别名兼容)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 'watch-t',
                       {'exec': 'watch', 'file': 'hello.bin', 'after': 'none'}).run()
    raise AssertionError('watch 带 file 应被拒绝')
except SystemExit as e:
    assert 'file' in str(e.code), e.code

# uboot 模式缺 file 给明确报错(此前是裸 KeyError)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 'go-t',
                       {'cmd': 'go {addr}', 'after': 'none'}).run()
    raise AssertionError('主动模式缺 file 应报错')
except SystemExit as e:
    assert 'file' in str(e.code), e.code

# 残留旧式 exec(除 watch)→ 指引改 mode/cmd
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 'go-t',
                       {'exec': 'go', 'after': 'none'}).run()
    raise AssertionError('旧式 exec=go 应被拒绝')
except SystemExit as e:
    assert 'cmd' in str(e.code), e.code

# 7. 电源语义层导入无误
from boardctl import power  # noqa: E402,F401

# 8. tftp 文件就位:external 只落文件、不探测不建服务器(已在根目录不自拷贝,
#    SameFileError 回归);local 已移除——残留配置给迁移指引
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
    _tftp.TftpTransport(cfg_x)._stage_file(str(root / 'hello.bin'))     # 原地:不抛 SameFileError
    assert (root / 'hello.bin').read_bytes() == b'BM-TEST'
    _tftp.TftpTransport(cfg_x)._stage_file(str(outside))                # 异地:落盘进 tftp 根
    assert (root / 'elsewhere.bin').read_bytes() == b'OTHER'

    # 8.3 local 已移除(不再自建 TFTP 服务器):残留配置报迁移指引
    cfg_l = {'tftp': {'method': 'local', 'local_dir': str(root)}}
    try:
        _tftp.TftpTransport(cfg_l)._stage_file(str(root / 'hello.bin'))
        raise AssertionError('method=local 应 sys.exit 退出(已移除)')
    except SystemExit as e:
        assert 'external' in str(e) and 'loady' in str(e), e

# 9. 电源:插件即类(PowerDevice 子类,多态同接口),域门面 Power 也是类
#    (包住插件实例,统一错误包装);mijia 开关量属性名可配(默认 on);
#    power 子命令语义(apply:on/off/status 经当前电源插件类)
from boardctl import power as _power_mod  # noqa: E402
from boardctl.plugins import POWER as _POWER_REG  # noqa: E402
from boardctl.plugins.power import mijia as _mijia  # noqa: E402

assert _mijia.MijiaPower({'power': {}})._prop() == 'on'                # 缺省:多数插座
assert _mijia.MijiaPower({'power': {'mijia': {}}})._prop() == 'on'
assert _mijia.MijiaPower({'power': {'mijia': {'prop': 'power'}}})._prop() == 'power'


class _FakePowerPlugin:
    """PowerDevice 形状的桩:记录 on/off 调用,status 可拨"""

    NAME = 'fake'
    calls = []
    state = True

    def __init__(self, cfg):
        self.cfg = cfg

    def on(self):
        self.calls.append(True)

    def off(self):
        self.calls.append(False)

    def status(self):
        return self.state


_POWER_REG['fake'] = _FakePowerPlugin
try:
    _fcfg = {'name': 'fake', 'power': {'method': 'fake'},
             'serial': {}, 'uboot': {}}
    for st, want in (('on', True), ('off', False)):
        try:
            _power_mod.Power(_fcfg).apply(st)
            raise AssertionError('apply 完成 action 后应 exit(0)')
        except SystemExit as e:
            assert e.code == 0, e.code
        assert _FakePowerPlugin.calls[-1] is want, _FakePowerPlugin.calls
    _FakePowerPlugin.state = False
    with contextlib.redirect_stdout(_io2.StringIO()) as _so:
        try:
            _power_mod.Power(_fcfg).apply('status')
        except SystemExit as e:
            assert e.code == 0, e.code
    assert _so.getvalue().strip() == '关', _so.getvalue()
finally:
    del _POWER_REG['fake']

# 10. CLI 接线(google-fire):Boardctl 类方法即子命令,走 fire.Fire 真实入口,
#     叶子打桩(do_run/板卡目录/Power 门面),不碰文件系统与硬件
from boardctl import cli as _cli  # noqa: E402

_runcalls = []
with _mock.patch.object(_cli, 'do_run',
                        lambda cfg, name, repeat=1: _runcalls.append((cfg['name'], name, repeat))), \
        _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/example.toml'}), \
        _mock.patch.object(_cli, 'load_board', lambda n: {'name': n, 'power': {}}):
    # 全局 -b 前置于子命令(构造器短别名)+ 位置参数 + 短旗标 -r
    _cli.fire.Fire(_cli.Boardctl, ['-b', 'example', 'run', 'hello', '-r', '3'])
    assert _runcalls == [('example', 'hello', 3)], _runcalls
    # 缺省 -b:仅一块用户板时自动选中
    _runcalls.clear()
    _cli.fire.Fire(_cli.Boardctl, ['run', 'hello'])
    assert _runcalls == [('example', 'hello', 1)], _runcalls
    # 省略目标名 = 列出目标(do_run 收到 None)
    _runcalls.clear()
    _cli.fire.Fire(_cli.Boardctl, ['run'])
    assert _runcalls == [('example', None, 1)], _runcalls
    # 纯数字板名:fire 字面量化成 int,__init__ 的 str() 兜底还原
    _runcalls.clear()
    _cli.fire.Fire(_cli.Boardctl, ['-b', '2026', 'run', 'x'])
    assert _runcalls == [('2026', 'x', 1)], _runcalls

# repeat 手工校验(fire 不做类型校验)
with _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/e.toml'}), \
        _mock.patch.object(_cli, 'load_board', lambda n: {'name': n, 'power': {}}):
    try:
        _cli.fire.Fire(_cli.Boardctl, ['run', 'hello', '-r', 'abc'])
        raise AssertionError('非法 repeat 应被拒绝')
    except SystemExit as e:
        assert '正整数' in str(e.code), e.code

# 多块用户板且未 -b:明确报错退出
with _mock.patch.object(_cli, 'available_boards',
                        lambda: {'a': '/x/a.toml', 'b': '/x/b.toml'}):
    try:
        _cli.fire.Fire(_cli.Boardctl, ['run'])
        raise AssertionError('多板未指定 -b 应报错退出')
    except SystemExit as e:
        assert '请用 -b' in str(e.code), e.code

# power 分发:state 与板卡配置送抵 Power.apply(on/off 前的提示行照打)
_pcalls = []


class _FakeCliPower:
    """Power 门面桩:记录 apply 调用(板名 + state)"""

    desc = '插件 fake'

    def __init__(self, cfg):
        self.cfg = cfg

    def apply(self, state):
        _pcalls.append((self.cfg['name'], state))


with _mock.patch.object(_cli, 'load_board', lambda n: {'name': n, 'power': {}}), \
        _mock.patch.object(_cli.power, 'Power', _FakeCliPower), \
        contextlib.redirect_stdout(_io2.StringIO()):
    _cli.Boardctl(board='ex').power('off')                         # 直接调方法
    _cli.fire.Fire(_cli.Boardctl, ['-b', 'ex', 'power', 'off'])    # 经 fire
assert _pcalls == [('ex', 'off'), ('ex', 'off')], _pcalls

# power 非法 state:手工校验拒绝(fire 无 Literal 校验)
with _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/e.toml'}):
    try:
        _cli.fire.Fire(_cli.Boardctl, ['power', 'bogus'])
        raise AssertionError('非法 power state 应被拒绝')
    except SystemExit as e:
        assert '无效 state' in str(e.code), e.code

# ls 分发
with _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/example.toml'}), \
        _mock.patch.object(_cli, 'load_board', lambda n: {'name': n, 'description': '示例'}):
    with contextlib.redirect_stdout(_io2.StringIO()) as _so:
        _cli.fire.Fire(_cli.Boardctl, ['ls'])
assert 'example' in _so.getvalue(), _so.getvalue()

# 无参数:打印组件帮助,正常返回或退出码 0
with contextlib.redirect_stdout(_io2.StringIO()) as _so:
    try:
        _cli.fire.Fire(_cli.Boardctl, [])
    except SystemExit as e:
        assert e.code in (0, None), e.code
assert 'SYNOPSIS' in _so.getvalue(), _so.getvalue()

# 11. 板卡配置目录:board_dir 直接放 *.toml(~/.config/boardctl,无 boards/ 子目录);
#     $BOARDCTL_BOARDS 指向的目录里直放 toml 即被发现且优先(同名先到先得,
#     不替换后续目录),加载照常合并默认值
with tempfile.TemporaryDirectory() as _td:
    (Path(_td) / 'x.toml').write_text('description = "t"\n[serial]\nurl = "socket://h:1"\n',
                                      encoding='utf-8')
    (Path(_td) / 'y.toml').write_text(
        'description = "旧式"\n[uboot]\nprompt = "ub# "\nload_addr = "0x1"\n',
        encoding='utf-8')
    (Path(_td) / 'z.toml').write_text(
        '[console]\nprompt = "sh$ "\n[uboot]\nprompt = "=>"\n', encoding='utf-8')
    (Path(_td) / 'example.toml').write_text('description = "覆盖同名内置示例"\n',
                                            encoding='utf-8')
    (Path(_td) / 'ignored.txt').write_text('not a board', encoding='utf-8')
    os.environ['BOARDCTL_BOARDS'] = _td
    try:
        _boards = available_boards()
        assert _boards['x'] == str(Path(_td) / 'x.toml'), _boards
        assert _boards['example'] == str(Path(_td) / 'example.toml'), _boards  # 先到先得
        assert 'ignored.txt' not in _boards
        _c = load_board('x')
        assert _c['serial']['url'] == 'socket://h:1'
        assert _c['console']['prompt'] == '=>'       # DEFAULTS 照常合并
        assert 'prompt' not in _c['uboot']           # 提示符已不归 [uboot]
        _c = load_board('y')                         # 旧式:prompt 住 [uboot]
        assert _c['console']['prompt'] == 'ub# '     # 无 [console] 时自动继承
        _c = load_board('z')                         # 两边都有:[console] 优先
        assert _c['console']['prompt'] == 'sh$ '
    finally:
        os.environ.pop('BOARDCTL_BOARDS', None)

print('software tests: OK')
