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
from boardctl.schema import (BoardCfg, ConsoleCfg, MijiaCfg,  # noqa: E402
                             PowerCfg, RunTarget, TftpCfg, UbootCfg)

_mc = BoardCfg(name='m', uboot=UbootCfg(load_addr='0x80080000'))
assert _expand(_mc, 't', RunTarget(cmd='go {addr}')) == 'go 0x80080000'
assert _expand(_mc, 't', RunTarget(cmd='source {entry}')) == 'source 0x80080000'
assert _expand(_mc, 't', RunTarget(cmd='go {entry}', entry='0x80090000')) == 'go 0x80090000'
assert _expand(_mc, 't', RunTarget(cmd='booti {addr} - {fdt}', fdt='0x83000000')) \
    == 'booti 0x80080000 - 0x83000000'
assert _expand(_mc, 't', RunTarget(cmd='bootm {addr} {initrd} {fdt}',
                                    initrd='0x82000000', fdt='0x83000000')) \
    == 'bootm 0x80080000 0x82000000 0x83000000'
assert expand_cmd('t', 'echo {{not var}}', {}) == 'echo {{not var}}'  # 非变量花括号原样
assert expand_cmd('t', 'tester {slot}', {'slot': 3}) == 'tester 3'  # console:变量取目标键
try:
    _expand(_mc, 't', RunTarget(cmd='booti {addr} - {fdt}'))
    raise AssertionError('cmd 缺变量应报错退出')
except SystemExit as e:
    assert 'fdt' in str(e) and 'run.t' in str(e), e
try:
    expand_cmd('t', 'go {addr}', {})   # console 无地址缺省,{addr} 即未知变量
    raise AssertionError('console 模式 {addr} 应报错退出')
except SystemExit as e:
    assert 'addr' in str(e) and 'run.t' in str(e), e

# 3. 断言引擎 evaluate(expect 子串 / expect_re 正则 / fail_re 禁止命中)
from boardctl.runner import evaluate  # noqa: E402

ok, detail, checked = evaluate('hello PASS world', RunTarget(expect=['PASS']))
assert ok and checked and detail == ''
ok, detail, _ = evaluate('abc', RunTarget(expect=['PASS']))
assert not ok and 'PASS' in detail
ok, _, _ = evaluate('Kernel panic - not syncing', RunTarget(expect_re=[r'(?i)panic']))
assert ok
ok, detail, _ = evaluate('Starting kernel', RunTarget(expect_re=[r'(?i)panic']))
assert not ok
ok, detail, _ = evaluate('kernel panic here', RunTarget(fail_re=['panic']))
assert not ok and 'fail_re' in detail
ok, detail, checked = evaluate('anything', RunTarget())
assert ok and not checked

# 4. 板卡配置加载 + schema 默认值(用包内置通用示例验证,不依赖个人环境;
#    配置以 BoardCfg 模型对象流通)
boards = available_boards()
assert 'example' in boards, boards
cfg = load_board('example')
assert cfg.loady.sender == ''                          # schema 默认值(单一来源)
assert cfg.tftp.method == 'remote', cfg.tftp
assert cfg.power.method == 'command', cfg.power
assert cfg.run['hello'].reset_before is True           # 示例即全自动开关机

# 5. run 目标引用的文件真实存在(示例模板的占位路径除外;
#    watch 等被动目标无 file——板子自己获取)
for name, t in cfg.run.items():
    if not t.file:
        continue
    path = t.file
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    assert os.path.isfile(path) or cfg.name == 'example', \
        f'run.{name} 文件缺失: {path}'

# 6. 流式执行引擎(常驻捕获:ConsoleStream 读线程 + 水位等待;伪串口注入,
#    线程/条件变量/水位全是真实实现,只换字节来源)
import contextlib  # noqa: E402
import threading as _threading  # noqa: E402
import time as _time  # noqa: E402
import io as _io  # noqa: E402

from boardctl import runner as _runner  # noqa: E402
from boardctl.console import ConsoleSession as _RealSession  # noqa: E402
from boardctl.stream import ConsoleStream as _Stream  # noqa: E402


