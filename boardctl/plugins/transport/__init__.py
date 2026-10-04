"""Transport plugin interface conventions (plugins are classes):

Each plugin module must provide:
  PLUGIN: a Transport subclass    # the plugin class (subclasses declare NAME themselves)

Transport subclass conventions:
  __init__(self, cfg)              # board config; each plugin takes the sections it needs
  send(self, channel, path, addr) -> bool
                                   # transfer the file to the device's addr; channel is
                                   # the board's serial channel, lent by the orchestrator —
                                   # the plugin opens no connection of its own and
                                   # doesn't close it either (the board owns the lifecycle)

The config section shapes and defaults live in schema.py (e.g. the [tftp]/[loady]
sections); plugins take what they need via cfg attributes. Available domain
dependencies: serial (byte channel) / console (console session) / shell (command
domain). Plugins must not import each other. Dropping a new .py file in this
directory auto-registers it.
"""
from abc import ABC, abstractmethod


class Transport(ABC):
    """Transport abstraction: subclasses implement send, selected via
    [run.*].method / method — encapsulation = each transport's details hide
    inside its class; polymorphism = different subclasses, one interface"""

    NAME = None            # registry name (subclasses must set), matches [run.*].method

    @abstractmethod
    def send(self, channel, path, addr):
        """Transfer the file to the device's addr; return True on success (channel is lent by the orchestrator, don't close it)"""
