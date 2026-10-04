"""mijia power plugin: calls the mijiaapi package natively, controlling a
smart socket via the Xiaomi cloud.

Credentials reuse mijiaAPI CLI's login state (~/.config/mijia-api/auth.json);
run `mijiaAPI login` (QR scan) once before first use. The on/off property
name defaults to 'on' (most sockets); on devices whose power prop isn't
'on', specify it via prop = "..." in [power.mijia].
"""
import threading

from . import PowerDevice


class MijiaPower(PowerDevice):
    NAME = 'mijia'

    _lock = threading.Lock()
    _dev_cache = {}   # (did, dev_name) -> mijiaDevice; class attribute: a
                      # process-level cache shared across instances (avoids
                      # re-fetching the device list on every call)

    def __init__(self, cfg):
        self.cfg = cfg

    def _device(self):
        with self._lock:
            p = self.cfg.power.mijia
            key = (p.did, p.dev_name)
            if key not in self._dev_cache:
                from mijiaAPI.apis import mijiaAPI
                from mijiaAPI.devices import mijiaDevice
                kwargs = {}
                if p.did:
                    kwargs['did'] = p.did
                elif p.dev_name:
                    kwargs['dev_name'] = p.dev_name
                else:
                    raise ValueError('[power.mijia] needs dev_name or did')
                self._dev_cache[key] = mijiaDevice(mijiaAPI(), **kwargs)
            return self._dev_cache[key]

    def _prop(self):
        """On/off property name: defaults to 'on'; devices not using 'on'
        configure prop in [power.mijia]"""
        return self.cfg.power.mijia.prop

    def on(self):
        self._device().set(self._prop(), True)

    def off(self):
        self._device().set(self._prop(), False)

    def status(self):
        return bool(self._device().get(self._prop()))


PLUGIN = MijiaPower
