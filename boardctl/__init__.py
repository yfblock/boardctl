"""boardctl — 开发板控制工具包(设计参考 crates.io 上的 ostool)

结构(松耦合,单向依赖):
  config.py    板卡 TOML 加载(不依赖其他模块)
  session.py   U-Boot 串口会话(依赖 config)
  power.py     电源控制与冷启动(依赖 config, session)
  shell.py     命令执行:本机/ssh(依赖 config)
  runner.py    run 编排:传输/执行/断言/收尾(依赖上述 + plugins)
  cli.py       命令行入口,只做接线(google-fire)
  mcp_server.py MCP server(依赖 runner)
  plugins/     插件,两族:transport(传输)、power(电源)
               (按目录约定自动发现,见 plugins/__init__.py;
               执行命令是 [run.*].cmd 配置模板,不是插件)
"""
