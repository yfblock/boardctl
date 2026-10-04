"""mijia power plugin: controls a smart socket via the Xiaomi cloud, calling
the mijiaapi package natively. Credentials reuse the mijiaAPI CLI login
state (~/.config/mijia-api/auth.json) — `mijiaAPI login` (QR scan) once
before first use."""
import threading

from . import PowerDevice


class MijiaPower(PowerDevice):
    NAME = 'mijia'

    _lock = threading.Lock()
    _dev_cache = {}   # (did, dev_name) -> mijiaDevice; process-level cache shared across instances

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
        """On/off property name: default 'on'; some devices differ."""
        return self.cfg.power.mijia.prop

    def on(self):
        self._device().set(self._prop(), True)

    def off(self):
        self._device().set(self._prop(), False)

    def status(self):
        return bool(self._device().get(self._prop()))


PLUGIN = MijiaPower
