"""命令行入口:极简命令面——run(一键全流程)+ ls(列表)"""
import argparse
import os
import signal
import sys

from . import power
from .config import BUNDLED_BOARDS_DIR, available_boards, load_board
from .runner import do_run


class _Interrupted(BaseException):
    """SIGTERM 等信号转成的可捕获中断"""


def _ensure_power_off(cfg):
    """打断善后:板在开机状态则执行一次关机,保证程序结束后设备是关的"""
    print('\n[boardctl] 程序被打断,执行关机保证...', file=sys.stderr, flush=True)
    try:
        state = power.power_status(cfg)
    except SystemExit:
        state = None
    if state is False:
        return  # 本来就是关的
    if not power.power_off(cfg, check=False):
        print('[boardctl] 自动关机失败,请手动确认电源状态', file=sys.stderr)


def _run_guarded(cfg, args):
    """带打断关机保证的 run:Ctrl-C/SIGTERM/异常退出时若板开机则关机"""
    def _on_signal(signum, _frame):
        raise _Interrupted(f'signal {signum}')

    old_term = signal.signal(signal.SIGTERM, _on_signal)
    try:
        do_run(cfg, args.name, repeat=args.repeat)
    except (KeyboardInterrupt, _Interrupted):
        _ensure_power_off(cfg)
        sys.exit(130)
    except Exception:
        _ensure_power_off(cfg)
        raise
    finally:
        signal.signal(signal.SIGTERM, old_term)


def main():
    ap = argparse.ArgumentParser(
        prog='boardctl',
        description='开发板控制工具:一键全流程(冷启动→传输→执行→断言→收尾),'
                    '板卡与启动目标配置见 ~/.config/boardctl/boards,插件化传输/执行/电源')
    ap.add_argument('-b', '--board', default=None,
                    help='开发板名(缺省:仅一块用户板卡时自动选中)')
    sub = ap.add_subparsers(dest='op', required=True)

    p_run = sub.add_parser('run', help='一键全流程启动(目标配置于 [run.<名字>])')
    p_run.add_argument('name', nargs='?', help='启动目标名(省略则列出可用目标)')
    p_run.add_argument('--repeat', '-r', type=int, default=1, metavar='N',
                       help='重复轮数(>1 时每轮冷启动,结束汇总 PASS/FAIL)')

    sub.add_parser('ls', help='列出开发板')

    args = ap.parse_args()
    if args.op == 'ls':
        boards = available_boards()
        if not boards:
            sys.exit('没有找到任何板卡配置。把板卡 TOML 放到 ~/.config/boardctl/boards/\n'
                     '(模板可参考包内置示例 boardctl/boards/),或用 $BOARDCTL_BOARDS 指定目录')
        for name in sorted(boards):
            cfg = load_board(name)
            desc = f' — {cfg["description"]}' if cfg['description'] else ''
            print(f'{cfg["name"]}{desc}')
        return

    cfg = None
    if args.op == 'run':
        if args.board is None:
            # 自动选中唯一的一块用户板(包内置示例不算)
            user_boards = {n: p for n, p in available_boards().items()
                           if not p.startswith(BUNDLED_BOARDS_DIR + os.sep)}
            if len(user_boards) == 1:
                args.board = next(iter(user_boards))
            else:
                sys.exit('请用 -b 指定开发板,可用: '
                         + (' '.join(sorted(user_boards)) or '(无;先在 ~/.config/boardctl/boards/ 放配置)'))
        cfg = load_board(args.board)
        _run_guarded(cfg, args)
