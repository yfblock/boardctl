"""命令行入口:参数解析与子命令分发,只做接线不含业务逻辑"""
import argparse
import os
import sys

from . import power, runner, shell
from .config import available_boards, load_board
from .console import do_console
from .plugins import TRANSPORT


def main():
    ap = argparse.ArgumentParser(
        prog='boardctl',
        description='开发板控制工具(参考 ostool 设计,每板一个 boards/*.toml,插件化传输/执行)')
    ap.add_argument('-b', '--board', default='sg2002', help='开发板名(boards/ 下的 TOML 文件名)')
    sub = ap.add_subparsers(dest='op', required=True)

    sub.add_parser('console', help='交互式串口终端')
    p_power = sub.add_parser('power', help='电源控制')
    p_power.add_argument('state', choices=['on', 'off', 'status'])
    sub.add_parser('reset', help='断电重启')
    p_cmd = sub.add_parser('cmd', help='在 U-Boot 提示符执行命令')
    p_cmd.add_argument('commands', nargs='+')
    p_send = sub.add_parser('send', help='向开发板传输文件')
    p_send.add_argument('file')
    p_send.add_argument('--method', choices=sorted(TRANSPORT) or ['loady'],
                        default='loady', help='传输插件')
    p_send.add_argument('--addr', help='加载地址(默认取板卡 uboot.load_addr)')
    p_run = sub.add_parser('run', help='按板卡配置的 [run.<名字>] 一键启动')
    p_run.add_argument('name', nargs='?', help='启动目标名(省略则列出可用目标)')
    p_exec = sub.add_parser('exec', help='在板卡命令环境执行 shell 命令(配置 ssh_host 则经 ssh 远端执行)')
    p_exec.add_argument('command', nargs='+')
    sub.add_parser('boards', help='列出开发板')

    args = ap.parse_args()
    if args.op == 'boards':
        boards = available_boards()
        if not boards:
            sys.exit('没有找到任何板卡配置(搜索:$BOARDCTL_BOARDS → ./boards → ~/.config/boardctl/boards → 包内置)')
        for name in sorted(boards):
            cfg = load_board(name)
            desc = f' — {cfg["description"]}' if cfg['description'] else ''
            print(f'{cfg["name"]}{desc}')
        return

    cfg = load_board(args.board)
    if args.op == 'console':
        do_console(cfg)
    elif args.op == 'power':
        power.do_power(cfg, args.state)
    elif args.op == 'reset':
        power.do_reset(cfg)
    elif args.op == 'cmd':
        runner.do_cmd(cfg, args.commands)
    elif args.op == 'send':
        if not os.path.isfile(args.file):
            sys.exit(f'文件不存在: {args.file}')
        addr = args.addr or cfg['uboot']['load_addr']
        ok = TRANSPORT[args.method].send(cfg, args.file, addr)
        sys.exit(0 if ok else 1)
    elif args.op == 'run':
        runner.do_run(cfg, args.name)
    elif args.op == 'exec':
        r = shell.run(cfg, ' '.join(args.command), check=False, capture=True)
        sys.stdout.write(r.stdout or '')
        sys.stderr.write(r.stderr or '')
        sys.exit(r.returncode)