class _FakeSer:
    """伪串口:上电(power_on)前读恒空(模拟断电静默);上电后按序吐
    chunks,块间 read_delay 秒;记录写入。引擎入口才打水位——有意义的首块
    必须晚于水位,read_delay 0.03 即为此裕量"""

    def __init__(self, chunks=(), powered=False, read_delay=0.03):
        self.pending = list(chunks)
        self.live = list(chunks) if powered else []
        self.read_delay = read_delay
        self.written = b''
        self._lock = _threading.Lock()

    def read(self, n):
        _time.sleep(self.read_delay)
        with self._lock:
            return self.live.pop(0) if self.live else b''

    def write(self, b):
        self.written += b

    def power_on(self):
        with self._lock:
            self.live = list(self.pending)


def _stream(ser, t, **kw):
    st = _Stream(ser)
    st.start()
    try:
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            return _runner._stream_run(st, kw.get('cmd', 'go x'), kw.get('prompt', 'soph#'),
                                       t, False, kw.get('timeout', 1.0))
    finally:
        st.stop()


out, ended = _stream(_FakeSer([b'BM-TEST-START\nBM-TEST-DONE\n'], powered=True),
                     RunTarget(expect=['BM-TEST-START', 'BM-TEST-DONE']))
assert ended == 'matched' and 'BM-TEST-DONE' in out, (ended, out)

out, ended = _stream(_FakeSer([b'output line\r\nsoph# '], powered=True), RunTarget())
assert ended == 'prompt', ended

out, ended = _stream(_FakeSer([], powered=True), RunTarget(), timeout=0.3)
assert ended == 'timeout', ended

out, ended = _stream(_FakeSer([b'kernel booting...'], powered=True), RunTarget(), timeout=0.3)
assert ended == 'timeout' and 'kernel booting' in out, (ended, out)

# fail_re 流式即时命中(判负优先于判正);命中后先续收 fail_linger 秒再收工,
# 让错误信息/栈输出完整(默认 2s,0 = 立即)
out, ended = _stream(_FakeSer([b'boot ok\n', b'thread panicked at root.rs:401\n', b'never reached'],
                              powered=True),
                     RunTarget(expect=['TEST_RUNNER_DONE'], fail_re=['(?i)panic'], fail_linger=0.3))
assert ended == 'fail' and 'panicked' in out and 'never reached' in out, (ended, out)

out, ended = _stream(_FakeSer([b'boot ok\n', b'thread panicked at root.rs:401\n', b'never reached'],
                              powered=True),
                     RunTarget(expect=['TEST_RUNNER_DONE'], fail_re=['(?i)panic'], fail_linger=0))
assert ended == 'fail' and 'never reached' not in out, (ended, out)

out, ended = _stream(_FakeSer([b'DONE\npanic!\n'], powered=True),
                     RunTarget(expect=['DONE'], fail_re=['panic'], fail_linger=0))
assert ended == 'fail', ended

# 被动观察(cmdline=None):零写入(连命令行回车都不发),输出照收、
# 结束条件(断言命中/提示符/超时/fail_re)与主动模式完全一致
ser = _FakeSer([b'U-Boot 2021.10\r\n', b'autoboot...\r\n', b'soph# '], powered=True)
out, ended = _stream(ser, RunTarget(), cmd=None)
assert ended == 'prompt' and ser.written == b'' and 'U-Boot 2021.10' in out, (ended, out, ser.written)

ser = _FakeSer([b'autoboot\r\n', b'TEST_RUNNER_DONE\r\n', b'never printed'], powered=True)
out, ended = _stream(ser, RunTarget(expect=['TEST_RUNNER_DONE']), cmd=None)
assert ended == 'matched' and ser.written == b'', (ended, ser.written)

ser = _FakeSer([], powered=True)
out, ended = _stream(ser, RunTarget(), cmd=None, timeout=0.2)
assert ended == 'timeout' and ser.written == b'', (ended, ser.written)

# 被动目标整链路(Runner.run):mode=watch 走静默上电分支
# (不碰 Board.cold_boot——那个会发 Ctrl-C)、全程零写入、断言照常
import unittest.mock as _mock  # noqa: E402

_wser = _FakeSer([b'U-Boot 2021.10\r\n', b'TEST_RUNNER_DONE\r\n', b'soph# '])
_pcalls = []


