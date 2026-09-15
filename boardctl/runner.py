"""run 编排:冷启动 -> 传输(插件) -> 执行(插件,流式) -> 断言 -> 收尾;
repeat > 1 时循环多轮(每轮冷启动)并汇总 PASS/FAIL。
CLI(do_run)实时打印;程序化调用用 run_collect(捕获输出,返回结构化结果)"""
import codecs
import contextlib
import io
import os
import re
import select
import sys
import time

from . import power
from .config import BASE_DIR
from .plugins import EXECUTORS, TRANSPORT
from .session import UbootSession

QUIT_BYTE = 0x1C   # 交互模式下退出


def _as_list(v):
    return [v] if isinstance(v, str) else (v or [])


def _positives_satisfied(t, buf):
    """正向断言(expect 子串 + expect_re 正则)是否已全部命中;
    未配置正向断言时返回 False(不以 matched 结束,等提示符/超时)"""
    subs = _as_list(t.get('expect'))
    pats = _as_list(t.get('expect_re'))
    if not subs and not pats:
        return False
    for e in subs:
        if e not in buf:
            return False
    for p in pats:
        if not re.search(p, buf):
            return False
    return True


def _stream_run(ser, cmdline, prompt, t, interactive, timeout):
    """流式执行一条 U-Boot 命令:输出实时打印,结束条件取最先者——
    提示符重现(prompt)/ 正向断言全部命中(matched,非交互)/ 超时(timeout)/
    用户退出(user,Ctrl-\\;仅交互模式)。
    interactive 且 stdin 为 TTY 时进入交互:stdin 原样转发到设备、不限时
    (适合 go/booti 进入内核后继续操作)。返回 (累计输出, 结束原因)。"""
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    ser.write(cmdline.encode() + b'\r')
    buf = ''
    deadline = time.monotonic() + timeout if not (interactive and sys.stdin.isatty()) else None

    raw = False
    if deadline is None:  # 交互模式:raw 终端 + Ctrl-\ 退出
        import termios
        import tty
        old_attrs = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())
        raw = True
        print('\r\n[boardctl] 交互模式:输出实时转发,Ctrl-\\ 退出\r\n',
              end='', flush=True)
    try:
        while True:
            data = ser.read(256)
            if data:
                text = decoder.decode(data)
                print(text, end='', flush=True)
                buf += text

            if prompt and prompt in buf[-256:]:
                return buf, 'prompt'
            if not raw and _positives_satisfied(t, buf):
                return buf, 'matched'

            if raw:
                r, _, _ = select.select([sys.stdin], [], [], 0)
                if r:
                    b = os.read(sys.stdin.fileno(), 1024)
                    if not b or QUIT_BYTE in b:
                        return buf, 'user'
                    ser.write(b)   # 原样转发(含 Ctrl-C,交给设备处理)
            elif deadline is not None and time.monotonic() > deadline:
                return buf, 'timeout'
    finally:
        if raw:
            import termios
            termios.tcdrain(sys.stdin.fileno())
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_attrs)


def evaluate(out, t):
    """断言输出。规则:
    expect     子串列表,必须全部出现(向后兼容)
    expect_re  正则列表,必须全部 re.search 命中
    fail_re    正则列表,必须全部不命中(如 panic/FAIL 自动判负)
    返回 (是否PASS, 问题摘要, 是否配置了断言)
    """
    problems = []
    for e in _as_list(t.get('expect')):
        if e not in out:
            problems.append(f'expect 未出现: {e!r}')
    for p in _as_list(t.get('expect_re')):
        if not re.search(p, out):
            problems.append(f'expect_re 未匹配: {p!r}')
    for p in _as_list(t.get('fail_re')):
        if re.search(p, out):
            problems.append(f'fail_re 命中: {p!r}')
    checked = bool(problems is not None and
                   (_as_list(t.get('expect')) or _as_list(t.get('expect_re'))
                    or _as_list(t.get('fail_re'))))
    return (not problems), '; '.join(problems), checked


