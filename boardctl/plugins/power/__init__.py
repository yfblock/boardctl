"""电源插件接口约定:

每个插件模块需要提供:
  NAME: str                       # 名字,对应 [power].method
  set_power(cfg, on: bool)        # 开/关设备电源
  get_power(cfg) -> bool          # 查询电源状态

插件在 boardctl 进程内原生执行(不经过 ssh_host)。
在此目录新建 .py 文件即自动注册。
"""
