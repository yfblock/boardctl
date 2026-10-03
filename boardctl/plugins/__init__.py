"""插件注册表:按目录约定自动发现,无需注册代码。

- plugins/transport/<mod>.py   传输插件(Transport 子类)
- plugins/power/<mod>.py       电源插件(PowerDevice 子类)
- plugins/mode/<mod>.py        启动模式插件(RunMode 子类,[run.*].mode 选择)

插件即类:每个插件模块提供 PLUGIN = <类>;类声明 NAME(注册名)与可选
CFG_SECTION/DEFAULTS(config 合并默认值用)。新建插件 = 在对应目录加一个
模块文件,自动生效。(执行命令本身是 [run.*].cmd 配置模板,不是插件——
0.11.0 起;mode 族解释的是"目标怎么弄起来",不是"执行什么命令"。)
"""
import importlib
import pkgutil

from . import mode, power, transport

#: 传输插件注册表 {NAME: Transport 子类},接口见 transport/__init__.py
TRANSPORT = {}

#: 电源插件注册表 {NAME: PowerDevice 子类},接口见 power/__init__.py
POWER = {}

#: 启动模式插件注册表 {NAME: RunMode 子类},接口见 mode/__init__.py
MODE = {}


def _scan(package, registry):
    for m in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f'{package.__name__}.{m.name}')
        plugin = getattr(module, 'PLUGIN', None)
        name = getattr(plugin, 'NAME', None) if plugin else None
        if name:
            registry[name] = plugin


_scan(transport, TRANSPORT)
_scan(power, POWER)
_scan(mode, MODE)


def all_plugins():
    """全部已注册插件类的列表(config 合并插件自带 DEFAULTS 用)"""
    plugins = []
    for registry in (TRANSPORT, POWER, MODE):
        plugins.extend(registry.values())
    return plugins
