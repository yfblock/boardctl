"""板卡配置:目录发现 + 加载。

- 发现:boards_dirs()/available_boards() 按 $BOARDCTL_BOARDS →
  ~/.config/boardctl → 包内置示例的优先级找板卡。
- 加载(load_board):toml 解析 → 注入板名 → msgspec 建模校验
  (形状与默认值见 schema.py)→ 直接以 BoardCfg 模型对象返回。
"""
import os
import sys
import tomllib
from pathlib import Path

import msgspec

from . import schema

# 项目根目录(本包的上一级):开发运行时 boards/、run.sh 等在这里
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 随包分发的示例板卡目录(仅作模板兜底,优先级最低)
BUNDLED_BOARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boards')


def boards_dirs():
    """板卡配置目录搜索顺序(去重,仅保留存在的):
    $BOARDCTL_BOARDS → ~/.config/boardctl(用户配置,唯一推荐位置)→ 包内置示例
    本地/项目文件夹不参与解析。
    """
    candidates = [
        os.environ.get('BOARDCTL_BOARDS'),
        str(Path.home() / '.config' / 'boardctl'),
        BUNDLED_BOARDS_DIR,
    ]
    seen, out = set(), []
    for d in candidates:
        if d:
            d = os.path.abspath(d)
            if d not in seen and os.path.isdir(d):
                seen.add(d)
                out.append(d)
    return out


def available_boards():
    """全部可用板卡名(按目录优先级去重,先出现的优先)"""
    names = {}
    for d in boards_dirs():
        for p in sorted(Path(d).glob('*.toml')):
            names.setdefault(p.stem, str(p))
    return names


def load_board(name):
    boards = available_boards()
    if name not in boards:
        sys.exit(f"未知开发板 {name!r},可用: {' '.join(sorted(boards)) or '(配置目录里没有任何板卡)'}")
    with open(boards[name], 'rb') as f:
        data = tomllib.load(f)
    data['name'] = name
    try:
        return msgspec.convert(data, schema.BoardCfg, strict=False)
    except msgspec.ValidationError as e:
        sys.exit(f'板卡 {name} 配置无效({boards[name]}):\n{e}')
