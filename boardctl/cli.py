"""命令行入口:极简命令面——run(一键全流程)+ ls(列表)+ power(电源控制)
+ check(校验配置)

cyclopts 注解式解析:类型即校验——repeat 声明 int、power state 用 Literal
合法值,非法参数在解析层即报错(带用法提示)。全局 -b/--board 须经 meta
入口收下(置于子命令前,与历代一致);meta 构造 Boardctl 一次,注入声明了
它的子命令(Annotated[..., Parameter(parse=False)] 约定,经 parse_args 的
ignored 传递)。板名解析与配置加载仍是 Boardctl.cfg 懒加载——ls/check
不触。命令体只转发到 Boardctl 方法:业务逻辑与打断善后(@_guarded)都
在类里,测试可直接调方法。
"""
import functools
import importlib.metadata
import os
import signal
import sys
from typing import Annotated, Literal

import cyclopts
from cyclopts import Parameter

from . import power
from .config import BUNDLED_BOARDS_DIR, available_boards, load_board
from .runner import do_run

try:
    _VERSION = importlib.metadata.version('boardctl')
except importlib.metadata.PackageNotFoundError:
    _VERSION = '0.0.0'   # 源码态未安装,占位(装好即真版本)

# result_action='return_value':命令成功时 app.meta() 正常返回而不是
# sys.exit(0)——保持可嵌入(测试/程序化调用);成败退出码由命令自身
# sys.exit 与错误路径负责
app = cyclopts.App(name='boardctl', version=_VERSION,
                   result_action='return_value')


class _Interrupted(BaseException):
    """SIGTERM 等信号转成的可捕获中断"""


def _on_signal(signum, _frame):
    raise _Interrupted(f'signal {signum}')


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


def _guarded(fn):
    """打断关机保证(装饰子命令):Ctrl-C/SIGTERM/异常退出时若板开机则关机。
    先落定板卡配置再装信号钩子——板卡解析阶段的退出不需要善后,
    而善后本身要用 cfg(经 self.cfg 懒加载,与命令体内是同一份)"""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        cfg = self.cfg
        old_term = signal.signal(signal.SIGTERM, _on_signal)
        try:
            return fn(self, *args, **kwargs)
        except (KeyboardInterrupt, _Interrupted):
            _ensure_power_off(cfg)
            sys.exit(130)
        except Exception:
            _ensure_power_off(cfg)
            raise
        finally:
            signal.signal(signal.SIGTERM, old_term)
    return wrapper


def _board_name(raw):
    """-b 原始值 → 板名:缺省且仅一块用户板(包内置示例不算)时自动选中"""
    if raw is None:
        user_boards = {n: p for n, p in available_boards().items()
                       if not p.startswith(BUNDLED_BOARDS_DIR + os.sep)}
        if len(user_boards) == 1:
            return next(iter(user_boards))
        sys.exit('请用 -b 指定开发板,可用: '
                 + (' '.join(sorted(user_boards)) or '(无;先在 ~/.config/boardctl/ 放配置)'))
    return raw


_NO_BOARDS = ('没有找到任何板卡配置。把板卡 TOML 放到 ~/.config/boardctl/\n'
              '(模板可参考包内置示例 boardctl/boards/),或用 $BOARDCTL_BOARDS 指定目录')


class Boardctl:
    """开发板控制工具:一键全流程(冷启动→传输→执行→断言→收尾),
    板卡与启动目标配置见 ~/.config/boardctl,插件化传输/电源/启动模式"""

    def __init__(self, board=None):
        self._board = str(board) if board is not None else None
        self._cfg = None

    @property
    def cfg(self):
        """目标板卡配置(懒加载一次):板名经 -b 或自动选板落定,即解析即加载"""
        if self._cfg is None:
            self._cfg = load_board(_board_name(self._board))
        return self._cfg

    @_guarded
    def run(self, name=None, repeat=1):
        """一键全流程启动(目标配置于 [run.<名字>];省略目标名则列出可用目标)

        repeat(--repeat/-r):重复轮数,>1 时每轮冷启动,结束汇总 PASS/FAIL
        """
        if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
            sys.exit(f'--repeat/-r 须为正整数,收到: {repeat!r}')
        do_run(self.cfg, name, repeat)

    def power(self, state):
        """电源控制(经电源插件:mijia/command):on 开机 / off 关机 / status 查询状态"""
        if state not in ('on', 'off', 'status'):
            sys.exit(f'无效 state {state!r},可选: on 开机 / off 关机 / status 查询状态')
        cfg = self.cfg
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
            sys.exit(_NO_BOARDS)
        for name in sorted(boards):
            cfg = load_board(name)
            desc = f' — {cfg["description"]}' if cfg['description'] else ''
            print(f'{cfg["name"]}{desc}')

    def check(self, name=None):
        """校验板卡配置格式(schema.py 声明的形状;不碰硬件)

        省略板名则校验全部;有无效配置时退出码 1
        """
        boards = available_boards()
        if not boards:
            sys.exit(_NO_BOARDS)
        failed = 0
        for n in [name] if name is not None else sorted(boards):
            try:
                load_board(n)   # 未知板/配置无效的判断都在 load_board,报错自带板名
                print(f'{n}: OK')
            except SystemExit as e:
                failed += 1
                print(e.code)
        if failed:
            sys.exit(1)


@app.meta.default
def _launch(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    board: Annotated[str | None,
                     Parameter(name=['-b', '--board'],
                               help='开发板名(缺省:仅一块用户板卡时自动选中)')] = None,
):
    """开发板控制工具:一键全流程(冷启动→传输→执行→断言→收尾),
    板卡与启动目标配置见 ~/.config/boardctl,插件化传输/执行/电源/启动模式"""
    command, bound, ignored = app.parse_args(tokens)
    extra = {'ctl': Boardctl(board=board)} if 'ctl' in ignored else {}
    command(*bound.args, **bound.kwargs, **extra)


@app.command
def run(
    name: Annotated[str | None, Parameter(help='启动目标名(省略则列出可用目标)')] = None,
    repeat: Annotated[int, Parameter(name=['-r', '--repeat'],
                                     help='重复轮数(>1 时每轮冷启动,结束汇总 PASS/FAIL)')] = 1,
    *,
    ctl: Annotated[Boardctl, Parameter(parse=False)],
):
    """一键全流程启动(目标配置于 [run.<名字>];省略目标名则列出可用目标)"""
    ctl.run(name, repeat)


@app.command(name='power')
def power_ctl(
    state: Annotated[Literal['on', 'off', 'status'],
                     Parameter(help='on 开机 / off 关机 / status 查询状态')],
    *,
    ctl: Annotated[Boardctl, Parameter(parse=False)],
):
    """电源控制(经电源插件:mijia/command)"""
    ctl.power(state)


@app.command
def ls(*, ctl: Annotated[Boardctl, Parameter(parse=False)]):
    """列出开发板"""
    ctl.ls()


@app.command
def check(
    name: Annotated[str | None, Parameter(help='板名(省略则校验全部)')] = None,
    *,
    ctl: Annotated[Boardctl, Parameter(parse=False)],
):
    """校验板卡配置格式(schema.py 声明的形状;不碰硬件);有无效配置时退出码 1"""
    ctl.check(name)


def main():
    app.meta(sys.argv[1:])
