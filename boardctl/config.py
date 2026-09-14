"""板卡配置加载:boards/*.toml + 默认值合并(TOML 同名键覆盖)"""
import os
import sys
import tomllib
from pathlib import Path

# 项目根目录(本包的上一级):开发运行时 boards/、run.sh 等在这里
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 全局默认值(仅真正跨模块的段;插件自己的默认值由插件模块的 DEFAULTS 提供)
DEFAULTS = {
    'serial': {'url': 'socket://localhost:5000', 'timeout': 0.2},
    'uboot': {
        'prompt': '=>',
        'load_addr': '0x80080000',
        'ip_addr': '',
        'server_ip': '',
        'ensure_server_ip': False,
    },
}


def boards_dirs():
    """板卡配置目录搜索顺序(去重,仅保留存在的):
    $BOARDCTL_BOARDS → 当前目录 boards/ → ~/.config/boardctl/boards → 包内置示例
    """
    candidates = [
        os.environ.get('BOARDCTL_BOARDS'),
        os.path.join(os.getcwd(), 'boards'),
        str(Path.home() / '.config' / 'boardctl' / 'boards'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boards'),
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
        for f in sorted(os.listdir(d)):
            if f.endswith('.toml'):
                names.setdefault(f[:-5], os.path.join(d, f))
    return names


def load_board(name):
    boards = available_boards()
    if name not in boards:
        sys.exit(f"未知开发板 {name!r},可用: {' '.join(sorted(boards)) or '(没有任何 boards/ 目录里有配置)'}")
    with open(boards[name], 'rb') as f:
        data = tomllib.load(f)
    cfg = {'name': name, 'description': data.get('description', ''),
           'ssh_host': data.get('ssh_host', '')}
    for section, defaults in DEFAULTS.items():
        cfg[section] = {**defaults, **data.get(section, {})}
    cfg['power'] = dict(data.get('power', {}))
    cfg['tftp'] = dict(data.get('tftp', {}))
    cfg['run'] = data.get('run', {})

    # 插件自带默认值:按插件的 CFG_SECTION 声明合并(TOML 值优先)。
    # 函数内 import,避免 config <-> plugins 模块级循环依赖
    from .plugins import all_plugins
    for mod in all_plugins():
        section = getattr(mod, 'CFG_SECTION', None)
        defaults = getattr(mod, 'DEFAULTS', None)
        if section and isinstance(defaults, dict):
            merged = dict(defaults)
            merged.update(cfg.get(section, {}))
            cfg[section] = merged
    return cfg
