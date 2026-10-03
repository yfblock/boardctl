"""boardctl — 开发板控制工具包(设计参考 crates.io 上的 ostool)

四域拆分(松耦合,单向依赖:接线→编排→板域→{电源,串口,控制台,指令域}):
  serial.py    串口域:纯字节通道,fd 借出(不依赖其他模块)
  console.py   控制台域:板上交互载荷(U-Boot/Linux shell/其他 CLI)的
               提示符会话——prompt 可配,Ctrl-C 可打断(依赖 serial)
  power.py     电源域:Power 门面包 PowerDevice 插件,纯电源动作绝不碰串口(依赖 plugins)
  shell.py     指令域:本机/ssh 命令执行(依赖 config)
  board.py     开发板域:Board 组合 SerialChannel + Power + Console(镜像
               配置的 [serial]/[power]/[console] 段),冷启动/静默上电/会话
               工厂(依赖 power, console)
  config.py    板卡 TOML 加载(不依赖其他模块)
  runner.py    run 编排域:Runner,一块板 ↔ 多个 runner(依赖 board + plugins)
  cli.py       命令行入口,只做接线(google-fire)
  mcp_server.py MCP server(依赖 runner)
  plugins/     插件,三族:transport(传输)、power(电源)、mode(启动模式,
               [run.*].mode 选择)——插件即类,按目录约定自动发现
               (见 plugins/__init__.py;执行命令是 [run.*].cmd 配置模板,
               不是插件)
"""
