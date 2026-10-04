# Changelog

## 0.14.0 - 2026-10-04

- **配置建模 msgspec:加载即校验(新增依赖 msgspec)**——schema.py 用
  Struct 声明板卡 toml 的形状,加载管线 = toml 解析 → 建模校验 → 剥
  缺省 → 插件默认值合并。拼错的键(如 expcet)、类型错误(timeout =
  "abc")、非法枚举(after = "reboot")、负超时、核心段未知键**当场
  报错且带字段路径**;核心段([serial]/[console]/[uboot]/[run.*])严格
  (未知键拒绝),插件段(power/tftp/loady)宽容;核心默认值从此只在
  schema.py 声明一份。顺带修复 `[loady]` 用户段从未进入配置的静默丢失
  (此前一直被 sender 自动查找兜底掩盖)
- **清除旧式配置格式(不兼容,加载即报错并给字段路径)**——归一层
  退役,格式唯一;旧配置按下表迁移(改完可用 `boardctl check` 验证):
  | 旧写法 | 迁移为 |
  |---|---|
  | `[uboot]` 段的 `prompt = "..."` | `[console]` 段的 `prompt = "..."` |
  | `expect = "标记"`(标量) | `expect = ["标记"]`(列表) |
  | `exec = "watch"` | `mode = "watch"` |
  | `reset_after = true` | `after = "reset"` |
- **新增 `boardctl check [板名]` 子命令**:按 schema 逐板校验配置格式,
  OK/报错逐板报告,有无效配置退出码 1;省略板名校验全部,不碰硬件
- **`-h` 帮助直接输出**:不再进 less 全屏分页(fire 在 tty 下的默认
  行为),顺序输出可回滚可管道
- 内部:available_boards 收敛为 pathlib glob;runner 断言取值不再
  逐处防御标量(类型已由 schema 保证);check 的未知板判断收敛回
  load_board 单点;注释段落化(概要行+空行+要点列表)

## 0.13.0 - 2026-10-04

- **串口输出从上电起即捕即显(事件驱动显示)**:新增 stream 域——常驻
  捕获线程持续读串口进日志,显示(tap)挂捕获事件,读到即上屏,全链
  迁离轮询。冷启动/传输/执行全程可见:SPL 字节、U-Boot banner、命令
  回显原样上屏,等待不再是黑盒
  - 状态行(断电.../上电.../等待控制台提示符...)先落屏、再挂显示、
    再上电——不被启动字节撕行,也不晚于对串口的任何写入;断电窗口的
    线路噪声不上屏(摘显示前放完积压,尾显不丢)
  - 程序化调用(run_collect/MCP)可把显示出口换成缓冲——设备字节
    不落服务进程的 stdout
- **传输成功静默**:tftp/loady 成功不再打印"OK: N 字节"汇总行——回显
  (即捕即显)里已有 tftpboot / Bytes transferred / Total Size,重复无
  信息量;只有本地才有的知识(大小核对不符)或失败判定才开口
- **`[run.*].mode` 启动模式插件族(新增配置键,缺省 uboot)**:mode =
  uboot / console / watch 细分目标形态,"这个目标怎么弄起来"(上电
  方式/传不传输/命令形态)的解释权归插件;流式执行/断言/收尾/repeat
  由 runner 统一持有,任何模式的判定语义一致。旧写法 exec = "watch"
  等价 mode = "watch",存量配置零改动
- **域收口完成(纯内部,零配置影响)**:console 域落地——Board 不再
  假定 U-Boot,控制台载荷由 `[console].prompt` 决定;电源/编排亦收口
  为 Power / Runner 类,Board 组合 serial / stream / power / console
  四域,显示(tap)生命周期归板;loady 的 fd 借出经 park/resume 让位,
  借出期间协议字节归发送器、resume 后无缝接上

## 0.12.0 - 2026-10-03

- **四域拆分(纯内部重构,零配置影响)**:core 按 串口/开发板/电源/指令
  四域重新切分,依赖单向:`board → {power, session/serial, shell}`——
  - 新增 `serial.py`(串口域):`SerialChannel` 纯字节通道,收编原先散在
    UbootSession(打开/读写)与 loady 插件(fd 借出 + O_NONBLOCK 清理)
    的底层串口细节;`blocking_fd()` 把 fd 干净地借给 Ymodem 发送器
  - 新增 `board.py`(开发板域):`Board.cold_boot()` / `quiet_boot()` /
    会话工厂——开机流程从 power.py 搬入(电源域不再长串口知识),
    冷启动与静默上电的语义不变
  - `power.py` 收窄为纯电源动作(on/off/status + power/reset 子命令),
    绝不碰串口;`session.py` 变 U-Boot 协议层,字节数据经 SerialChannel
  - `shell.py`(指令域)不动
