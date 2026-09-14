"""执行插件接口约定(文件加载后如何启动):

每个插件模块需要提供:
  NAME: str                            # 名字,对应 [run.*].exec
  build_cmd(addr, t=None) -> str|None  # 返回要在 U-Boot 执行的命令;None = 只加载不执行
                                       # addr = entry 地址;t = run 目标配置表(可读 fdt/initrd 等附加键)

在此目录新建 .py 文件即自动注册。
"""