def _execute_target(cfg, name, t):
    """执行单轮:冷启动 -> 传输 -> 执行 -> 断言 -> 收尾。
    返回 (expect 判定 bool, 结束原因);未配置断言时 bool 恒 True;基础设施错误直接退出。"""
    if t.get('reset_before'):
        print(f'[{name}] 冷启动(断电->上电->等提示符)', flush=True)
        power.power_cycle_and_wait(cfg)

    path = t['file']
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    if not os.path.isfile(path):
        sys.exit(f'文件不存在: {path}(先构建?)')
    addr = t.get('addr', cfg['uboot']['load_addr'])   # 加载地址
    entry = t.get('entry', addr)                      # 跳转/执行地址,默认与加载地址相同
    method = t.get('method', 'tftp')
    transport = TRANSPORT.get(method)
    if transport is None:
        sys.exit(f'未知传输方式 {method!r},可用: {" ".join(sorted(TRANSPORT)) or "(无)"}')

    print(f'[{name}] 传输 {t["file"]} ({method}) -> {addr}', flush=True)
    if not transport.send(cfg, path, addr):
        sys.exit(1)

    exec_mode = t.get('exec', 'none')
    executor = EXECUTORS.get(exec_mode)
    if executor is None:
        sys.exit(f'未知 exec 方式: {exec_mode}(可用: {" ".join(sorted(EXECUTORS))})')
    cmdline = executor.build_cmd(entry, t)
    if cmdline is None:
        print(f'[{name}] 已加载到 {addr}(exec={exec_mode},未执行)')
        return True, 'loaded'

    timeout = float(t.get('timeout', 15))
    interactive = bool(t.get('interactive'))
    print(f'[{name}] 执行: {cmdline}', flush=True)
    with UbootSession(cfg) as s:
        ok, _ = s.wait_prompt()
        if not ok:
            sys.exit('等待 U-Boot 提示符超时')
        out, ended = _stream_run(s.ser, cmdline, cfg['uboot']['prompt'],
                                 t, interactive, timeout)
    print(f'[{name}] 执行结束({ended})', flush=True)

    ok, detail, checked = evaluate(out, t)
    if checked:
        print(f'[{name}] 结果: {"PASS" if ok else "FAIL"}' + (f'({detail})' if detail else ''),
              flush=True)

    # 收尾:off 断电 | reset 重启回提示符 | none 保持现状(兼容旧的 reset_after 布尔)
    after = t.get('after', 'reset' if t.get('reset_after') else 'none')
    if after == 'off':
        print(f'[{name}] 断电收尾(after=off)', flush=True)
        power.power_off(cfg)
        print(f'[{name}] 已断电', flush=True)
    elif after == 'reset':
        print(f'[{name}] 输出结束,重启回提示符(after=reset)', flush=True)
        power.do_reset(cfg)
    return (ok if checked else True), ended


def do_run(cfg, name, repeat=1):
    """按板卡配置里的 [run.<名字>] 一键启动;repeat>1 时循环并汇总"""
    targets = cfg.get('run', {})
    if not name:
        if not targets:
            sys.exit(f'{cfg["name"]} 配置里没有 [run.*] 启动目标')
        print(f'{cfg["name"]} 可启动目标(boardctl run <名字>):')
        for k, t in targets.items():
            desc = t.get('desc', '')
            print(f'  {k:12} exec={t.get("exec", "none"):8} {t.get("file", "")}  {desc}')
        return
    if name not in targets:
        sys.exit(f'未定义的启动目标 {name!r},可用: {" ".join(targets) or "(无)"}')
    t = dict(targets[name])   # 复制,repeat 注入不污染原配置

    total = max(1, int(repeat))
    if total > 1 and not t.get('reset_before'):
        print(f'[{name}] repeat>1,自动启用 reset_before(每轮冷启动)', flush=True)
        t['reset_before'] = True

    results = []
    for i in range(1, total + 1):
        if total > 1:
            print(f'===== 第 {i}/{total} 轮 =====', flush=True)
        results.append(_execute_target(cfg, name, t)[0])

    if total > 1:
        p = sum(1 for r in results if r)
        print(f'[{name}] 汇总: {p}/{total} 轮 PASS' + (' ✅' if p == total else ' ❌'))
    sys.exit(0 if all(results) else 1)


def run_collect(cfg, name, repeat=1, tail_lines=60):
    """程序化执行 run 目标(MCP/自动化用):捕获输出、不 sys.exit,返回结构化结果。
    stderr 不捕获(留给日志);基础设施错误转为该轮 error 而非抛出。"""
    targets = cfg.get('run', {})
    if name not in targets:
        return {'error': f'未定义的启动目标 {name!r}',
                'available': sorted(targets)}
    t = dict(targets[name])

    total = max(1, int(repeat))
    if total > 1 and not t.get('reset_before'):
        t['reset_before'] = True

    rounds = []
    for i in range(1, total + 1):
        buf = io.StringIO()
        ok, ended, err = False, 'none', None
        try:
            with contextlib.redirect_stdout(buf):
                ok, ended = _execute_target(cfg, name, t)
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
    return {'board': cfg['name'], 'target': name, 'repeat': total,
            'rounds': rounds, 'passed': passed, 'failed': total - passed,
            'all_pass': passed == total}
