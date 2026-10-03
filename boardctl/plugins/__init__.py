"""插件注册表:按目录约定自动发现,无需注册代码。

- plugins/transport/<mod>.py   传输插件
- plugins/power/<mod>.py       电源插件

新建插件 = 在对应目录加一个模块文件,自动生效。
(执行插件族已于 0.11.0 退役:执行命令回归 [run.*].cmd 模板配置,
watch 被动模式由 runner 原生处理。)
"""
import importlib
import pkgutil

from . import power, transport

#: 传输插件注册表 {NAME: module},接口见 transport/__init__.py
TRANSPORT = {}

#: 电源插件注册表 {NAME: module},接口见 power/__init__.py
POWER = {}


def _scan(package, registry):
    for m in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f'{package.__name__}.{m.name}')
        name = getattr(module, 'NAME', None)
        if name:
            registry[name] = module


_scan(transport, TRANSPORT)
_scan(power, POWER)


def all_plugins():
    """全部已注册插件模块的列表(config 合并插件自带 DEFAULTS 用)"""
    mods = []
    for registry in (TRANSPORT, POWER):
        mods.extend(registry.values())
    return mods
