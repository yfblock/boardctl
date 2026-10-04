"""Run orchestration: Runner drives the single-round full flow (power-on →
transport → execute → assert → after-handling); one Board maps to many
runners, one per [run.<name>] target. How a target gets brought up belongs
to the mode plugins (plugins/mode, selected via [run.*].mode); the
streaming engine (_stream_run) and the assertion engine (evaluate) are
shared — consistent verdict and after-handling come from that sharing, not
from each plugin's diligence."""
import contextlib
import io
import os
import re
import select
import sys
import time

from .board import Board
from .plugins import MODE

QUIT_BYTE = 0x1C   # quit key in interactive mode


def _positives_satisfied(t, buf):
    """All positive assertions hit; False when none configured (keep waiting
    for prompt/timeout instead of ending as matched)."""
    subs = t.expect
    pats = t.expect_re
    if not subs and not pats:
        return False
    for e in subs:
        if e not in buf:
            return False
    for p in pats:
        if not re.search(p, buf):
            return False
    return True


def _fail_hit(t, buf):
    """Any fail_re hit — instant negative verdict: panic-class faults cut
    power early to limit damage."""
    for p in t.fail_re:
        if re.search(p, buf):
            return True
    return False


def _stream_run(ch, cmdline, prompt, t, interactive, timeout):
    """Stream-execute one command; returns (accumulated output, end reason).

    End reason, first one wins: prompt / fail (fail_re hit; with
    fail_linger>0 keep capturing that long so error output completes — on
    same-batch ties with positives the negative wins) / matched (all
    positives hit) / timeout; interactive adds user (Ctrl-\\, no time
    limit, stdin forwarded raw). cmdline=None is passive capture with zero
    writes (mode=watch). The observation window starts at the entry
    watermark — assertions don't look back."""
    since = ch.mark()
    if cmdline is not None:
        ch.write(cmdline + '\r')

    deadline = None if (interactive and sys.stdin.isatty()) else time.monotonic() + timeout
    fail_deadline = None
    linger = max(0.0, float(2 if t.fail_linger is None else t.fail_linger))   # extra capture after a fail hit
    raw = False

    def _ended(text):
        if prompt and prompt in text[-256:]:
            return True
        return not raw and (_fail_hit(t, text) or _positives_satisfied(t, text))

    if deadline is None:  # interactive mode: raw terminal + Ctrl-\ to quit
        import termios
        import tty
        old_attrs = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())
        raw = True
        print('\r\n[boardctl] interactive mode: output forwarded live, Ctrl-\\ to quit\r\n',
              end='', flush=True)
    try:
        while True:
            if fail_deadline is not None:   # fail-linger window: capture only, no more judging
                ch.wait(lambda _t, fd=fail_deadline: time.monotonic() >= fd,
                        since, max(0.0, fail_deadline - time.monotonic()))
                return ch.text(since), 'fail'
            slice_ = 0.05 if deadline is None else deadline - time.monotonic()
            _, hit = ch.wait(_ended, since, max(0.0, slice_))
            if hit:
                buf = ch.text(since)
                if prompt and prompt in buf[-256:]:
                    return buf, 'prompt'
                if _fail_hit(t, buf):
                    if linger <= 0:
                        return buf, 'fail'
                    fail_deadline = time.monotonic() + linger
                    continue
                return buf, 'matched'
            if deadline is None:   # interactive: reading happens in the capture thread; only forward keys here
                r, _, _ = select.select([sys.stdin], [], [], 0)
                if r:
                    b = os.read(sys.stdin.fileno(), 1024)
                    if not b or QUIT_BYTE in b:
                        return ch.text(since), 'user'
                    ch.write(b)
            else:
                return ch.text(since), 'timeout'
    finally:
        if raw:
            termios.tcdrain(sys.stdin.fileno())
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_attrs)


def evaluate(out, t):
    """Assert on output: expect substrings and expect_re regexes must all
    hit, fail_re regexes must not. Returns (PASS, problem summary, whether
    any assertion was configured)."""
    problems = []
    for e in t.expect:
        if e not in out:
            problems.append(f'expect not seen: {e!r}')
    for p in t.expect_re:
        if not re.search(p, out):
            problems.append(f'expect_re not matched: {p!r}')
    for p in t.fail_re:
        if re.search(p, out):
            problems.append(f'fail_re hit: {p!r}')
    checked = bool(t.expect or t.expect_re or t.fail_re)
    return (not problems), '; '.join(problems), checked


