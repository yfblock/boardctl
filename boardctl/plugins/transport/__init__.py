"""传输插件接口约定:

每个插件模块需要提供:
  NAME: str                     # 名字,对应 --method / [run.*].method
  send(cfg, path, addr) -> bool  # 把文件传到设备的 addr,成功返回 True

可用的依赖:boardctl.config(BASE_DIR 等)、boardctl.session(UbootSession)。
插件之间禁止互相 import。在此目录新建 .py 文件即自动注册。
"""
