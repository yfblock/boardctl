"""传输插件接口约定(插件即类):

每个插件模块需要提供:
  PLUGIN: Transport 子类       # 插件类(子类自身声明 NAME)

Transport 子类约定:
  __init__(self, cfg)              # 板卡配置,各插件自取所需段
  send(self, path, addr) -> bool   # 把文件传到设备的 addr

类属性 CFG_SECTION + DEFAULTS(可选)由 config 合并为默认配置。
可用的域依赖:serial(字节通道)/ session(U-Boot 协议)/ shell(指令域)。
插件之间禁止互相 import。在此目录新建 .py 文件即自动注册。
"""
from abc import ABC, abstractmethod


class Transport(ABC):
    """传输方式抽象:子类实现 send,经 [run.*].method / method 选择——
    封装 = 各传输细节藏在类里;多态 = 不同子类同一接口"""

    NAME = None            # 注册名(子类必填),对应 [run.*].method
    CFG_SECTION = None     # 可选:插件配置段名
    DEFAULTS = None        # 可选:该段默认值

    @abstractmethod
    def send(self, path, addr):
        """把文件传到设备的 addr;成功返回 True"""