- **插件即类**:transport/power 两族插件从"模块函数"改为类——基类
  `Transport` / `PowerDevice`(抽象 on/off/status 或 send)住在各插件包
  `__init__.py`,插件模块提供 `PLUGIN = <类>`,类声明 `NAME` 与可选
  `CFG_SECTION`/`DEFAULTS`(config 合并默认值的约定不变)。封装 = 各插件
  细节藏在类里;多态 = 不同子类同一接口。新增电源插件示例:实现
  `on()/off()/status()` 三方法即可被 `[power].method` 选中

## 0.11.0 - 2026-10-03

- **移除 tftp `method = "local"`(不兼容)**:boardctl 不再自建临时 TFTP
  服务器(内置 `tftp_server.py` 随包删除)——文件就位只剩两种显式方式:
  `remote`(scp 到远端 tftpd)与 `external`(本机常驻 tftpd,只落文件);
  没有 tftpd 的场景用 `loady`(Ymodem 串口传输,免特权免服务器)。
  配置残留 `local` 会得到迁移指引而非晦涩报错
- **执行插件族退役,`exec` → `cmd` 模板(不兼容)**:执行命令回归配置数据——
  `[run.<名>] cmd = "go {addr}"`。变量取本目标配置键(`{addr}`/`{entry}` 缺省
  `uboot.load_addr`),缺变量报错指名;不写 `cmd` = 只加载(原 exec=none);
  命令序列仍写 .scr 经 `source {addr}` 执行。`exec = "watch"` 保留(被动模式
  是行为不是命令)。迁移映射:`go`→`cmd = "go {entry}"`、
  `source`→`cmd = "source {entry}"`、`booti`→`cmd = "booti {entry} - {fdt}"`
  (带 initrd 用 `{initrd}`)、`bootm`→`cmd = "bootm {entry} {initrd} {fdt}"`、
  `none`→删除 exec 行

## 0.10.0 - 2026-10-03

- **CLI 引擎 cyclopts → google-fire**:Boardctl 类即命令面(方法即子命令),
  命令面与用法完全不变(`-b 板名` 仍置于子命令前、`run <目标> -r N`、
  `power on|off|status`、`ls`、无 `-b` 时单板自动选中);`sys.exit` 退出码
  原样传播(0/1/130 语义不变)。依赖 cyclopts → fire(传递依赖 termcolor)。
  差异:fire 不做参数校验,power state 与 repeat 改为本工具手工校验;
  纯数字板名会被 fire 字面量化成 int,已兜底还原;帮助页格式变化
- 修复 CI 测试两处脆断言(cyclopts 版本相关的退出码断言、
  `$BOARDCTL_BOARDS` 目录替换语义的误断言——实为前置优先)

## 0.9.0 - 2026-10-01

- **板卡配置目录去掉 `boards/` 子目录(不兼容)**:板卡 TOML 直接放
  `~/.config/boardctl/`(即 board_dir 本身),不再需要 `boards/` 子文件夹;
  `$BOARDCTL_BOARDS` 环境变量语义不变(指向的目录里直接放 `*.toml`)。
  从旧版本升级:`mv ~/.config/boardctl/boards/*.toml ~/.config/boardctl/`

## 0.8.0 - 2026-10-01

- **`power` 子命令**:`boardctl [-b 板名] power on|off|status`——
  直接经电源插件控制/查询电源(run 全流程之外的手动操作);
  status 对可解析的插件(mijia)打印 开/关,不可解析的(command)原样输出
- **mijia 插件属性名可配**:部分设备的开关量 prop 不是 `'on'`,
  新增 `[power.mijia] prop = "..."`(默认仍为 `'on'`,原配置不受影响)
- **CLI 迁移到 cyclopts**(弃手写 argparse):注解式声明命令与参数,
  命令面与用法完全不变(`-b 板名` 仍置于子命令前、`run <目标> -r N`、
  `power on|off|status`、`ls`);全局 `-b` 经 meta 入口解析,板卡配置
  加载一次注入子命令;新增 `--version`;非法参数的错误提示更友好

