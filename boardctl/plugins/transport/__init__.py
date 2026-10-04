"""Transport plugin interface: a module provides PLUGIN = a Transport
subclass (the class declares NAME, matched by [run.*].method).

  __init__(self, cfg)                # board config; take the sections you need
  send(self, channel, path, addr) -> bool

channel is the board's resident capture stream, lent by the orchestrator —
open no connection of your own, don't close it; park()/resume() around any
fd lend. Config shapes and defaults live in schema.py. Plugins must not
import each other."""
from abc import ABC, abstractmethod


class Transport(ABC):
    """Transport abstraction: how a file reaches the device's addr."""

    NAME = None            # registry name (subclasses must set), matches [run.*].method

    @abstractmethod
    def send(self, channel, path, addr):
        """Transfer the file to the device's addr; return True on success."""
