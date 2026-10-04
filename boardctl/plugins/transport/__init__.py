"""传输插件接口约定(插件即类):

每个插件模块需要提供:
  PLUGIN: Transport 子类       # 插件类(子类自身声明 NAME)

Transport 子类约定:
  __init__(self, cfg)              # 板卡配置,各插件自取所需段
  send(self, channel, path, addr) -> bool
                                   # 把文件传到设备的 addr;channel 是板的
                                   # 串口通道,由编排借出——插件不自开连接,
                                   # 也不关闭它(板负责生命周期)

配置段形状与默认值住 schema.py(如 [tftp]/[loady] 段);插件经 cfg
属性自取所需。可用的域依赖:serial(字节通道)/ console(控制台会话)/ shell(指令域)。
插件之间禁止互相 import。在此目录新建 .py 文件即自动注册。
"""
from abc import ABC, abstractmethod


class Transport(ABC):
    """传输方式抽象:子类实现 send,经 [run.*].method / method 选择——
    封装 = 各传输细节藏在类里;多态 = 不同子类同一接口"""

    NAME = None            # 注册名(子类必填),对应 [run.*].method

    @abstractmethod
    def send(self, channel, path, addr):
        """把文件传到设备的 addr;成功返回 True(channel 由编排借出,不关)"""