class _FakeBoard:
    """Board 桩:serial 即伪串口(可注入),捕获流是真的;记录冷启动走哪条
    路径(after=none 时 power 不触)。冷启动/静默上电/断电收尾的桩顺带
    模拟上电,并镜像真实 Board 的显示面(tap 上电前挂、断电前摘、
    set_display 换程序化出口)——伪串口只有 power_on 后才吐字节"""

    def __init__(self, cfg, ser=None):
        self.cfg = cfg
        self.power = None
        self.serial = ser or _wser
        self.stream = _Stream(self.serial)
        self._display = None

    @property
    def prompt(self):
        return self.cfg.console.prompt

    def session(self):
        return _RealSession(self.stream, self.cfg.console.prompt)

    # 显示面(与真实 Board 同款):tap 出口可换成缓冲
    def set_display(self, out):
        self._display = out

    def _show(self, text):
        (self._display if self._display is not None else sys.stdout).write(text)

    def cold_boot(self, boot_timeout=60):
        _pcalls.append('WAIT')
        self.stream.set_tap(self._show)   # 上电前挂显示(真实 Board 同款)
        self.serial.power_on()

    def quiet_boot(self):
        _pcalls.append('quiet')
        self.stream.clear()   # 真实 quiet_boot:清噪,捕获起点 = 上电
        self.stream.set_tap(self._show)
        self.serial.power_on()

    def power_off(self):
        _pcalls.append('off')
        self.stream.set_tap(None)   # 真实 Board:先摘显示(放完积压)再断电

    def reboot(self):
        _pcalls.append('reboot')
        self.stream.set_tap(None)
        self.serial.power_on()


_mincfg = BoardCfg(name='fake', console=ConsoleCfg(prompt='soph#'))
import io as _io2  # noqa: E402

_wb = _FakeBoard(_mincfg)
_wb.stream.start()
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        ok, ended = _runner.Runner(_wb, 'watch-t',
                                   RunTarget(mode='watch', reset_before=True,
                                             after='none', timeout=1.0,
                                             expect=['TEST_RUNNER_DONE'])).run()
finally:
    _wb.stream.stop()
# 被动整链路:expect 一命中即收工(matched,不等提示符——与主动模式一致)
assert ok and ended == 'matched' and _pcalls == ['quiet'], (ok, ended, _pcalls)
assert _wser.written == b'', _wser.written   # 整链路零写入

# console 模式整链路:不传输,冷启动到提示符后直接执行 cmd(Linux shell 形态)
_pcalls.clear()
_cser = _FakeSer([b'ALL PASS\r\n', b'soph# '])
_cb = _FakeBoard(_mincfg, _cser)
_cb.stream.start()
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        ok, ended = _runner.Runner(_cb, 'sh-t',
                                   RunTarget(mode='console', cmd='./selftest.sh',
                                             reset_before=True, after='none',
                                             timeout=1.0, expect=['ALL PASS'])).run()
finally:
    _cb.stream.stop()
assert ok and ended == 'matched' and _pcalls == ['WAIT'], (ok, ended, _pcalls)
assert _cser.written == b'./selftest.sh\r', _cser.written   # 只发命令本身

# after=off 整链:断电收尾经板域 power_off(先摘显示、放完积压再断电)
_pcalls.clear()
_offser = _FakeSer([b'out line\r\n', b'soph# '])
_ob = _FakeBoard(_mincfg, _offser)
_ob.stream.start()
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        ok, ended = _runner.Runner(_ob, 'off-t',
                                   RunTarget(mode='watch', reset_before=True,
                                             after='off', timeout=1.0)).run()
finally:
    _ob.stream.stop()
assert ended == 'prompt' and _pcalls == ['quiet', 'off'], (ended, _pcalls)

# 显示端到端:挂在捕获事件上——静默上电起的设备输出全程进程序化出口
# (set_display 换缓冲;after=off 摘 tap 前放完积压,SPL 与断言句都在,
# 不靠显示回调与谓词命中的时序运气)
_pcalls.clear()
_dser = _FakeSer([b'SPL banner\r\n', b'TEST_RUNNER_DONE\r\n'])
_db = _FakeBoard(_mincfg, _dser)
_dbuf = _io2.StringIO()
_db.set_display(_dbuf)
_db.stream.start()
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        ok, ended = _runner.Runner(_db, 'disp-t',
                                   RunTarget(mode='watch', reset_before=True,
                                             after='off', timeout=1.0,
                                             expect=['TEST_RUNNER_DONE'])).run()
