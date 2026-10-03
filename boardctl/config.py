"""板卡配置加载:board_dir(~/.config/boardctl)下的 *.toml + 默认值合并(TOML 同名键覆盖)"""
import os
import sys
import tomllib
from pathlib import Path

# 项目根目录(本包的上一级):开发运行时 boards/、run.sh 等在这里
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 随包分发的示例板卡目录(仅作模板兜底,优先级最低)
BUNDLED_BOARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boards')

# 全局默认值(仅真正跨模块的段;插件自己的默认值由插件类的 DEFAULTS 提供)
DEFAULTS = {
    'serial': {'url': 'socket://localhost:5000', 'timeout': 0.2},
    'console': {'prompt': '=>'},    # 控制台提示符(U-Boot/Linux shell/其他 CLI 皆可)
    'uboot': {                      # U-Boot 特有:加载地址/网络,由 cmd 模板与传输插件取用
        'load_addr': '0x80080000',
        'ip_addr': '',
        'server_ip': '',
        'ensure_server_ip': False,
    },
}


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
        for f in sorted(os.listdir(d)):
            if f.endswith('.toml'):
                names.setdefault(f[:-5], os.path.join(d, f))
    return names


def load_board(name):
    boards = available_boards()
    if name not in boards:
        sys.exit(f"未知开发板 {name!r},可用: {' '.join(sorted(boards)) or '(配置目录里没有任何板卡)'}")
    with open(boards[name], 'rb') as f:
        data = tomllib.load(f)
    cfg = {'name': name, 'description': data.get('description', ''),
           'ssh_host': data.get('ssh_host', '')}
    for section, defaults in DEFAULTS.items():
        cfg[section] = {**defaults, **data.get(section, {})}
    cfg['power'] = dict(data.get('power', {}))
    cfg['tftp'] = dict(data.get('tftp', {}))
    cfg['run'] = data.get('run', {})

    # 旧配置兼容:prompt 原住在 [uboot];控制台不一定姓 U-Boot,现归 [console]。
    # 无 [console] 段时提示符继承 [uboot].prompt,老配置零改动可用
    if 'console' not in data and 'prompt' in cfg['uboot']:
        cfg['console']['prompt'] = cfg['uboot']['prompt']

    # 插件自带默认值:按插件类的 CFG_SECTION 声明合并(TOML 值优先)。
    # 函数内 import,避免 config <-> plugins 模块级循环依赖
    from .plugins import all_plugins
    for plugin in all_plugins():
        section = getattr(plugin, 'CFG_SECTION', None)
        defaults = getattr(plugin, 'DEFAULTS', None)
        if section and isinstance(defaults, dict):
            merged = dict(defaults)
            merged.update(cfg.get(section, {}))
            cfg[section] = merged
    return cfg
