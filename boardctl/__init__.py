"""boardctl — 开发板控制工具包(设计参考 crates.io 上的 ostool)

四域拆分(松耦合,单向依赖:接线→编排→板域→{电源,串口,捕获,控制台,指令域}):
  serial.py    串口域:纯字节通道,fd 借出(不依赖其他模块)
  stream.py    常驻捕获域:读线程持续把通道字节落进捕获日志,等待 = 水位 +
               谓词 + 条件变量唤醒;显示(tap)挂捕获事件即捕即显;
               fd 借出经 park/resume 让位(依赖 serial)
  console.py   控制台域:板上交互载荷(U-Boot/Linux shell/其他 CLI)的
               提示符会话——等提示符/执行命令都在捕获流的水位上展开(依赖 stream)
  power.py     电源域:Power 门面包 PowerDevice 插件,纯电源动作绝不碰串口,
               只持节拍值 reset_delay(节拍编排在板域)(依赖 plugins)
  shell.py     指令域:本机/ssh 命令执行(依赖 config)
  board.py     开发板域:Board 组合 SerialChannel + ConsoleStream + Power +
               Console(镜像配置的 [serial]/[power]/[console] 段),冷启动/
               静默上电/会话工厂;显示(tap)生命周期:上电前挂、断电前摘、
               程序化调用可换出口;上下文管理器起停捕获线程(依赖 power,
               serial, stream, console)
  config.py    板卡 TOML 加载(不依赖其他模块)
  runner.py    run 编排域:Runner,一块板 ↔ 多个 runner(依赖 board + plugins)
  cli.py       命令行入口,只做接线(google-fire)
  mcp_server.py MCP server(依赖 runner)
  plugins/     插件,三族:transport(传输)、power(电源)、mode(启动模式,
               [run.*].mode 选择)——插件即类,按目录约定自动发现
               (见 plugins/__init__.py;执行命令是 [run.*].cmd 配置模板,
               不是插件)
"""
