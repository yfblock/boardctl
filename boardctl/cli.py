"""命令行入口:极简命令面——run(一键全流程)+ boards(列表)"""
import argparse
import sys

from .config import available_boards, load_board
from .runner import do_run


def main():
    ap = argparse.ArgumentParser(
        prog='boardctl',
        description='开发板控制工具:一键全流程(冷启动→传输→执行→断言→收尾),'
                    '板卡与启动目标配置见 boards/*.toml,插件化传输/执行/电源')
    ap.add_argument('-b', '--board', default='sg2002', help='开发板名(boards/ 下的 TOML 文件名)')
    sub = ap.add_subparsers(dest='op', required=True)

    p_run = sub.add_parser('run', help='一键全流程启动(目标配置于 [run.<名字>])')
    p_run.add_argument('name', nargs='?', help='启动目标名(省略则列出可用目标)')
    p_run.add_argument('--repeat', '-r', type=int, default=1, metavar='N',
                       help='重复轮数(>1 时每轮冷启动,结束汇总 PASS/FAIL)')

    sub.add_parser('boards', help='列出开发板')

    args = ap.parse_args()
    if args.op == 'boards':
        boards = available_boards()
        if not boards:
            sys.exit('没有找到任何板卡配置。把板卡 TOML 放到 ~/.config/boardctl/boards/\n'
                     '(模板可参考包内置示例 boardctl/boards/),或用 $BOARDCTL_BOARDS 指定目录')
        for name in sorted(boards):
            cfg = load_board(name)
            desc = f' — {cfg["description"]}' if cfg['description'] else ''
            print(f'{cfg["name"]}{desc}')
        return

    cfg = load_board(args.board)
    if args.op == 'run':
        do_run(cfg, args.name, repeat=args.repeat)
