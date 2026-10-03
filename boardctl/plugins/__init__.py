"""插件注册表:按目录约定自动发现,无需注册代码。

- plugins/transport/<mod>.py   传输插件(Transport 子类)
- plugins/power/<mod>.py       电源插件(PowerDevice 子类)

插件即类:每个插件模块提供 PLUGIN = <类>;类声明 NAME(注册名)与可选
CFG_SECTION/DEFAULTS(config 合并默认值用)。新建插件 = 在对应目录加一个
模块文件,自动生效。(执行插件族已于 0.11.0 退役:执行命令回归
[run.*].cmd 模板配置,watch 被动模式由 runner 原生处理。)
"""
import importlib
import pkgutil

from . import power, transport

#: 传输插件注册表 {NAME: Transport 子类},接口见 transport/__init__.py
TRANSPORT = {}

#: 电源插件注册表 {NAME: PowerDevice 子类},接口见 power/__init__.py
POWER = {}


def _scan(package, registry):
    for m in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f'{package.__name__}.{m.name}')
        plugin = getattr(module, 'PLUGIN', None)
        name = getattr(plugin, 'NAME', None) if plugin else None
        if name:
            registry[name] = plugin


_scan(transport, TRANSPORT)
_scan(power, POWER)


def all_plugins():
    """全部已注册插件类的列表(config 合并插件自带 DEFAULTS 用)"""
    plugins = []
    for registry in (TRANSPORT, POWER):
        plugins.extend(registry.values())
    return plugins
