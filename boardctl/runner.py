"""run 编排域:Runner 单轮全流程(上电 -> 传输 -> 执行 -> 断言 -> 收尾);
一块板(Board)对应多个 runner——每个 [run.<名>] 目标一个,repeat > 1 时
同一 runner 复跑多轮并汇总。CLI(do_run)实时打印;程序化调用用
run_collect(捕获输出,返回结构化结果)。
目标"怎么弄起来"由启动模式插件族(plugins/mode,[run.*].mode 选择)解释;
流式引擎(_stream_run)与断言引擎(evaluate)是无状态纯函数,所有模式共用
——判定与收尾语义一致由共享代码保证,不靠各插件自觉。"""
import codecs
import contextlib
import io
import os
import re
import select
import sys
import time

from .board import Board
from .plugins import MODE

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


def _fail_hit(t, buf):
    """负向断言 fail_re 是否命中(流式即时判负:一命中就收工,
    不等 timeout——panic 类故障立刻断电止损);明细由 evaluate 统一给出"""
    for p in _as_list(t.get('fail_re')):
        if re.search(p, buf):
            return True
    return False


def _resolve_mode(name, t):
    """目标启动模式:[run.*].mode 显式声明;旧写法 exec="watch" 等价
    mode="watch"(存量配置零改动);缺省 uboot"""
    mode = t.get('mode')
    exec_ = t.get('exec')
    if exec_ is not None and exec_ != 'watch':
        sys.exit(f'无效 exec: {exec_!r}(0.11.0 起执行命令改配 cmd 模板,'
                 '如 cmd = "go {addr}";被动观察改配 mode = "watch")')
    if exec_ == 'watch' and mode is None:
        return 'watch'      # 旧写法,等价 mode = "watch"
    return mode or 'uboot'


def _stream_run(ch, cmdline, prompt, t, interactive, timeout):
    """流式执行一条 U-Boot 命令:输出实时打印,结束条件取最先者——
    提示符重现(prompt)/ fail_re 命中(fail)/ 正向断言全部命中(matched,
    非交互)/ 超时(timeout)/ 用户退出(user,Ctrl-\\;仅交互模式)。
    fail_re 命中后不立即收工:再继续收集 fail_linger 秒(默认 2,可配 0)
    让错误信息/栈输出完整,然后判 FAIL 走收尾;同批输出正负断言双命中时
    判负优先。interactive 且 stdin 为 TTY 时进入交互:stdin 原样转发到
    设备、不限时(适合 go/booti 进入内核后继续操作)。
    cmdline=None 时为被动观察:不向设备发送任何字节,只收流
    (exec=watch——板子自己跑自动流程,任何写入都会打断它)。
    返回 (累计输出, 结束原因)。"""
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    if cmdline is not None:
        ch.write(cmdline.encode() + b'\r')
    buf = ''
    deadline = time.monotonic() + timeout if not (interactive and sys.stdin.isatty()) else None
    fail_deadline = None
    linger = max(0.0, float(t.get('fail_linger', 2)))   # fail 命中后的续收秒数

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
            data = ch.read(256)
            if data:
                text = decoder.decode(data)
                print(text, end='', flush=True)
                buf += text

            if fail_deadline is not None:   # 止损续收窗口:只收输出,不再判定
                if time.monotonic() >= fail_deadline:
                    return buf, 'fail'
                continue

            if prompt and prompt in buf[-256:]:
                return buf, 'prompt'
            if raw:
                r, _, _ = select.select([sys.stdin], [], [], 0)
                if r:
                    b = os.read(sys.stdin.fileno(), 1024)
                    if not b or QUIT_BYTE in b:
                        return buf, 'user'
                    ch.write(b)   # 原样转发(含 Ctrl-C,交给设备处理)
            else:
                if _fail_hit(t, buf):
                    if linger <= 0:
                        return buf, 'fail'
                    fail_deadline = time.monotonic() + linger
                elif _positives_satisfied(t, buf):
                    return buf, 'matched'
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


