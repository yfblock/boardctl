"""watch 执行插件:被动观察——boardctl 不向设备发送任何命令。

适用场景:板子自己完成传输与执行(U-Boot bootcmd、板上自动脚本等),
不需要外部敲 loady/tftpboot/go。此时 boardctl 的职责收窄为:
静默上电(串口先挂好,从启动第一个字节开始收)→ 被动收流 → 断言 → 收尾。
"""

NAME = 'watch'
PASSIVE = True   # runner 据此走被动分支:不传输文件、零写入(连 Ctrl-C 都不发)


def build_cmd(addr, t=None):
    """被动模式无命令可发;返回 None 仅为满足插件接口约定——
    runner 见 PASSIVE 即接管,不会走到这里"""
    return None
