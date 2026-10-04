"""Power plugin interface conventions (plugins are classes):

Each plugin module must provide:
  PLUGIN: a PowerDevice subclass    # the plugin class (subclasses declare NAME themselves)

PowerDevice subclass conventions:
  __init__(self, cfg)              # board config; each plugin takes the sections it needs
  on(self) / off(self)             # power the device on/off; failures raise (the caller wraps the error)
  status(self) -> bool | None      # query the state; None when unparseable

Config section shapes and defaults live in schema.py (the [power] section);
plugins take what they need via cfg attributes. Plugins execute natively
inside the boardctl process (not via ssh_host). Dropping a new .py file in
this directory auto-registers it.
"""
from abc import ABC, abstractmethod


class PowerDevice(ABC):
    """Power-device abstraction: subclasses implement on/off/status, selected
    via [power].method — encapsulation = each plugin's details hide inside
    its class; polymorphism = different subclasses, one interface"""

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
