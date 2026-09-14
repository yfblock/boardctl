#!/usr/bin/env python3
"""兼容入口:等价于 boardctl -b sg2002 console(旧用法 python main.py 仍有效)"""
import sys

from boardctl.cli import main

if __name__ == '__main__':
    args = sys.argv[1:]
    board = args[0] if args and not args[0].startswith('-') else 'sg2002'
    sys.argv = ['boardctl', '-b', board, 'console']
    main()
