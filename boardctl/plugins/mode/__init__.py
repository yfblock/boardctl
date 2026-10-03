"""启动模式插件接口约定(插件即类):

每个插件模块需要提供:
  PLUGIN: RunMode 子类       # 插件类(子类自身声明 NAME)

RunMode 子类约定:
  __init__(self, cfg)                  # 板卡配置,各模式自取所需段
  launch(self, board, name, t) -> (channel, cmdline, done)
                                       # 校验目标字段 + 按模式上电/传输;
                                       # 返回流式引擎要用的 (板的串口通道, 待发命令);
                                       # cmdline=None 表示零写入被动收流(watch);
                                       # done 非 None 表示 launch 已自行收束
                                       # (如 uboot 只加载不执行 -> 'loaded'),
                                       # runner 跳过流式直接返回

分工:模式插件只解释"这个目标怎么弄起来"(上电方式/传不传输/命令形态);
流式引擎/断言/收尾/repeat 由 runner 统一持有——任何模式的判定与收尾
语义完全一致,这是共享代码保证的不变量,不靠各插件自觉。
类属性 NAME 对应 [run.*].mode。可用的域依赖:board(板域)/ serial /
console。插件之间禁止互相 import。在此目录新建 .py 文件即自动注册。
"""
import re
import sys
from abc import ABC, abstractmethod


def expand_cmd(name, t):
    """展开目标 cmd 模板(执行命令是配置数据,不是代码):变量取本目标配置键,
    模式级缺省(如 uboot 的 {addr}/{entry})由各模式在调用前 setdefault 注入;
    未知变量报错指名,不静默留 {var} 字面量"""

    def _sub(m):
        k = m.group(1)
        if k not in t or t[k] is None:
            sys.exit(f'run.{name} 的 cmd 用了 {{{k}}},但目标未配置该键')
        return str(t[k])

    return re.sub(r'\{(\w+)\}', _sub, t['cmd'])


class RunMode(ABC):
    """启动模式抽象:一个 [run.<名>] 目标"怎么弄起来"——封装 = 上电方式/
    传输与否/命令形态藏在类里;多态 = runner 按 [run.*].mode 选子类,
    流式/断言/收尾共用"""

    NAME = None            # 注册名(子类必填),对应 [run.*].mode

    @abstractmethod
    def launch(self, board, name, t):
        """校验 + 上电 + 传输;返回 (channel, cmdline, done)"""