class Runner:
    """单轮 run 编排:冷启动 -> 传输(插件) -> 执行(cmd 模板,流式) -> 断言 -> 收尾。

    一块板(Board)对应多个 runner——每个 [run.<名>] 目标一个;runner 持有
    板:开机/静默上电/会话经板域,断电收尾经板上的电源域对象(board.power)。
    依赖方向:runner(编排)-> board(板域)-> {power, session/serial}。"""

    def __init__(self, board, name, t):
        self.board = board
        self.cfg = board.cfg
        self.name = name
        self.t = t

    def _finish(self):
        # 收尾:off 断电 | reset 重启回提示符 | none 保持现状(兼容旧的 reset_after 布尔)
        t, name = self.t, self.name
        after = t.get('after', 'reset' if t.get('reset_after') else 'none')
        try:
            if after == 'off':
                print(f'[{name}] 断电收尾(after=off)', flush=True)
                self.board.power.off()
                print(f'[{name}] 已断电', flush=True)
            elif after == 'reset':
                print(f'[{name}] 输出结束,重启回提示符(after=reset)', flush=True)
                self.board.power.reset()
        except Exception as e:   # 收尾失败不掩盖执行阶段的原始异常
            print(f'[{name}] 收尾(after={after})失败: {e}', file=sys.stderr, flush=True)

    def run(self):
        """执行单轮:启动模式插件 launch(上电/传输/命令) -> 流式收输出 ->
        断言 -> 收尾。模式(uboot/console/watch/…)解释目标怎么弄起来,
        流式/断言/收尾全模式共用。收尾(after)放 finally:传输失败、插件
        sys.exit、异常退出同样执行(after=none 语义不变:保持现状);
        返回 (expect 判定 bool, 结束原因);未配置断言时 bool 恒 True;
        基础设施错误直接退出。"""
        cfg, name, t = self.cfg, self.name, self.t
        try:
            mode_name = _resolve_mode(name, t)
            mode = MODE.get(mode_name)
            if mode is None:
                sys.exit(f'未知启动模式 {mode_name!r},可用: {" ".join(sorted(MODE)) or "(无)"}')
            timeout = float(t.get('timeout', 15))
            interactive = bool(t.get('interactive'))
            ch, cmdline, done = mode(cfg).launch(self)   # 特定对象 = 该目标的 runner
            if done is not None:   # launch 已自行收束(如 uboot 只加载不执行)
                return True, done
            out, ended = _stream_run(ch, cmdline, self.board.prompt,
                                     t, interactive, timeout)
            print(f'[{name}] 执行结束({ended})', flush=True)

            ok, detail, checked = evaluate(out, t)
            if checked:
                print(f'[{name}] 结果: {"PASS" if ok else "FAIL"}' + (f'({detail})' if detail else ''),
                      flush=True)
            return (ok if checked else True), ended
        finally:
            self._finish()


def do_run(cfg, name, repeat=1):
    """按板卡配置里的 [run.<名字>] 一键启动;repeat>1 时循环并汇总"""
    targets = cfg.get('run', {})
    if not name:
        if not targets:
            sys.exit(f'{cfg["name"]} 配置里没有 [run.*] 启动目标')
        print(f'{cfg["name"]} 可启动目标(boardctl run <名字>):')
        for k, t in targets.items():
            desc = t.get('desc', '')
            what = t.get('cmd') or t.get('mode') or t.get('exec') or '(只加载)'
            print(f'  {k:12} {what:26} {t.get("file", "")}  {desc}')
        return
    if name not in targets:
        sys.exit(f'未定义的启动目标 {name!r},可用: {" ".join(targets) or "(无)"}')
    t = dict(targets[name])   # 复制,repeat 注入不污染原配置

    total = max(1, int(repeat))
    if total > 1 and not t.get('reset_before'):
        print(f'[{name}] repeat>1,自动启用 reset_before(每轮冷启动)', flush=True)
        t['reset_before'] = True

    with Board(cfg) as board:   # 板持有唯一串口通道,结束时关
        runner = Runner(board, name, t)   # 一块板 ↔ 多个 runner(每目标一个)
        results = []
        for i in range(1, total + 1):
            if total > 1:
                print(f'===== 第 {i}/{total} 轮 =====', flush=True)
            results.append(runner.run()[0])

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

    with Board(cfg) as board:
        runner = Runner(board, name, t)
        rounds = []
        for i in range(1, total + 1):
            buf = io.StringIO()
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
    return {'board': cfg['name'], 'target': name, 'repeat': total,
            'rounds': rounds, 'passed': passed, 'failed': total - passed,
            'all_pass': passed == total}
