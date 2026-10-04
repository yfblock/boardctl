"""插件注册表:按目录约定自动发现,无需注册代码。

- plugins/transport/<mod>.py   传输插件(Transport 子类)
- plugins/power/<mod>.py       电源插件(PowerDevice 子类)
- plugins/mode/<mod>.py        启动模式插件(RunMode 子类,[run.*].mode 选择)

插件即类:每个插件模块提供 PLUGIN = <类>;类声明 NAME(注册名)。
配置段的形状与默认值统一住在 schema.py(单一来源),插件经 cfg 属性
自取所需段。新建插件 = 在对应目录加一个模块文件,自动生效;若带新
配置段,在 schema.BoardCfg 加字段即可(暂不定形的段可先声明 dict)。
(执行命令本身是 [run.*].cmd 配置模板,不是插件——0.11.0 起;mode 族
解释的是"目标怎么弄起来",不是"执行什么命令"。)
"""
import importlib
import pkgutil

from . import mode, power, transport

#: transport plugin registry {NAME: Transport subclass}; interface in transport/__init__.py
TRANSPORT = {}

#: power plugin registry {NAME: PowerDevice subclass}; interface in power/__init__.py
POWER = {}

#: boot-mode plugin registry {NAME: RunMode subclass}; interface in mode/__init__.py
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
