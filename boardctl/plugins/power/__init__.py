"""Power plugin interface: a module provides PLUGIN = a PowerDevice
subclass (the class declares NAME, matched by [power].method).

  __init__(self, cfg)     # board config; take the sections you need
  on() / off()            # failures raise; the Power facade wraps the error
  status() -> bool | None # None when unparseable

Config shapes and defaults live in schema.py. Plugins execute natively
inside the boardctl process (not via ssh_host). Plugins must not import
each other."""
from abc import ABC, abstractmethod


class PowerDevice(ABC):
    """Power-device abstraction: on/off/status for one board's power source."""

    NAME = None            # registry name (subclasses must set), matches [power].method

    @abstractmethod
    def on(self):
        """Power on"""

    @abstractmethod
    def off(self):
        """Power off"""

    @abstractmethod
    def status(self):
        """Query the state; returns None when unparseable"""
