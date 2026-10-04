"""Plugin registry: auto-discovery by directory convention, no registration
code.

- plugins/transport/<mod>.py   Transport subclasses (registry TRANSPORT)
- plugins/power/<mod>.py       PowerDevice subclasses (POWER)
- plugins/mode/<mod>.py        RunMode subclasses (MODE, selected via [run.*].mode)

A plugin module provides PLUGIN = <class>; the class declares NAME (the
registry name). Config section shapes and defaults live only in schema.py.
Creating a plugin = dropping a module file into the right directory; if it
brings a new config section, add the field to schema.BoardCfg. The executed
command itself is a [run.*].cmd config template, not a plugin."""
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
