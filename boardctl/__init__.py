"""boardctl — 开发板控制工具包(设计参考 crates.io 上的 ostool)

四域拆分(松耦合,单向依赖:接线→编排→板域→{电源,串口,指令域}):
  serial.py    串口域:纯字节通道,fd 借出(不依赖其他模块)
  power.py     电源域:纯电源动作 on/off/status,绝不碰串口(依赖 plugins)
  shell.py     指令域:本机/ssh 命令执行(依赖 config)
  session.py   U-Boot 协议:在串口通道上收发命令(依赖 serial)
  board.py     开发板域:冷启动/静默上电/会话工厂,组合电源+串口(依赖 power, session)
  config.py    板卡 TOML 加载(不依赖其他模块)
  runner.py    run 编排:传输/执行/断言/收尾(依赖 board + plugins)
  cli.py       命令行入口,只做接线(google-fire)
  mcp_server.py MCP server(依赖 runner)
  plugins/     插件,两族:transport(传输)、power(电源)——插件即类,
               Transport / PowerDevice 子类,按目录约定自动发现
               (见 plugins/__init__.py;执行命令是 [run.*].cmd 配置模板,不是插件)
"""