## 0.7.0 - 2026-10-01

- **被动观察模式 `exec = "watch"`**:板子自己完成传输与执行(U-Boot bootcmd、
  板上自动脚本)时,boardctl 全程零写入——不敲 `loady`/`tftpboot`/`go`,
  连冷启动等提示符的 Ctrl-C 都不发(那会打断板上自动流程);只做:
  静默上电(串口先挂好、清掉断电期线路噪声,从启动第一个字节开始收)→
  被动收流 → 断言(expect/fail_re/fail_linger 照常)→ after 收尾;
  此类目标不需要也不允许 `file`(板子自行获取)
- 执行插件接口新增可选声明 `PASSIVE = True`(watch 即第一个使用者);
  主动模式缺 `file` 由裸 KeyError 改为明确报错

## 0.6.3 - 2026-09-29

- **fail_re 命中后延迟收工**:新增 `[run].fail_linger`(秒,默认 2)——
  fail_re 命中后不立即断电,先继续收集输出让错误信息/栈吐完整,
  到时再判 FAIL 走收尾;置 0 恢复立即收工。续收窗口内只收输出,
  不再做其他结束判定

## 0.6.2 - 2026-09-29

- **fail_re 流式即时判负**:执行流中 `fail_re` 一命中立即收工
  (结束原因 `fail`),判 FAIL 并执行 after 收尾——panic 类故障即时止损,
  不再干等 timeout(此前 fail_re 只在流结束后由断言统一判定,流式期间
  正向断言可提前收工而负向不行);同批输出正负断言双命中时判负优先

## 0.6.1 - 2026-09-29

- **tftp `method` 拆分:显式声明,不再猜测**(`local` 原先一个方法混装两种语义,
  依端口探测猜意图,是非 root 误报问题的根源)
  - 新增 `method = "external"`:本机已有常驻 tftpd(如 tftpd-hpa)服务
    UDP 69 时,只把文件放进其根目录——**不探测端口、不建服务器、免特权**;
    文件已在 `local_dir` 不重复落盘(修自拷贝 `SameFileError`)
  - `method = "local"` 收窄为"boardctl 自建临时 TFTP 服务器":探测仅为
    快速失败并给出替代——69 被占用提示改 `external`,空闲但无特权提示
    `sudo`/`external`/`loady`(占用判定读 `/proc/net/udp`:非 root 试绑
    特权端口永远 EACCES,内核先查权限再查占用,原探测无法区分)
- **run 收尾兜底**:`after` 移入 `finally`——传输失败、插件 `sys.exit`、
  `exec=none` 早退等任何退出路径都会执行收尾(`after=off` 时失败也断电,
  修复"冷启动后传输报错、板子留在开机状态");收尾自身异常只报告,
  不掩盖原始错误

## 0.6.0 - 2026-09-15

- **流式执行**:run 的执行阶段改为实时流式输出(不再整段等满 timeout 才打印)
  - 正向断言(expect/expect_re)全部命中 → 提前收工:死循环类目标(如 go 裸机)
    从"等满 timeout"变为"标记出完即收"
  - 提示符重现即收(source 等回提示符的执行器)
- **交互模式** `[run].interactive = true`(TTY):输出实时流 + stdin 原样转发进设备
  ——`go`/`booti` 进入内核后可直接在 run 会话里输入;`Ctrl-\` 退出
  (非 TTY/MCP 自动退化为流式+限时,行为兼容)
- run_collect 轮结果新增 `ended` 字段(prompt/matched/timeout/user/loaded)

## 0.5.0 - 2026-09-15

- **MCP server**:`pip install 'boardctl[mcp]'` 后 `claude mcp add boardctl --
  boardctl-mcp` 即可让 Claude 等客户端直接操控开发板
  - 工具:`ls_boards`(列板卡与目标)/ `power_status`(查电源)/
    `run_target`(真机全流程测试,repeat 支持压测;会真实控制硬件电源)
  - 兼容 mcp 1.x(FastMCP)与 2.x(MCPServer)
  - 新增 `runner.run_collect()`:程序化执行 API,捕获输出返回结构化结果
    (CLI 实时打印行为不变);tests/test_mcp.py 协议级冒烟进 CI

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