finally:
    _db.stream.stop()
assert ok and ended == 'matched', (ok, ended)
assert 'SPL banner' in _dbuf.getvalue() and 'TEST_RUNNER_DONE' in _dbuf.getvalue(), \
    _dbuf.getvalue()
assert _pcalls == ['quiet', 'off'], _pcalls

# console 模式拒绝 file/method/addr(无传输/地址语义)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 'sh-t',
                       RunTarget(mode='console', cmd='x', file='f.bin',
                                 after='none')).run()
    raise AssertionError('console 带 file 应被拒绝')
except SystemExit as e:
    assert 'file' in str(e.code) and 'console' in str(e.code), e.code

# 未知模式给明确报错(注册表里有什么就报什么)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 't', RunTarget(mode='gdb', after='none')).run()
    raise AssertionError('未知 mode 应被拒绝')
except SystemExit as e:
    assert 'gdb' in str(e.code) and 'uboot' in str(e.code), e.code

# 被动模式拒绝 file(watch 不传输,无文件语义)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 'watch-t',
                       RunTarget(mode='watch', file='hello.bin', after='none')).run()
    raise AssertionError('watch 带 file 应被拒绝')
except SystemExit as e:
    assert 'file' in str(e.code), e.code

# uboot 模式缺 file 给明确报错(此前是裸 KeyError)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 'go-t',
                       RunTarget(cmd='go {addr}', after='none')).run()
    raise AssertionError('主动模式缺 file 应报错')
except SystemExit as e:
    assert 'file' in str(e.code), e.code

# 6b. 常驻捕获原语:水位/事件等待/清零/fd 借出配合(park-resume 握手)
_pser = _FakeSer([b'hello\r\n'], powered=True)
_pst = _Stream(_pser)
_pst.start()
try:
    m = _pst.mark()
    assert _pst.wait(lambda txt: 'hello' in txt, m, 2)[1]      # 谓词命中
    _pst.park()                     # 读线程确认让位后才返回(此后绝不再读)
    _pser.live = [b'PARKED\n']      # 借出期间设备吐的字节:滞留通道
    m2 = _pst.mark()
    _time.sleep(0.2)
    assert _pst.text(m2) == ''      # 借出期间不进捕获日志
    _pst.resume()
    assert _pst.wait(lambda txt: 'PARKED' in txt, m2, 2)[1]     # resume 后无损接上
    _pst.clear()                    # 清日志与解码残态(静默上电前清噪)
    assert _pst.mark() == 0 and _pst.text(0) == ''
    assert _pst.wait(lambda txt: 'never' in txt, 0, 0.05)[1] is False   # 超时信号不丢

    # tap(显示回调):捕到即显(读线程异步);摘下前放完积压(显示无缺口,
    # 不靠时序运气);重挂不回放摘下期间的字节;回调抛异常不毒害捕获线程
    _taplog = []
    _pst.set_tap(_taplog.append)
    _pser.live = [b'tap1\r\n']
    assert _pst.wait(lambda txt: 'tap1' in txt, 0, 2)[1]      # 进日志
    _pst.set_tap(None)                                        # 摘:先放完积压
    assert ''.join(_taplog) == 'tap1\r\n', _taplog
    _pser.live = [b'tap2\r\n']                                # 摘下期间:进日志不显示
    assert _pst.wait(lambda txt: 'tap2' in txt, 0, 2)[1]
    _pst.set_tap(_taplog.append)                              # 重挂:不回放 tap2
    _pser.live = [b'tap3\r\n']
    assert _pst.wait(lambda txt: 'tap3' in txt, 0, 2)[1]
    _pst.set_tap(None)
    assert ''.join(_taplog) == 'tap1\r\ntap3\r\n', _taplog

    def _bad_tap(_text):
        raise RuntimeError('显示炸了也不许死')

    _pst.set_tap(_bad_tap)
    _pser.live = [b'tap4\r\n']
    assert _pst.wait(lambda txt: 'tap4' in txt, 0, 2)[1]      # 捕获线程仍活着
finally:
    _pst.stop()

