"""boardctl — 开发板控制工具包(设计参考 crates.io 上的 ostool)

结构(松耦合,单向依赖):
  config.py    板卡 TOML 加载(不依赖其他模块)
  session.py   U-Boot 串口会话(依赖 config)
  power.py     电源控制与冷启动(依赖 config, session)
  console.py   交互终端(依赖 config, session, power)
  runner.py    run/cmd 编排(依赖上述 + plugins)
  cli.py       命令行入口,只做接线
  plugins/     插件(按目录约定自动发现,见 plugins/__init__.py)
"""
