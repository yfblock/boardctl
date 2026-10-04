# boardctl

开发板控制工具(设计参考 [ostool](https://crates.io/crates/ostool)):每块开发板一个
TOML 配置,**模块化 + 插件化**架构——一键全流程(冷启动 → 传输 → 执行 → 断言 → 收尾),
加传输/执行/电源方式只需在插件目录丢一个文件。

- `run <目标>`:自动开机 → TFTP/Ymodem 传输 → `cmd` 模板执行(`go {addr}`、`booti …`)→
  输出断言(PASS/FAIL)→ 自动关机;`--repeat N` 多轮压测
- 串口输出**从上电起即捕即显**(常驻捕获 + 显示挂在捕获事件上):
  启动日志、命令回显、传输与执行输出全程可见,无窗口遗漏
- `power on|off|status`:手动电源控制/查询(经电源插件,run 全流程之外用)
- 被动观察 `mode = "watch"`:板子自己跑自动流程(bootcmd/板上脚本)时,
  全程零写入——不传输、不发任何命令(连 Ctrl-C 都不发,免得打断),
  静默上电后从第一个字节开始收流,断言与收尾照常
- 打断保证:Ctrl-C / kill 时若板在开机状态自动关机,程序结束后设备必为关
- 板卡配置放 `~/.config/boardctl/`,与代码完全解耦

## 安装

```bash
pip install boardctl             # 核心:run 全流程(tftp + loady 传输,command 电源)
pip install 'boardctl[mijia]'    # + 米家智能插座电源插件(原生小米云)
```

## 快速上手

```bash
# 1. 建板卡配置(模板:包内置示例,或仓库 boardctl/boards/example.toml)
mkdir -p ~/.config/boardctl
cp <模板> ~/.config/boardctl/myboard.toml       # 改串口地址/电源命令/启动目标

# 2. 跑起来
boardctl ls                        # 列出已配置开发板
boardctl -b myboard run            # 列出该板的启动目标
boardctl -b myboard run hello      # 全流程:开机→传输→执行→断言→关机
boardctl -b myboard run hello -r 10   # 10 轮压测,汇总 N/10 PASS
boardctl -b myboard power status   # 查电源(开/关)
boardctl -b myboard power off      # 手动关机(on 同理)
boardctl check                     # 校验板卡配置格式(省略板名则全部)
# 仅一块板时可省略 -b
```

## 板卡配置(~/.config/boardctl/*.toml)

搜索顺序:`$BOARDCTL_BOARDS`(临时覆盖)→ `~/.config/boardctl/` →
包内置示例(仅作模板兜底);本地/项目文件夹不参与解析。

| 段 | 键 | 说明 |
|---|---|---|
| 顶层 | `ssh_host` | 命令模式命令的执行位置:空 = 本机;填 ssh 别名(如 `myserver`)= 经 ssh 远端执行,别名/端口/用户走 `~/.ssh/config` |
| `[serial]` | `url` / `timeout` | 串口 URL(TCP 桥 `socket://host:port`、本地 `ttyUSB0`、`rfc2217://...`) |
| `[console]` | `prompt` | 控制台提示符(命令结束的判定依据)——板上跑什么配什么:U-Boot `=>`、Linux shell `#`…皆可 |
| `[uboot]` | `load_addr` | U-Boot 默认加载地址 |
| | `server_ip` / `ensure_server_ip` | TFTP 服务器地址;目标 U-Boot 环境易失(无 saveenv)时置 true,连接时自动恢复 |
| `[power]` | `method = "mijia"` + `[power.mijia]` dev_name/did | 电源插件:原生小米云(凭证复用 `mijiaAPI` CLI 登录态,首次需 `mijiaAPI login` 扫码),不走 ssh_host |
| | `[power.mijia]` prop | 开关量属性名,默认 `"on"`;部分设备的电源 prop 不是 `on`,按设备属性表改 |
| | `method = "command"` + `on_cmd`/`off_cmd`/`status_cmd` | 命令插件:任意开关机 shell 命令(经 ssh_host 决定本机/远端);method 未配置时默认即此 |
| `[tftp]` | `method=remote` + `ssh_host`/`remote_dir` | scp 到远端 tftpd 服务器 |
| | `method=external` + `local_dir` | **本机已有常驻 tftpd(如 tftpd-hpa)服务 UDP 69**:只把文件放进其根目录即可——不探测端口、不建服务器、免特权 |
| `[loady]` | `sender` | Ymodem 发送器(空则自动查找:Arch 为 `lrzsz-sb`,Debian/Ubuntu 为 `sb`) |
| `[run.<名字>]` | `mode` / `file` / `cmd` / `method` / `timeout` | 启动目标(mode 即模式插件名):`uboot`(缺省:传文件+cmd 执行,`{addr}`/`{entry}` 缺省 `uboot.load_addr`)、`console`(不传输,上电到提示符直接执行 `cmd`,无地址语义)、`watch`(被动观察:零写入,板子自己跑) |
| | `cmd` | U-Boot 执行命令模板:`go {addr}`、`source {addr}`、`booti {addr} - {fdt}`;变量取本目标键(`{addr}`/`{entry}` 缺省 `uboot.load_addr`),缺变量报错指名;不写 = 只加载不执行;命令序列写在 .scr 里 `source` |
| | `addr` / `entry` | 加载地址 / 跳转执行地址;缺省都取 `uboot.load_addr`,加载与入口不同时分别指定 |
| | `fdt` / `initrd` | booti 执行插件附加键:设备树地址(必需)/ initrd 地址(可选) |
| | `reset_before` | 开头自动开机:关→开→等提示符(不依赖设备初始状态) |
| | `after = off/reset/none` | 收尾动作(断电 / 重启回提示符 / 保持) |
| | `expect` / `expect_re` / `fail_re` | 输出断言:子串 / 正则须命中 / 正则禁止命中;全命中才 PASS,退出码 0/1。**fail_re 流式一命中即判负**(正则区分大小写,Linux `Kernel panic` 与 Rust `panicked` 需分别覆盖或用 `(?i)`) |
| | `fail_linger` | fail_re 命中后继续收集输出的秒数(默认 2)——让错误信息/栈吐完整再收工断电;0 = 立即收 |

## 架构(松耦合,单向依赖)

```
boardctl/
├── cli.py        命令行接线(google-fire 类组件,无业务逻辑)
├── config.py     板卡 TOML 加载(不依赖其他模块)
├── serial.py     串口域:纯字节通道 + fd 借出(不依赖其他模块)
├── stream.py     常驻捕获域:读线程持续捕字节进日志,等待 = 水位 + 谓词 + 条件变量;
│                 显示 tap 挂捕获事件即捕即显 ← serial
├── console.py    控制台域:提示符驱动的交互会话,U-Boot/Linux shell/其他 CLI 皆可 ← stream
├── power.py      电源域:Power 门面包 PowerDevice 插件,纯 on/off/status,绝不碰串口 ← plugins
├── board.py      开发板域:Board 组合 serial + stream + power + console(镜像配置段;
│                 上下文管理器起停捕获线程;显示 tap 上电前挂、断电前摘)
│                 ← power, serial, stream, console
├── shell.py      指令域:命令执行(本机/ssh)← config
├── runner.py     run 编排域:Runner(一块板 ↔ 多个 runner)← board + plugins
└── plugins/      插件即类(目录约定自动发现,零注册代码)
    ├── transport/   传输插件:loady.py、tftp.py(Transport 子类)
    ├── power/       电源插件:mijia.py(小米云)、command.py(命令,默认)
    └── mode/        启动模式插件:uboot.py、console.py、watch.py(RunMode 子类,
                     [run.*].mode 选择;流式/断言/收尾由 runner 统一持有)
```

**插件即类**(基类与约定写在各 `plugins/<族>/__init__.py`;插件模块提供
`PLUGIN = <类>`,类声明 `NAME` 与可选 `CFG_SECTION` + `DEFAULTS` 自带配置
默认值,TOML 优先;新建插件 = 丢一个文件):

- 传输插件:`Transport` 子类,`send(stream, path, addr) -> bool`(stream 为板借出的常驻捕获流,插件不自开连接;fd 借出前 `park()`、归还后 `resume()`)
- 电源插件:`PowerDevice` 子类,`on()` / `off()` / `status() -> bool | None`

新建插件 = 加一个文件,`[run].method`/`[power].method` 立即可用,核心零改动
(执行命令不是插件:它是 `[run].cmd` 配置模板,由 runner 展开)。

## MCP(让 Claude 等客户端直接操控开发板)

```bash
pip install 'boardctl[mcp]'
claude mcp add boardctl -- boardctl-mcp      # Claude Code;Desktop 填 mcpServers JSON 同理
```

之后模型可调用三个工具:`ls_boards`(列板卡与目标)、`power_status`(查电源)、
`run_target`(真机全流程测试:自动开关机 → 传输 → 执行 → 断言,`repeat` 支持压测)。
工具会真实控制硬件电源,描述中已注明;长任务注意客户端超时设置。

## 开发

```bash
git clone https://github.com/yfblock/boardctl && cd boardctl
uv venv && uv pip install -e '.[mijia]'   # 依赖唯一来源:pyproject.toml
uv run python tests/test_software.py      # 纯软件测试(无需硬件)
```

发布:打 tag(`git tag vX.Y.Z && git push origin vX.Y.Z`)即经 GitHub Actions
自动构建并发布到 PyPI(trusted publishing)。

## 依赖

Python 3.11+(stdlib `tomllib`)+ pyserial + fire(CLI 解析,传递依赖 termcolor)。
裸机测试固件交叉构建另需
`riscv64-linux-gnu-gcc`、`mkimage`(uboot-tools)、`lrzsz`。

## License

MIT(见 [LICENSE](LICENSE))