# 多字节字符拆在两次 read 之间:空解码帧不炸泵,显示/捕获都不丢字
_pser2 = _FakeSer([b'\xe4\xb8', b'\xad\xe6\x96\x87\r\n'], powered=True)
_pst2 = _Stream(_pser2)
_t2 = []
_pst2.set_tap(_t2.append)
_pst2.start()
try:
    assert _pst2.wait(lambda txt: '中文' in txt, 0, 2)[1]
    _pst2.set_tap(None)
    assert ''.join(_t2) == '中文\r\n', _t2
finally:
    _pst2.stop()

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
    cfg_x = BoardCfg(name='x', tftp=TftpCfg(method='external', local_dir=str(root)))
    _tftp.TftpTransport(cfg_x)._stage_file(str(root / 'hello.bin'))     # 原地:不抛 SameFileError
    assert (root / 'hello.bin').read_bytes() == b'BM-TEST'
    _tftp.TftpTransport(cfg_x)._stage_file(str(outside))                # 异地:落盘进 tftp 根
    assert (root / 'elsewhere.bin').read_bytes() == b'OTHER'

    # 8.3 local 已移除(不再自建 TFTP 服务器):残留配置报迁移指引
    cfg_l = BoardCfg(name='l', tftp=TftpCfg(method='local', local_dir=str(root)))
    try:
        _tftp.TftpTransport(cfg_l)._stage_file(str(root / 'hello.bin'))
        raise AssertionError('method=local 应 sys.exit 退出(已移除)')
    except SystemExit as e:
        assert 'external' in str(e) and 'loady' in str(e), e

# 9. 电源:插件即类(PowerDevice 子类,多态同接口),域门面 Power 也是类
#    (包住插件实例,统一错误包装;节拍值 reset_delay 住域内,节拍编排在
#    板域——显示 tap 要挂在上电前);mijia 开关量属性名
#    可配(默认 on),设备缓存/锁是插件类属性(封装,跨实例共享)
from boardctl import power as _power_mod  # noqa: E402
from boardctl.plugins import POWER as _POWER_REG  # noqa: E402
from boardctl.plugins.power import mijia as _mijia  # noqa: E402

assert _mijia.MijiaPower(BoardCfg(name='m'))._prop() == 'on'                   # 缺省:多数插座
assert _mijia.MijiaPower(BoardCfg(name='m', power=PowerCfg()))._prop() == 'on'
assert _mijia.MijiaPower(BoardCfg(name='m', power=PowerCfg(mijia=MijiaCfg(prop='power'))))._prop() == 'power'


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
    _fcfg = BoardCfg(name='fake', power=PowerCfg(method='fake'))
    p = _power_mod.Power(_fcfg)
    p.on()
    p.off()   # 门面默认 check=True:失败才退出;成功路径不碰进程
    assert _FakePowerPlugin.calls[-2:] == [True, False], _FakePowerPlugin.calls
    _FakePowerPlugin.state = False
    assert p.status() is False           # 门面归一为 bool
    _FakePowerPlugin.state = None
    assert p.status() is None            # 无法解析时原样透传 None
finally:
    del _POWER_REG['fake']

# 10. CLI 接线(cyclopts):类型即校验(repeat:int、power state:Literal,
#     解析层拦截非法值),全局 -b 经 meta 入口前置;走 app.meta 真实入口,
#     叶子打桩(do_run/板卡目录/Power 门面),不碰文件系统与硬件。
#     命令函数即业务,也可绕过 CLI 层直调(cfg 作普通参数传入)
from boardctl import cli as _cli  # noqa: E402

_runcalls = []
with _mock.patch.object(_cli, 'do_run',
                        lambda cfg, name, repeat=1: _runcalls.append((cfg.name, name, repeat))), \
        _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/example.toml'}), \
        _mock.patch.object(_cli, 'load_board', lambda n: BoardCfg(name=n)):
    # 全局 -b 前置于子命令 + 位置参数 + 短旗标 -r(cyclopts 按 int 注解交付)
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
    # 纯数字板名按注解交付 str(fire 时代会被字面量化成 int,需 str() 兜底)
    _runcalls.clear()
    _cli.app.meta(['-b', '2026', 'run', 'x'])
    assert _runcalls == [('2026', 'x', 1)], _runcalls

