"""命令行入口:极简命令面——run(一键全流程)+ ls(列表)+ power(电源控制)

cyclopts 注解式解析:全局 -b/--board 须经 meta 入口收下(置于子命令前,与旧
argparse 行为一致),板卡配置在 meta 层解析一次,注入声明了 cfg 的子命令
(Annotated[..., Parameter(parse=False)] 约定,经 parse_args 的 ignored 传递)。
"""
import os
import signal
import sys
from typing import Annotated, Literal

import cyclopts
from cyclopts import Parameter

from . import power
from .config import BUNDLED_BOARDS_DIR, available_boards, load_board
from .runner import do_run

# result_action='return_value':命令成功时 app.meta() 正常返回而不是 sys.exit(0)
# ——保持可嵌入(测试/程序化调用);成败退出码由命令自身 sys.exit 与错误路径负责
app = cyclopts.App(name='boardctl', result_action='return_value')


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


@app.meta.default
def _launch(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    board: Annotated[str | None,
                     Parameter(name=['-b', '--board'],
                               help='开发板名(缺省:仅一块用户板卡时自动选中)')] = None,
):
    """开发板控制工具:一键全流程(冷启动→传输→执行→断言→收尾),
    板卡与启动目标配置见 ~/.config/boardctl,插件化传输/执行/电源"""
    command, bound, ignored = app.parse_args(tokens)
    extra = {}
    if 'cfg' in ignored:                 # 仅声明了 cfg 的子命令才解析板卡(ls 不需要)
        extra['cfg'] = _pick_board(board)
    command(*bound.args, **bound.kwargs, **extra)


@app.command
def run(name: Annotated[str | None, Parameter(help='启动目标名(省略则列出可用目标)')] = None,
        repeat: Annotated[int, Parameter(name=['-r', '--repeat'],
                                         help='重复轮数(>1 时每轮冷启动,结束汇总 PASS/FAIL)')] = 1,
        *, cfg: Annotated[dict, Parameter(parse=False)]):
    """一键全流程启动(目标配置于 [run.<名字>])"""
    _run_guarded(cfg, name, repeat)


@app.command
def ls():
    """列出开发板"""
    boards = available_boards()
    if not boards:
        sys.exit('没有找到任何板卡配置。把板卡 TOML 放到 ~/.config/boardctl/\n'
                 '(模板可参考包内置示例 boardctl/boards/),或用 $BOARDCTL_BOARDS 指定目录')
    for name in sorted(boards):
        cfg = load_board(name)
        desc = f' — {cfg["description"]}' if cfg['description'] else ''
        print(f'{cfg["name"]}{desc}')


@app.command(name='power')
def power_ctl(state: Annotated[Literal['on', 'off', 'status'],
                              Parameter(help='on 开机 / off 关机 / status 查询状态')],
              *, cfg: Annotated[dict, Parameter(parse=False)]):
    """电源控制(经电源插件:mijia/command)"""
    if state != 'status':
        print(f'[{cfg["name"]}] 电源{"开机" if state == "on" else "关机"}'
              f'({power.method_desc(cfg)})', flush=True)
    power.do_power(cfg, state)   # 内部完成动作并 exit(0)


def main():
    app.meta(sys.argv[1:])
