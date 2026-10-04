#!/usr/bin/env python3
"""Pure-software smoke tests: no real board/serial/network needed, must run
both in CI and locally"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from boardctl.config import BASE_DIR, available_boards, load_board
from boardctl.plugins import MODE, POWER, TRANSPORT

# 1. plugin registries complete (bring-up belongs to the mode family, [run.*].mode)
assert {'loady', 'tftp'} <= set(TRANSPORT), TRANSPORT
assert {'mijia', 'command'} <= set(POWER), POWER
assert {'uboot', 'console', 'watch'} <= set(MODE), MODE

# 2. cmd template expansion: {addr}/{entry} default chain injected by uboot mode; console mode has no defaults; unknown vars error by name
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
assert expand_cmd('t', 'echo {{not var}}', {}) == 'echo {{not var}}'  # non-variable braces pass through verbatim
assert expand_cmd('t', 'tester {slot}', {'slot': 3}) == 'tester 3'  # console: variables come from target keys
try:
    _expand(_mc, 't', RunTarget(cmd='booti {addr} - {fdt}'))
    raise AssertionError('a cmd with a missing variable should exit with an error')
except SystemExit as e:
    assert 'fdt' in str(e) and 'run.t' in str(e), e
try:
    expand_cmd('t', 'go {addr}', {})   # console has no address default, {addr} is an unknown variable
    raise AssertionError('console mode {addr} should exit with an error')
except SystemExit as e:
    assert 'addr' in str(e) and 'run.t' in str(e), e

# 3. assertion engine evaluate (expect substrings / expect_re regexes / fail_re must not hit)
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

# 4. board config loading + schema defaults (bundled example; config circulates as a BoardCfg model)
boards = available_boards()
assert 'example' in boards, boards
cfg = load_board('example')
assert cfg.loady.sender == ''                          # schema default (single source)
assert cfg.tftp.method == 'remote', cfg.tftp
assert cfg.power.method == 'command', cfg.power
assert cfg.run['hello'].reset_before is True           # the example is fully automatic power on/off

# 5. files referenced by run targets exist (except the example's placeholder paths)
for name, t in cfg.run.items():
    if not t.file:
        continue
    path = t.file
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    assert os.path.isfile(path) or cfg.name == 'example', \
        f'run.{name} file missing: {path}'

# 6. streaming engine: real ConsoleStream threads/watermarks, fake serial as the byte source
import contextlib  # noqa: E402
import threading as _threading  # noqa: E402
import time as _time  # noqa: E402
import io as _io  # noqa: E402

from boardctl import runner as _runner  # noqa: E402
from boardctl.console import ConsoleSession as _RealSession  # noqa: E402
from boardctl.stream import ConsoleStream as _Stream  # noqa: E402


class _FakeSer:
    """Fake serial: empty reads before power_on (power-off silence); after
    power-on emits pending chunks in order, read_delay apart; writes
    recorded. read_delay 0.03: the engine's entry watermark must land before
    the first block arrives."""

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

# fail_re: instant negative verdict (beats positives); fail_linger keeps capturing so error output completes (0 = immediate)
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

# passive watch (cmdline=None): zero writes; end conditions exactly as in active mode
ser = _FakeSer([b'U-Boot 2021.10\r\n', b'autoboot...\r\n', b'soph# '], powered=True)
out, ended = _stream(ser, RunTarget(), cmd=None)
assert ended == 'prompt' and ser.written == b'' and 'U-Boot 2021.10' in out, (ended, out, ser.written)

ser = _FakeSer([b'autoboot\r\n', b'TEST_RUNNER_DONE\r\n', b'never printed'], powered=True)
out, ended = _stream(ser, RunTarget(expect=['TEST_RUNNER_DONE']), cmd=None)
assert ended == 'matched' and ser.written == b'', (ended, ser.written)

ser = _FakeSer([], powered=True)
out, ended = _stream(ser, RunTarget(), cmd=None, timeout=0.2)
assert ended == 'timeout' and ser.written == b'', (ended, ser.written)

# passive full chain (Runner.run): watch takes quiet_boot (cold_boot sends Ctrl-C), zero writes throughout
import unittest.mock as _mock  # noqa: E402

_wser = _FakeSer([b'U-Boot 2021.10\r\n', b'TEST_RUNNER_DONE\r\n', b'soph# '])
_pcalls = []


class _FakeBoard:
    """Board stub: injectable fake serial, real capture stream; records
    which boot path was taken. The stubs mirror the real Board's display
    surface (tap before power-on, detach before power-off, set_display
    sink swap); the fake serial emits only after power_on."""

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

    # display surface (same as the real Board): the tap sink can be swapped for a buffer
    def set_display(self, out):
        self._display = out

    def _show(self, text):
        (self._display if self._display is not None else sys.stdout).write(text)

    def cold_boot(self, boot_timeout=60):
        _pcalls.append('WAIT')
        self.stream.set_tap(self._show)   # attach display before power-on (same as the real Board)
        self.serial.power_on()

    def quiet_boot(self):
        _pcalls.append('quiet')
        self.stream.clear()   # real quiet_boot: clear noise, capture starts at power-on
        self.stream.set_tap(self._show)
        self.serial.power_on()

    def power_off(self):
        _pcalls.append('off')
        self.stream.set_tap(None)   # real Board: detach display first (flush backlog), then power off

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
# passive full chain: finish as soon as expect hits (matched, no waiting for prompt — same as active)
assert ok and ended == 'matched' and _pcalls == ['quiet'], (ok, ended, _pcalls)
assert _wser.written == b'', _wser.written   # zero writes across the whole chain

# console mode full chain: no transport, after cold boot to the prompt execute cmd directly (Linux shell shape)
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
assert _cser.written == b'./selftest.sh\r', _cser.written   # only the command itself is sent

# after=off full chain: power-off finish via the board-domain power_off (detach display, flush backlog, then cut power)
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

# display end-to-end: device output flows into the programmatic sink the
# whole way (after=off flushes the backlog before detaching — no timing luck)
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

# console mode rejects file/method/addr (no transport/address semantics)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 'sh-t',
                       RunTarget(mode='console', cmd='x', file='f.bin',
                                 after='none')).run()
    raise AssertionError('console with file should be rejected')
except SystemExit as e:
    assert 'file' in str(e.code) and 'console' in str(e.code), e.code

# unknown mode gets a clear error (reports whatever the registry has)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 't', RunTarget(mode='gdb', after='none')).run()
    raise AssertionError('an unknown mode should be rejected')
except SystemExit as e:
    assert 'gdb' in str(e.code) and 'uboot' in str(e.code), e.code

# passive mode rejects file (watch doesn't transport, no file semantics)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 'watch-t',
                       RunTarget(mode='watch', file='hello.bin', after='none')).run()
    raise AssertionError('watch with file should be rejected')
except SystemExit as e:
    assert 'file' in str(e.code), e.code

# uboot mode missing file gets a clear error (used to be a bare KeyError)
try:
    with contextlib.redirect_stdout(_io2.StringIO()):
        _runner.Runner(_FakeBoard(_mincfg), 'go-t',
                       RunTarget(cmd='go {addr}', after='none')).run()
    raise AssertionError('an active mode missing file should error out')
except SystemExit as e:
    assert 'file' in str(e.code), e.code

# 6b. resident-capture primitives: watermark/event waiting/clear/fd-lend cooperation (park-resume handshake)
_pser = _FakeSer([b'hello\r\n'], powered=True)
_pst = _Stream(_pser)
_pst.start()
try:
    m = _pst.mark()
    assert _pst.wait(lambda txt: 'hello' in txt, m, 2)[1]      # predicate hit
    _pst.park()                     # returns only after the reader confirms standing down (never reads again after)
    _pser.live = [b'PARKED\n']      # bytes the device emits during the lend: stuck in the channel
    m2 = _pst.mark()
    _time.sleep(0.2)
    assert _pst.text(m2) == ''      # during the lend nothing enters the capture log
    _pst.resume()
    assert _pst.wait(lambda txt: 'PARKED' in txt, m2, 2)[1]     # picks up losslessly after resume
    _pst.clear()                    # clear log and decoder residue (noise clearing before quiet power-on)
    assert _pst.mark() == 0 and _pst.text(0) == ''
    assert _pst.wait(lambda txt: 'never' in txt, 0, 0.05)[1] is False   # the timeout signal isn't lost

    # tap: shown as captured; detach flushes backlog; re-attach doesn't replay;
    # a raising callback doesn't poison the capture thread
    _taplog = []
    _pst.set_tap(_taplog.append)
    _pser.live = [b'tap1\r\n']
    assert _pst.wait(lambda txt: 'tap1' in txt, 0, 2)[1]      # lands in the log
    _pst.set_tap(None)                                        # detach: flush the backlog first
    assert ''.join(_taplog) == 'tap1\r\n', _taplog
    _pser.live = [b'tap2\r\n']                                # while detached: into the log, not displayed
    assert _pst.wait(lambda txt: 'tap2' in txt, 0, 2)[1]
    _pst.set_tap(_taplog.append)                              # re-attach: no replay of tap2
    _pser.live = [b'tap3\r\n']
    assert _pst.wait(lambda txt: 'tap3' in txt, 0, 2)[1]
    _pst.set_tap(None)
    assert ''.join(_taplog) == 'tap1\r\ntap3\r\n', _taplog

    def _bad_tap(_text):
        raise RuntimeError('display blew up — still must not die')

    _pst.set_tap(_bad_tap)
    _pser.live = [b'tap4\r\n']
    assert _pst.wait(lambda txt: 'tap4' in txt, 0, 2)[1]      # the capture thread is still alive
finally:
    _pst.stop()

# multi-byte char split across two reads: an empty decode frame doesn't kill the pump, display/capture lose no characters
_pser2 = _FakeSer([b'h\xc3', b'\xa9llo\r\n'], powered=True)
_pst2 = _Stream(_pser2)
_t2 = []
_pst2.set_tap(_t2.append)
_pst2.start()
try:
    assert _pst2.wait(lambda txt: 'héllo' in txt, 0, 2)[1]
    _pst2.set_tap(None)
    assert ''.join(_t2) == 'héllo\r\n', _t2
finally:
    _pst2.stop()

# 7. power semantic layer imports cleanly
from boardctl import power  # noqa: E402,F401

# 8. tftp staging: external only stages the file (no self-copy regression); local removed with migration guidance
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from boardctl.plugins.transport import tftp as _tftp  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    # 8.1 /proc/net/udp parsing: ports matched in hex
    fake = Path(td) / 'fakeudp'
    fake.write_text('  Sl  local_address            remote_address\n'
                    '   0: 0100007F:0045 00000000:0000 07 00000000:00000000\n'
                    '   1: 00000000:1F90 00000000:0000 07 00000000:00000000\n')
    assert len(_tftp._port_listeners(69, files=(str(fake),))) == 1     # 0x0045
    assert len(_tftp._port_listeners(8080, files=(str(fake),))) == 1   # 0x1F90
    assert _tftp._port_listeners(12345, files=(str(fake),)) == []
    assert _tftp._port_listeners(69, files=()) == []

    # 8.2 external: a file already in the tftp root isn't re-staged; a file elsewhere is copied in
    root = Path(td) / 'srv'
    root.mkdir()
    (root / 'hello.bin').write_bytes(b'BM-TEST')
    outside = Path(td) / 'elsewhere.bin'
    outside.write_bytes(b'OTHER')
    cfg_x = BoardCfg(name='x', tftp=TftpCfg(method='external', local_dir=str(root)))
    _tftp.TftpTransport(cfg_x)._stage_file(str(root / 'hello.bin'))     # in place: no SameFileError
    assert (root / 'hello.bin').read_bytes() == b'BM-TEST'
    _tftp.TftpTransport(cfg_x)._stage_file(str(outside))                # elsewhere: staged into the tftp root
    assert (root / 'elsewhere.bin').read_bytes() == b'OTHER'

    # 8.3 local removed (no self-built TFTP server anymore): leftover configs get migration guidance
    cfg_l = BoardCfg(name='l', tftp=TftpCfg(method='local', local_dir=str(root)))
    try:
        _tftp.TftpTransport(cfg_l)._stage_file(str(root / 'hello.bin'))
        raise AssertionError('method=local should sys.exit (removed)')
    except SystemExit as e:
        assert 'external' in str(e) and 'loady' in str(e), e

# 9. power facade: wraps the plugin, normalizes status to bool/None;
#    mijia prop default 'on', device cache/lock are class attributes
from boardctl import power as _power_mod  # noqa: E402
from boardctl.plugins import POWER as _POWER_REG  # noqa: E402
from boardctl.plugins.power import mijia as _mijia  # noqa: E402

assert _mijia.MijiaPower(BoardCfg(name='m'))._prop() == 'on'                   # default: most sockets
assert _mijia.MijiaPower(BoardCfg(name='m', power=PowerCfg()))._prop() == 'on'
assert _mijia.MijiaPower(BoardCfg(name='m', power=PowerCfg(mijia=MijiaCfg(prop='power'))))._prop() == 'power'


class _FakePowerPlugin:
    """PowerDevice-shaped stub: records on/off calls, status is dialable"""

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
    p.off()   # facade default check=True: exits only on failure; the success path doesn't touch the process
    assert _FakePowerPlugin.calls[-2:] == [True, False], _FakePowerPlugin.calls
    _FakePowerPlugin.state = False
    assert p.status() is False           # the facade normalizes to bool
    _FakePowerPlugin.state = None
    assert p.status() is None            # unparseable passes None through unchanged
finally:
    del _POWER_REG['fake']

# 10. CLI wiring through the real app.meta entry with leaf stubs (do_run/board
#     dirs/Power facade); types are validation; commands callable directly too
from boardctl import cli as _cli  # noqa: E402

_runcalls = []
with _mock.patch.object(_cli, 'do_run',
                        lambda cfg, name: _runcalls.append((cfg.name, name))), \
        _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/example.toml'}), \
        _mock.patch.object(_cli, 'load_board', lambda n: BoardCfg(name=n)):
    # global -b before the subcommand + positional arg
    _cli.app.meta(['-b', 'example', 'run', 'hello'])
    assert _runcalls == [('example', 'hello')], _runcalls
    # -b omitted: auto-selected when there's exactly one user board
    _runcalls.clear()
    _cli.app.meta(['run', 'hello'])
    assert _runcalls == [('example', 'hello')], _runcalls
    # target name omitted = list targets (do_run receives None)
    _runcalls.clear()
    _cli.app.meta(['run'])
    assert _runcalls == [('example', None)], _runcalls
    # all-digit board name delivered as str per the annotation (in the fire era it would be literalized to int, needing a str() fallback)
    _runcalls.clear()
    _cli.app.meta(['-b', '2026', 'run', 'x'])
    assert _runcalls == [('2026', 'x')], _runcalls

# -r/--repeat is retired: multi-round stress runs are shell loops over the
# one-shot flow (tool minimalism); an unknown option still errors at the parse layer
with _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/e.toml'}), \
        _mock.patch.object(_cli, 'load_board', lambda n: BoardCfg(name=n)):
    with contextlib.redirect_stdout(_io2.StringIO()) as _so, \
            contextlib.redirect_stderr(_io2.StringIO()) as _se:
        try:
            _cli.app.meta(['run', 'hello', '-r', '3'])
            raise AssertionError('a retired option should be rejected')
        except SystemExit as e:
            assert e.code not in (0, None), e.code
    assert '-r' in _so.getvalue() + _se.getvalue(), (_so.getvalue(), _se.getvalue())

# multiple user boards and no -b: clear error exit
with _mock.patch.object(_cli, 'available_boards',
                        lambda: {'a': '/x/a.toml', 'b': '/x/b.toml'}):
    try:
        _cli.app.meta(['run'])
        raise AssertionError('multiple boards without -b should error out')
    except SystemExit as e:
        assert 'Specify a board with -b' in str(e.code), e.code

# power dispatch reaches the facade's on/off/status; status prints on/off
_pcalls = []


class _FakeCliPower:
    """Power facade stub: records on/off/status calls (board name via cfg)"""

    desc = 'plugin fake'

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
        _cli.power_ctl('off', cfg=BoardCfg(name='ex'))           # direct function call
        _cli.app.meta(['-b', 'ex', 'power', 'off'])                # via cyclopts
    assert _pcalls == [('ex', 'off'), ('ex', 'off')], _pcalls
    with contextlib.redirect_stdout(_io2.StringIO()) as _so:
        _cli.power_ctl('status', cfg=BoardCfg(name='ex'))        # status prints on/off
    assert _so.getvalue() == 'off\n', _so.getvalue()

# illegal power state: Literal rejected at the parse layer (the in-function manual check remains, guarding programmatic calls)
with _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/e.toml'}):
    with contextlib.redirect_stdout(_io2.StringIO()) as _so, \
            contextlib.redirect_stderr(_io2.StringIO()) as _se:
        try:
            _cli.app.meta(['power', 'bogus'])
            raise AssertionError('an illegal power state should be rejected')
        except SystemExit as e:
            assert e.code not in (0, None), e.code
    assert 'bogus' in _so.getvalue() + _se.getvalue(), (_so.getvalue(), _se.getvalue())

# ls dispatch
with _mock.patch.object(_cli, 'available_boards', lambda: {'example': '/x/example.toml'}), \
        _mock.patch.object(_cli, 'load_board', lambda n: BoardCfg(name=n, description='demo')):
    with contextlib.redirect_stdout(_io2.StringIO()) as _so:
        _cli.app.meta(['ls'])
assert 'example' in _so.getvalue(), _so.getvalue()

# no arguments: prints usage and returns normally; cyclopts reads signatures
# only (no board auto-selection), no mocks needed
with contextlib.redirect_stdout(_io2.StringIO()) as _so:
    _cli.app.meta([])
assert 'Usage' in _so.getvalue(), _so.getvalue()

# 11. config dirs: *.toml directly in the dir; $BOARDCTL_BOARDS takes priority, first dir wins on name collisions
with tempfile.TemporaryDirectory() as _td:
    (Path(_td) / 'x.toml').write_text('description = "t"\n[serial]\nurl = "socket://h:1"\n',
                                      encoding='utf-8')
    (Path(_td) / 'y.toml').write_text(
        'description = "y"\n[console]\nprompt = "ub# "\n[uboot]\nload_addr = "0x1"\n',
        encoding='utf-8')
    (Path(_td) / 'z.toml').write_text(
        '[console]\nprompt = "sh$ "\n', encoding='utf-8')
    (Path(_td) / 'example.toml').write_text('description = "overrides the bundled same-name example"\n',
                                            encoding='utf-8')
    (Path(_td) / 'ignored.txt').write_text('not a board', encoding='utf-8')
    os.environ['BOARDCTL_BOARDS'] = _td
    try:
        _boards = available_boards()
        assert _boards['x'] == str(Path(_td) / 'x.toml'), _boards
        assert _boards['example'] == str(Path(_td) / 'example.toml'), _boards  # first come first served
        assert 'ignored.txt' not in _boards
        _c = load_board('x')
        assert _c.serial.url == 'socket://h:1'
        assert _c.console.prompt == '=>'       # schema default
        assert not hasattr(_c.uboot, 'prompt')  # the prompt belongs to [console] only (UbootCfg has no such field)
        _c = load_board('y')
        assert _c.console.prompt == 'ub# '     # an explicit [console] gives exactly what's configured
        assert _c.uboot.load_addr == '0x1'
        _c = load_board('z')
        assert _c.console.prompt == 'sh$ '
    finally:
        os.environ.pop('BOARDCTL_BOARDS', None)

# 12. config modeling: misspelled/legacy keys, illegal enums/types/constraints
#     error on load; check summarizes per board with a usable exit code
with tempfile.TemporaryDirectory() as _td:
    os.environ['BOARDCTL_BOARDS'] = _td
    try:
        def _toml(body):
            (Path(_td) / 'm.toml').write_text(body, encoding='utf-8')

        _toml('[run.h]\nexpect = ["X"]\ntimeout = 8\n')
        _c = load_board('m')
        assert _c.run['h'].expect == ['X'], _c.run['h']
        assert _c.run['h'].timeout == 8.0                         # int→float coercion
        assert _c.run['h'].after is None, _c.run['h']             # absent means absent (field is None)
        assert _c.run['h'].cmd is None

        _toml('[loady]\nsender = "/opt/sb"\n')
        assert load_board('m').loady.sender == '/opt/sb'          # user value goes straight through

        for _body, _why in [
            ('[run.h]\nexpcet = ["X"]\n', 'misspelled key'),
            ('[run.h]\nafter = "reboot"\n', 'illegal enum'),
            ('[serial]\ntimeout = "abc"\n', 'type error'),
            ('[run.h]\ntimeout = -5\n', 'negative timeout'),
            ('[serial]\nurll = "x"\n', 'unknown key in a core section'),
            ('[run.h]\nexpect = "X"\n', 'scalar assertion (needs a list)'),
            ('[uboot]\nprompt = "soph#"\n', 'legacy prompt (now [console])'),
            ('[run.h]\nexec = "watch"\n', 'legacy exec (now mode)'),
            ('[run.h]\nreset_after = true\n', 'legacy reset_after (now after)'),
        ]:
            _toml(_body)
            try:
                load_board('m')
                raise AssertionError(f'{_why} should be rejected')
            except SystemExit as _e:
                assert 'invalid config' in str(_e), _e

        # check: per-board OK / details + exit 1 (mocked board list, no ~/.config dependence)
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
                    raise AssertionError('check with a bad config should end with exit code 1')
                except SystemExit as _e:
                    assert _e.code == 1, _e.code
        assert 'invalid config' in _so.getvalue() and 'expcet' in _so.getvalue(), _so.getvalue()
    finally:
        os.environ.pop('BOARDCTL_BOARDS', None)

print('software tests: OK')