# 非法 repeat:cyclopts 解析层拦截,报错文案带原值(退出码属框架约定,
# 只断非零不断具体码——0.10.0 教训:别断言 CLI 框架的退出码)
with _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/e.toml'}), \
        _mock.patch.object(_cli, 'load_board', lambda n: BoardCfg(name=n)):
    with contextlib.redirect_stdout(_io2.StringIO()) as _so, \
            contextlib.redirect_stderr(_io2.StringIO()) as _se:
        try:
            _cli.app.meta(['run', 'hello', '-r', 'abc'])
            raise AssertionError('非法 repeat 应被拒绝')
        except SystemExit as e:
            assert e.code not in (0, None), e.code
    assert 'abc' in _so.getvalue() + _se.getvalue(), (_so.getvalue(), _se.getvalue())

# 多块用户板且未 -b:明确报错退出
with _mock.patch.object(_cli, 'available_boards',
                        lambda: {'a': '/x/a.toml', 'b': '/x/b.toml'}):
    try:
        _cli.app.meta(['run'])
        raise AssertionError('多板未指定 -b 应报错退出')
    except SystemExit as e:
        assert '请用 -b' in str(e.code), e.code

# power 分发:state 与板卡配置送抵 Power 门面的 on/off/status
#    (子命令编排住 cli:status 打印开/关,on/off 前的提示行照打)
_pcalls = []


class _FakeCliPower:
    """Power 门面桩:记录 on/off/status 调用(板名经 cfg)"""

    desc = '插件 fake'

    def __init__(self, cfg):
        self.cfg = cfg

    def on(self):
        _pcalls.append((self.cfg.name, 'on'))

    def off(self):
        _pcalls.append((self.cfg.name, 'off'))

    def status(self):
        _pcalls.append((self.cfg.name, 'status'))
        return False


with _mock.patch.object(_cli, 'load_board', lambda n: BoardCfg(name=n)), \
        _mock.patch.object(_cli.power, 'Power', _FakeCliPower):
    with contextlib.redirect_stdout(_io2.StringIO()):
        _cli.power_ctl('off', cfg=BoardCfg(name='ex'))           # 直调函数
        _cli.app.meta(['-b', 'ex', 'power', 'off'])                # 经 cyclopts
    assert _pcalls == [('ex', 'off'), ('ex', 'off')], _pcalls
    with contextlib.redirect_stdout(_io2.StringIO()) as _so:
        _cli.power_ctl('status', cfg=BoardCfg(name='ex'))        # status 打印开/关
    assert _so.getvalue() == '关\n', _so.getvalue()

# 非法 power state:Literal 在解析层拒绝(方法内手工校验仍在,兜程序化调用)
with _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/e.toml'}):
    with contextlib.redirect_stdout(_io2.StringIO()) as _so, \
            contextlib.redirect_stderr(_io2.StringIO()) as _se:
        try:
            _cli.app.meta(['power', 'bogus'])
            raise AssertionError('非法 power state 应被拒绝')
        except SystemExit as e:
            assert e.code not in (0, None), e.code
    assert 'bogus' in _so.getvalue() + _se.getvalue(), (_so.getvalue(), _se.getvalue())

# ls 分发
with _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/example.toml'}), \
        _mock.patch.object(_cli, 'load_board', lambda n: BoardCfg(name=n, description='示例')):
    with contextlib.redirect_stdout(_io2.StringIO()) as _so:
        _cli.app.meta(['ls'])
assert 'example' in _so.getvalue(), _so.getvalue()

# 无参数:打印用法帮助并正常返回(result_action=return_value,不退码)。
# cyclopts 帮助只看签名不求值成员——fire 时代 inspect.getmembers 会求值
# cfg 属性触发自动选板,测试被迫 mock"恰好一块板"(CI 曾因此红),
# 该脆弱性随引擎更换消失,无需任何 mock
with contextlib.redirect_stdout(_io2.StringIO()) as _so:
    _cli.app.meta([])
assert 'Usage' in _so.getvalue(), _so.getvalue()

