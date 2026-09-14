# Changelog

## 0.1.0 - 2026-09-15

首发版本:插件化开发板控制工具(设计参考 [ostool](https://crates.io/crates/ostool))。

- 子命令:`console`(交互串口终端)/ `power` / `reset` / `cmd` / `send` / `run` / `exec` / `boards`
- 插件三族,目录约定自动发现:
  - 传输:loady(Ymodem)、tftp(remote scp / local 内置服务器)
  - 执行:go、source、none
  - 电源:mijia(原生小米云)、command(特制开关机命令,默认)
- 一键启动 `run`:冷启动 → 传输 → 执行 → expect 断言(PASS/FAIL 退出码)→ 收尾(off/reset/none)
- 板卡配置 `boards/*.toml`,搜索顺序 `$BOARDCTL_BOARDS` → `./boards` → `~/.config/boardctl/boards` → 包内置
- `ssh_host` 字段:命令模式命令可经 ssh 在远端主机执行
- 端到端验收 `e2e/verify_e2e.py`(真机裸机 + U-Boot 脚本,逐字节断言)
