"""电源插件接口约定(插件即类):

每个插件模块需要提供:
  PLUGIN: PowerDevice 子类      # 插件类(子类自身声明 NAME)

PowerDevice 子类约定:
  __init__(self, cfg)          # 板卡配置,各插件自取所需段
  on(self) / off(self)         # 开/关设备电源;失败抛异常(上层包装报错)
  status(self) -> bool | None  # 查询状态;无法解析时返回 None

配置段形状与默认值住 schema.py([power] 段);插件经 cfg 属性自取所需。
插件在 boardctl 进程内原生执行(不经过 ssh_host)。
在此目录新建 .py 文件即自动注册。
"""
from abc import ABC, abstractmethod


class PowerDevice(ABC):
    """电源设备抽象:子类实现 on/off/status,经 [power].method 选择——
    封装 = 各插件细节藏在类里;多态 = 不同子类同一接口"""

    NAME = None            # 注册名(子类必填),对应 [power].method

    @abstractmethod
    def on(self):
        """上电"""

    @abstractmethod
    def off(self):
        """断电"""

    @abstractmethod
    def status(self):
        """查询状态;无法解析时返回 None"""