class Runner:
    """One round: mode-plugin launch (power-on/transport/command) → stream
    output in → assert → after-handling. One Board maps to many runners —
    one per [run.<name>] target."""

    def __init__(self, board, name, t):
        self.board = board
        self.cfg = board.cfg
        self.name = name
        self.t = t

    def _finish(self):
        # after-handling: off powers down | reset reboots to the prompt | none keeps state (default)
        t, name = self.t, self.name
        after = t.after or 'none'
        try:
            if after == 'off':
                print(f'[{name}] powering off (after=off)', flush=True)
                self.board.power_off()
                print(f'[{name}] powered off', flush=True)
            elif after == 'reset':
                print(f'[{name}] output done, rebooting to prompt (after=reset)', flush=True)
                self.board.reboot()
        except Exception as e:   # a finish failure must not mask the original execute-phase exception
            print(f'[{name}] after-handling (after={after}) failed: {e}', file=sys.stderr, flush=True)

    def run(self):
        """Run one round via the mode plugin; returns (verdict, end reason).
        With no assertions configured the verdict is always True;
        infrastructure errors exit directly. After-handling sits in finally:
        transport failures and plugin sys.exit run it too (after=none
        semantics unchanged: keep state)."""
        cfg, name, t = self.cfg, self.name, self.t
        try:
            mode_name = t.mode or 'uboot'
            mode = MODE.get(mode_name)
            if mode is None:
                sys.exit(f'unknown boot mode {mode_name!r}, available: {" ".join(sorted(MODE)) or "(none)"}')
            timeout = float(15 if t.timeout is None else t.timeout)
            interactive = bool(t.interactive)
            ch, cmdline, done = mode(cfg).launch(self)
            if done is not None:   # launch concluded itself (e.g. uboot loads without executing)
                return True, done
            out, ended = _stream_run(ch, cmdline, self.board.prompt,
                                     t, interactive, timeout)
            print(f'[{name}] execution ended ({ended})', flush=True)

            ok, detail, checked = evaluate(out, t)
            if checked:
                print(f'[{name}] result: {"PASS" if ok else "FAIL"}' + (f'({detail})' if detail else ''),
                      flush=True)
            return (ok if checked else True), ended
        finally:
            self._finish()


def do_run(cfg, name):
    """One-shot launch per [run.<name>]."""
    targets = cfg.run
    if not name:
        if not targets:
            sys.exit(f'{cfg.name} config has no [run.*] boot targets')
        print(f'{cfg.name} bootable targets (boardctl run <name>):')
        for k, t in targets.items():
            desc = t.desc or ''
            what = t.cmd or t.mode or '(load only)'
            print(f'  {k:12} {what:26} {t.file or ""}  {desc}')
        return
    if name not in targets:
        sys.exit(f'undefined boot target {name!r}, available: {" ".join(targets) or "(none)"}')
    t = targets[name]



    with Board(cfg) as board:   # the board owns the single serial channel; closed on exit
        ok = Runner(board, name, t).run()[0]
    sys.exit(0 if ok else 1)


def run_collect(cfg, name, tail_lines=60):
    """Programmatic run (for MCP/automation): doesn't sys.exit, returns a
    structured result. The display sink is swapped for a buffer — device
    output and orchestration prints all go into it, never landing on the
    caller's stdout (MCP's stdout is a protocol channel); infrastructure
    errors become the result's error instead of raising."""
    targets = cfg.run
    if name not in targets:
        return {'error': f'undefined boot target {name!r}',
                'available': sorted(targets)}
    t = targets[name]



    with Board(cfg) as board:
        buf = io.StringIO()
        board.set_display(buf)
        ok, ended, err = False, 'none', None
        try:
            with contextlib.redirect_stdout(buf):
                ok, ended = Runner(board, name, t).run()
        except SystemExit as e:
            err = str(e.code) if isinstance(e.code, str) else f'exit {e.code}'
    return {'board': cfg.name, 'target': name,
            'pass': bool(ok) and err is None,
            'ended': ended, 'error': err,
            'output_tail': '\n'.join(buf.getvalue().splitlines()[-tail_lines:])}
