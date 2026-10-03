"""mijia 电源插件:原生调用 mijiaapi 包,经小米云控制智能插座

凭证复用 mijiaAPI CLI 的登录态(~/.config/mijia-api/auth.json),
首次使用前需先执行一次 `mijiaAPI login` 扫码。
开关量属性名默认 'on'(多数插座);部分设备的电源 prop 不是 'on',
可在 [power.mijia] 里用 prop = "..." 指定。
"""
import threading

from . import PowerDevice

_lock = threading.Lock()
_dev_cache = {}   # (did, dev_name) -> mijiaDevice,进程级缓存,避免每次操作都拉设备列表


class MijiaPower(PowerDevice):
    NAME = 'mijia'

    def __init__(self, cfg):
        self.cfg = cfg

    def _device(self):
        with _lock:
            p = self.cfg['power'].get('mijia', {})
            key = (p.get('did'), p.get('dev_name'))
            if key not in _dev_cache:
                from mijiaAPI.apis import mijiaAPI
                from mijiaAPI.devices import mijiaDevice
                kwargs = {}
                if p.get('did'):
                    kwargs['did'] = p['did']
                elif p.get('dev_name'):
                    kwargs['dev_name'] = p['dev_name']
                else:
                    raise ValueError('[power.mijia] 需要 dev_name 或 did')
                _dev_cache[key] = mijiaDevice(mijiaAPI(), **kwargs)
            return _dev_cache[key]

    def _prop(self):
        """开关量属性名:默认 'on';非 'on' 的设备在 [power.mijia] 配 prop"""
        return self.cfg['power'].get('mijia', {}).get('prop', 'on')

    def on(self):
        self._device().set(self._prop(), True)

    def off(self):
        self._device().set(self._prop(), False)

    def status(self):
        return bool(self._device().get(self._prop()))


PLUGIN = MijiaPower
