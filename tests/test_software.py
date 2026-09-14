#!/usr/bin/env python3
"""纯软件冒烟测试:不需要真机/串口/网络,CI 与本地都应能跑"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from boardctl.config import BASE_DIR, available_boards, load_board
from boardctl.plugins import EXECUTORS, POWER, TRANSPORT

# 1. 插件注册表齐全
assert {'loady', 'tftp'} <= set(TRANSPORT), TRANSPORT
assert {'go', 'source', 'none'} <= set(EXECUTORS), EXECUTORS
assert {'mijia', 'command'} <= set(POWER), POWER

# 2. 执行插件命令构造
assert EXECUTORS['go'].build_cmd('0x80080000') == 'go 0x80080000'
assert EXECUTORS['source'].build_cmd('0x80080000') == 'source 0x80080000'
assert EXECUTORS['none'].build_cmd('0x80080000') is None

# 3. 板卡配置加载 + 插件默认值合并
boards = available_boards()
assert 'sg2002' in boards, boards
cfg = load_board('sg2002')
assert 'sender' in cfg['loady'], cfg['loady']          # loady 插件自带 DEFAULTS
assert cfg['tftp']['method'] == 'remote', cfg['tftp']
assert cfg['power']['method'] == 'mijia', cfg['power']

# 4. run 目标引用的文件真实存在(相对项目根解析)
for name, t in cfg['run'].items():
    path = t['file']
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    assert os.path.isfile(path), f'run.{name} 文件缺失: {path}'

# 5. 电源语义层导入无误
from boardctl import power  # noqa: E402,F401

print('software tests: OK')