# 11. 板卡配置目录:board_dir 直接放 *.toml(~/.config/boardctl,无 boards/ 子目录);
#     $BOARDCTL_BOARDS 指向的目录里直放 toml 即被发现且优先(同名先到先得,
#     不替换后续目录),加载照常走 schema 校验与默认值
with tempfile.TemporaryDirectory() as _td:
    (Path(_td) / 'x.toml').write_text('description = "t"\n[serial]\nurl = "socket://h:1"\n',
                                      encoding='utf-8')
    (Path(_td) / 'y.toml').write_text(
        'description = "y"\n[console]\nprompt = "ub# "\n[uboot]\nload_addr = "0x1"\n',
        encoding='utf-8')
    (Path(_td) / 'z.toml').write_text(
        '[console]\nprompt = "sh$ "\n', encoding='utf-8')
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
        assert _c.serial.url == 'socket://h:1'
        assert _c.console.prompt == '=>'       # schema 默认值
        assert not hasattr(_c.uboot, 'prompt')  # 提示符只归 [console](UbootCfg 无此字段)
        _c = load_board('y')
        assert _c.console.prompt == 'ub# '     # 显式 [console] 即所配即所得
        assert _c.uboot.load_addr == '0x1'
        _c = load_board('z')
        assert _c.console.prompt == 'sh$ '
    finally:
        os.environ.pop('BOARDCTL_BOARDS', None)

# 12. 配置建模(msgspec):加载即校验——拼错的键/旧式键/非法枚举/类型/约束
#     当场报错且带字段路径;缺省即缺省(字段值为 None,消费端判 None 取
#     自己的默认);插件段同样建模校验;check 子命令按板汇总、退出码可用
with tempfile.TemporaryDirectory() as _td:
    os.environ['BOARDCTL_BOARDS'] = _td
    try:
        def _toml(body):
            (Path(_td) / 'm.toml').write_text(body, encoding='utf-8')

        _toml('[run.h]\nexpect = ["X"]\ntimeout = 8\n')
        _c = load_board('m')
        assert _c.run['h'].expect == ['X'], _c.run['h']
        assert _c.run['h'].timeout == 8.0                         # int→float 强转
        assert _c.run['h'].after is None, _c.run['h']             # 缺省即缺省(字段为 None)
        assert _c.run['h'].cmd is None

        _toml('[loady]\nsender = "/opt/sb"\n')
        assert load_board('m').loady.sender == '/opt/sb'          # 用户值直达

        for _body, _why in [
            ('[run.h]\nexpcet = ["X"]\n', '拼错的键'),
            ('[run.h]\nafter = "reboot"\n', '非法枚举'),
            ('[serial]\ntimeout = "abc"\n', '类型错误'),
            ('[run.h]\ntimeout = -5\n', '负超时'),
            ('[serial]\nurll = "x"\n', '核心段未知键'),
            ('[run.h]\nexpect = "X"\n', '断言标量(须列表)'),
            ('[uboot]\nprompt = "soph#"\n', '旧式 prompt(现归 [console])'),
            ('[run.h]\nexec = "watch"\n', '旧式 exec(现归 mode)'),
            ('[run.h]\nreset_after = true\n', '旧式 reset_after(现归 after)'),
        ]:
            _toml(_body)
            try:
                load_board('m')
                raise AssertionError(f'{_why}应被拒绝')
            except SystemExit as _e:
                assert '配置无效' in str(_e), _e

        # check 子命令:好配置逐板 OK、退出码 0;坏配置逐板报明细、退出码 1
        # (mock 板列表保持封闭:不依赖本机 ~/.config 里恰好有什么配置)
        _toml('[run.h]\nexpect = ["X"]\n')
        with _mock.patch.object(_cli, 'available_boards',
                                lambda: {'m': str(Path(_td) / 'm.toml')}):
            with contextlib.redirect_stdout(_io2.StringIO()) as _so:
                try:
                    _cli.check()
                    _code = 0
                except SystemExit as _e:
                    _code = _e.code
        assert _code in (0, None), _code
        assert 'm: OK' in _so.getvalue(), _so.getvalue()
        _toml('[run.h]\nexpcet = ["X"]\n')
        with _mock.patch.object(_cli, 'available_boards',
                                lambda: {'m': str(Path(_td) / 'm.toml')}):
            with contextlib.redirect_stdout(_io2.StringIO()) as _so:
                try:
                    _cli.check()
                    raise AssertionError('坏配置 check 应以退出码 1 结束')
                except SystemExit as _e:
                    assert _e.code == 1, _e.code
        assert '配置无效' in _so.getvalue() and 'expcet' in _so.getvalue(), _so.getvalue()
    finally:
        os.environ.pop('BOARDCTL_BOARDS', None)

print('software tests: OK')
