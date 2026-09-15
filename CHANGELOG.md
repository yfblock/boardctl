# Changelog

## 0.4.4 - 2026-09-15

- 泄漏修正:CHANGELOG 条目不再提及具体内网地址;真机验收目录(含特定硬件
  环境信息)整体移出仓库与发布产物,仓库工作树自此不含任何内网/个人环境信息

## 0.4.3 - 2026-09-15

- 修正 0.4.2 的发布瑕疵:v0.4.2 tag 误指向清理前的提交,wheel 内三处注释
  残留内网环境信息(仅代码注释,无功能影响);本版已干净

## 0.4.2 - 2026-09-15

- 内置板卡示例去个性化:`sg2002.toml`(含内网地址与个人环境)替换为通用模板
  `example.toml`(IP 一律使用 RFC 5737 文档网段)
- `-b` 不再默认 `sg2002`:未指定时若仅有一块用户板自动选中,多板时提示选择
- README 面向公开发布重写(去除内网环境信息与维护者发布说明)

## 0.4.1 - 2026-09-15

- 示例板卡配置:`run script` 目标补齐 `reset_before` + `after = "off"`
  (自动开关机;此前假设板已在提示符,设备关着会超时失败)

## 0.4.0 - 2026-09-15

**破坏性变更**:`boards` 子命令更名为 `ls`。

- **打断关机保证**:`run` 执行中若被 Ctrl-C / SIGTERM 打断或发生未捕获异常,
  且板卡处于开机状态,自动执行一次关机——保证程序结束后设备是关的;
  正常完成的收尾仍由 `[run].after` 决定(off/reset/none)

## 0.3.1 - 2026-09-15

- 板卡配置解析收窄:**只认 `~/.config/boardctl/boards/`**(`$BOARDCTL_BOARDS` 可临时
  覆盖;包内置示例降为最低优先级模板)。本地/项目文件夹不再参与解析,
  仓库根 boards/ 目录移除,示例移入包内(boardctl/boards/),打包不再需要 force-include

## 0.3.0 - 2026-09-15

**破坏性变更**:CLI 命令面极简化。

- 仅保留 `run`(一键全流程:冷启动→传输→执行→断言→收尾,`--repeat N` 压测)
  与 `boards`(列出板卡)
- 移除子命令:`console`、`power`、`reset`、`cmd`、`send`、`exec`;
  对应能力仍在:电源操作由 run 的 `reset_before`/`after` 与电源插件覆盖,
  传输/执行插件由 run 的 `method`/`exec` 驱动,均可经 Python API 使用
- `console` 交互终端模块随子命令移除(`off_on_exit` 配置项随之删除)
- 删除 boards/run.sh:开关机命令直接内联进板卡配置(command 电源模式安装态可用)
- e2e/verify_e2e.py 改为 Python API 驱动(不再依赖 CLI 子命令)

## 0.2.0 - 2026-09-15

- 新增执行插件:`booti`(引导 Linux raw 内核,run 目标 fdt 必需 / initrd 可选)、
  `bootm`(legacy uImage)
- `run --repeat N`:多轮压测,每轮冷启动(repeat>1 自动启用 reset_before),
  结束输出 `N/M 轮 PASS` 汇总,任一轮失败退出码 1
- 断言引擎增强(`expect` 保持子串语义,新增):
  - `expect_re`:正则列表,必须全部命中
  - `fail_re`:正则列表,命中即 FAIL(如 `panic`、`Unknown command`)
- 执行插件接口扩展:`build_cmd(addr, t)` 第二参数为 run 目标配置表
  (booti/bootm 用它读取 fdt/initrd)
- 目录重组:boards/(板卡配置+板级资产)、examples/、tests/(纯软件)、
  e2e/(真机验收);删除 requirements.txt 与 main.py;新增 LICENSE(MIT)、
  CHANGELOG、CI(push/PR 自动编译+软件测试+构建检查)

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
