"""命令行入口:极简命令面——run(一键全流程)+ ls(列表)+ power(电源控制)

google-fire 驱动:Boardctl 类即命令面,方法即子命令。全局 -b/--board 经
构造器参数收下(须置于子命令前,与历代版本一致;-b 是 board 的短别名,
fire 的短旗标即去掉前导连字符的参数名)。fire 不做类型/取值校验,
power state 与 repeat 由本模块手工校验;板名 str() 兜底纯数字名被
fire 字面量化成 int。
"""
import os
import signal
import sys

import fire

from . import power
from .config import BUNDLED_BOARDS_DIR, available_boards, load_board
from .runner import do_run


class _Interrupted(BaseException):
    """SIGTERM 等信号转成的可捕获中断"""


def _ensure_power_off(cfg):
    """打断善后:板在开机状态则执行一次关机,保证程序结束后设备是关的"""
    print('\n[boardctl] 程序被打断,执行关机保证...', file=sys.stderr, flush=True)
    p = power.Power(cfg)
    try:
        state = p.status()
    except SystemExit:
        state = None
    if state is False:
        return  # 本来就是关的
    if not p.off(check=False):
        print('[boardctl] 自动关机失败,请手动确认电源状态', file=sys.stderr)


def _run_guarded(cfg, name, repeat):
    """带打断关机保证的 run:Ctrl-C/SIGTERM/异常退出时若板开机则关机"""
    def _on_signal(signum, _frame):
        raise _Interrupted(f'signal {signum}')

    old_term = signal.signal(signal.SIGTERM, _on_signal)
    try:
        do_run(cfg, name, repeat=repeat)
    except (KeyboardInterrupt, _Interrupted):
        _ensure_power_off(cfg)
        sys.exit(130)
    except Exception:
        _ensure_power_off(cfg)
        raise
    finally:
        signal.signal(signal.SIGTERM, old_term)


def _pick_board(board):
    """解析目标板卡:-b 指定;缺省且仅一块用户板(包内置示例不算)时自动选中"""
    if board is None:
        user_boards = {n: p for n, p in available_boards().items()
                       if not p.startswith(BUNDLED_BOARDS_DIR + os.sep)}
        if len(user_boards) == 1:
            board = next(iter(user_boards))
        else:
            sys.exit('请用 -b 指定开发板,可用: '
                     + (' '.join(sorted(user_boards)) or '(无;先在 ~/.config/boardctl/ 放配置)'))
    return load_board(board)


class Boardctl:
    """开发板控制工具:一键全流程(冷启动→传输→执行→断言→收尾),
    板卡与启动目标配置见 ~/.config/boardctl,插件化传输/执行/电源"""

    def __init__(self, board=None, b=None):
        got = b if b is not None else board
        self._board = str(got) if got is not None else None

    def run(self, name=None, repeat=1, r=None):
        """一键全流程启动(目标配置于 [run.<名字>];省略目标名则列出可用目标)

        repeat(--repeat/-r):重复轮数,>1 时每轮冷启动,结束汇总 PASS/FAIL
        """
        repeat = r if r is not None else repeat
        if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
            sys.exit(f'--repeat/-r 须为正整数,收到: {repeat!r}')
        _run_guarded(_pick_board(self._board), name, repeat)

    def power(self, state):
        """电源控制(经电源插件:mijia/command):on 开机 / off 关机 / status 查询状态"""
        if state not in ('on', 'off', 'status'):
            sys.exit(f'无效 state {state!r},可选: on 开机 / off 关机 / status 查询状态')
        cfg = _pick_board(self._board)
        p = power.Power(cfg)
        if state == 'status':
            val = p.status()
            if val is not None:
                print('开' if val else '关')
        else:
            print(f'[{cfg["name"]}] 电源{"开机" if state == "on" else "关机"}({p.desc})',
                  flush=True)
            (p.on if state == 'on' else p.off)()

    def ls(self):
        """列出开发板"""
        boards = available_boards()
        if not boards:
            sys.exit('没有找到任何板卡配置。把板卡 TOML 放到 ~/.config/boardctl/\n'
                     '(模板可参考包内置示例 boardctl/boards/),或用 $BOARDCTL_BOARDS 指定目录')
        for name in sorted(boards):
            cfg = load_board(name)
            desc = f' — {cfg["description"]}' if cfg['description'] else ''
            print(f'{cfg["name"]}{desc}')


def main():
    fire.Fire(Boardctl)
