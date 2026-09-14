"""mijia 电源插件:原生调用 mijiaapi 包,经小米云控制智能插座

凭证复用 mijiaAPI CLI 的登录态(~/.config/mijia-api/auth.json),
首次使用前需先执行一次 `mijiaAPI login` 扫码。
"""
import threading

NAME = 'mijia'

_lock = threading.Lock()
_dev_cache = {}   # (did, dev_name) -> mijiaDevice,避免每次操作都拉设备列表


def _device(cfg):
    with _lock:
        p = cfg['power'].get('mijia', {})
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


def set_power(cfg, on):
    _device(cfg).set('on', bool(on))


def get_power(cfg):
    return bool(_device(cfg).get('on'))
