"""run orchestration domain: Runner drives the single-round full flow
(power-on -> transport -> execute -> assert -> after-handling). One Board
maps to many runners, one per [run.<name>] target; repeat > 1 re-runs
rounds and summarizes.

Display hangs on capture events (the stream tap, attached before power-on
and detached before power-off by the board domain): the CLI shows
everything as captured from power-on; run_collect swaps the display sink
for a per-round buffer (device bytes never reach the caller's stdout) and
returns a structured result.

How a target gets brought up is the boot-mode family's interpretation
(plugins/mode, selected via [run.*].mode). The streaming engine
(_stream_run: watermarks + event wakeup, see stream.py) and the assertion
engine (evaluate) are shared code — consistent verdict and after-handling
come from that sharing, not from each plugin's diligence."""
import contextlib
import io
import os
import re
import select
import sys
import time

from msgspec.structs import replace

from .board import Board
from .plugins import MODE

QUIT_BYTE = 0x1C   # quit key in interactive mode


def _positives_satisfied(t, buf):
    """Whether all positive assertions (expect substrings + expect_re regexes)
    have hit; returns False when no positive assertions are configured
    (doesn't end as matched — waits for prompt/timeout)"""
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
    """Whether a negative assertion fail_re hit (streaming instant negative
    verdict: wrap up as soon as one hits, don't wait out the timeout —
    panic-class faults cut power immediately to limit damage); details come
    uniformly from evaluate"""
    for p in t.fail_re:
        if re.search(p, buf):
            return True
    return False


def _stream_run(ch, cmdline, prompt, t, interactive, timeout):
    """Stream-execute one command, returning (accumulated output, end reason).

    End reason, first one wins: prompt (prompt reappears) / fail (fail_re hit
    but no immediate wrap-up — keep capturing fail_linger seconds so error
    output completes; when positives and negatives hit in the same batch the
    negative wins) / matched (all positive assertions hit) / timeout;
    interactive mode also has user (Ctrl-\\): stdin is forwarded to the device
    verbatim, no time limit. cmdline=None is passive capture with zero writes
    (mode=watch — writing would interrupt the board's automatic flow).
    Display doesn't live here — the stream tap shows as captured; the
    observation window = the entry watermark, assertions don't look back."""
    since = ch.mark()
    if cmdline is not None:
        ch.write(cmdline + '\r')

    deadline = None if (interactive and sys.stdin.isatty()) else time.monotonic() + timeout
    fail_deadline = None
    linger = max(0.0, float(2 if t.fail_linger is None else t.fail_linger))   # seconds of extra capture after a fail hit
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
            if fail_deadline is not None:   # fail-linger window: capture output only, no more judging
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
            import termios
            termios.tcdrain(sys.stdin.fileno())
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_attrs)


def evaluate(out, t):
    """Assert on output. Rules:
    expect     list of substrings, all must appear
    expect_re  list of regexes, all must re.search-hit
    fail_re    list of regexes, none may hit (e.g. panic/FAIL auto-fail)
    Returns (PASS bool, problem summary, whether any assertion was configured)
    """
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
    """Single-round run orchestration: cold boot -> transport (plugin) ->
    execute (cmd template, streamed) -> assert -> after-handling.

    One Board maps to many runners — one per [run.<name>] target; the runner
    holds the board: power-on/quiet power-on/session go through the board
    domain, power-off finish goes through the power-domain object on the
    board (board.power). Dependency direction: runner (orchestration) ->
    board (board domain) -> {power, session/serial}."""

    def __init__(self, board, name, t):
        self.board = board
        self.cfg = board.cfg
        self.name = name
        self.t = t

    def _finish(self):
        # after-handling: off powers down | reset reboots back to the prompt |
        # none keeps state (default). off/reset go through board-domain methods:
        # the display tap is detached before cutting power (line noise stays off screen)
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
        """Run one round: boot-mode plugin launch (power-on/transport/command)
        -> stream output in -> assert -> after-handling. The mode
        (uboot/console/watch/…) interprets how the target gets brought up;
        streaming/assertions/after-handling are shared across all modes.

        After-handling (after) sits in finally: transport failures, plugin
        sys.exit and exceptional exits run it too (after=none semantics
        unchanged: keep state).

        Returns (expect-verdict bool, end reason); with no assertions
        configured the bool is always True; infrastructure errors exit
        directly."""
        cfg, name, t = self.cfg, self.name, self.t
        try:
            mode_name = t.mode or 'uboot'
            mode = MODE.get(mode_name)
            if mode is None:
                sys.exit(f'unknown boot mode {mode_name!r}, available: {" ".join(sorted(MODE)) or "(none)"}')
            timeout = float(15 if t.timeout is None else t.timeout)
            interactive = bool(t.interactive)
            ch, cmdline, done = mode(cfg).launch(self)   # the specific object = this target's runner
            if done is not None:   # launch already concluded itself (e.g. uboot loads without executing)
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


def do_run(cfg, name, repeat=1):
    """One-shot launch per [run.<name>] in the board config; with repeat>1 loop and summarize"""
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

    total = max(1, int(repeat))
    if total > 1 and not t.reset_before:
        print(f'[{name}] repeat>1, enabling reset_before automatically (cold boot each round)', flush=True)
        t = replace(t, reset_before=True)   # copy-and-inject; the original config stays untouched

    with Board(cfg) as board:   # the board owns the single serial channel; closed on exit
        runner = Runner(board, name, t)   # one board ↔ many runners (one per target)
        results = []
        for i in range(1, total + 1):
            if total > 1:
                print(f'===== round {i}/{total} =====', flush=True)
            results.append(runner.run()[0])

    if total > 1:
        p = sum(1 for r in results if r)
        print(f'[{name}] summary: {p}/{total} rounds PASS' + (' ✅' if p == total else ' ❌'))
    sys.exit(0 if all(results) else 1)


def run_collect(cfg, name, repeat=1, tail_lines=60):
    """Programmatically run a run target (for MCP/automation): captures
    output, doesn't sys.exit, returns a structured result.

    The display sink is swapped for a per-round buffer (board.set_display)
    — device output (tap) and orchestration prints all go into buf, never
    landing on the caller's stdout (MCP's stdout is a protocol channel);
    stderr isn't captured (left for logs); infrastructure errors become
    that round's error instead of raising."""
    targets = cfg.run
    if name not in targets:
        return {'error': f'undefined boot target {name!r}',
                'available': sorted(targets)}
    t = targets[name]

    total = max(1, int(repeat))
    if total > 1 and not t.reset_before:
        t = replace(t, reset_before=True)

    with Board(cfg) as board:
        runner = Runner(board, name, t)
        rounds = []
        for i in range(1, total + 1):
            buf = io.StringIO()
            board.set_display(buf)   # this round's device output (tap display) goes into buf too
            ok, ended, err = False, 'none', None
            try:
                with contextlib.redirect_stdout(buf):
                    ok, ended = runner.run()
            except SystemExit as e:
                err = str(e.code) if isinstance(e.code, str) else f'exit {e.code}'
            output = buf.getvalue()
            rounds.append({
                'round': i,
                'pass': bool(ok) and err is None,
                'ended': ended,
                'error': err,
                'output_tail': '\n'.join(output.splitlines()[-tail_lines:]),
            })
    passed = sum(1 for r in rounds if r['pass'])
    return {'board': cfg.name, 'target': name, 'repeat': total,
            'rounds': rounds, 'passed': passed, 'failed': total - passed,
            'all_pass': passed == total}
