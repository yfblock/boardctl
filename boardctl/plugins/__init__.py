"""Plugin registry: auto-discovery by directory convention, no registration
code.

- plugins/transport/<mod>.py   transport plugins (Transport subclasses)
- plugins/power/<mod>.py       power plugins (PowerDevice subclasses)
- plugins/mode/<mod>.py        boot-mode plugins (RunMode subclasses,
                               selected via [run.*].mode)

Plugins are classes: each plugin module provides PLUGIN = <class>; the class
declares NAME (the registry name). Config section shapes and defaults live
uniformly in schema.py (single source); plugins take the sections they need
via cfg attributes. Creating a plugin = drop a module file into the right
directory, effective automatically; if it brings a new config section, just
add the field to schema.BoardCfg (a section not yet settled can first be
declared as dict). (The executed command itself is a [run.*].cmd config
template, not a plugin — since 0.11.0; the mode family interprets "how a
target gets brought up", not "what command to execute".)
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
