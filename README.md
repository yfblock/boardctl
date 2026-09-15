# boardctl

开发板控制工具(设计参考 [ostool](https://crates.io/crates/ostool)):每块开发板一个
TOML 配置,**模块化 + 插件化**架构——一键全流程(冷启动 → 传输 → 执行 → 断言 → 收尾),
加传输/执行/电源方式只需在插件目录丢一个文件。

- `run <目标>`:自动开机 → TFTP/Ymodem 传输 → `go`/`source`/`booti` 执行 →
  输出断言(PASS/FAIL)→ 自动关机;`--repeat N` 多轮压测
- 打断保证:Ctrl-C / kill 时若板在开机状态自动关机,程序结束后设备必为关
- 板卡配置放 `~/.config/boardctl/boards/`,与代码完全解耦

## 安装

```bash
pip install boardctl             # 核心:run 全流程(tftp + loady 传输,command 电源)
pip install 'boardctl[mijia]'    # + 米家智能插座电源插件(原生小米云)
```

## 快速上手

```bash
# 1. 建板卡配置(模板:包内置示例,或仓库 boardctl/boards/example.toml)
mkdir -p ~/.config/boardctl/boards
cp <模板> ~/.config/boardctl/boards/myboard.toml   # 改串口地址/电源命令/启动目标

# 2. 跑起来
boardctl ls                        # 列出已配置开发板
boardctl -b myboard run            # 列出该板的启动目标
boardctl -b myboard run hello      # 全流程:开机→传输→执行→断言→关机
boardctl -b myboard run hello -r 10   # 10 轮压测,汇总 N/10 PASS
# 仅一块板时可省略 -b
```

## 板卡配置(~/.config/boardctl/boards/*.toml)

搜索顺序:`$BOARDCTL_BOARDS`(临时覆盖)→ `~/.config/boardctl/boards/` →
包内置示例(仅作模板兜底);本地/项目文件夹不参与解析。

| 段 | 键 | 说明 |
|---|---|---|
| 顶层 | `ssh_host` | 命令模式命令的执行位置:空 = 本机;填 ssh 别名(如 `myserver`)= 经 ssh 远端执行,别名/端口/用户走 `~/.ssh/config` |
| `[serial]` | `url` / `timeout` | 串口 URL(TCP 桥 `socket://host:port`、本地 `ttyUSB0`、`rfc2217://...`) |
| `[uboot]` | `prompt` / `load_addr` | U-Boot 提示符、默认加载地址 |
| | `server_ip` / `ensure_server_ip` | TFTP 服务器地址;目标 U-Boot 环境易失(无 saveenv)时置 true,连接时自动恢复 |
| `[power]` | `method = "mijia"` + `[power.mijia]` dev_name/did | 电源插件:原生小米云(凭证复用 `mijiaAPI` CLI 登录态,首次需 `mijiaAPI login` 扫码),不走 ssh_host |
| | `method = "command"` + `on_cmd`/`off_cmd`/`status_cmd` | 命令插件:任意开关机 shell 命令(经 ssh_host 决定本机/远端);method 未配置时默认即此 |
| `[tftp]` | `method=remote` + `ssh_host`/`remote_dir` | scp 到远端 tftpd 服务器 |
| | `method=local` + `local_dir` | 本机临时拉起内置 TFTP 服务器(UDP 69 需特权,退出自动回收) |
| `[loady]` | `sender` | Ymodem 发送器(空则自动查找:Arch 为 `lrzsz-sb`,Debian/Ubuntu 为 `sb`) |
| `[run.<名字>]` | `file` / `exec` / `method` / `timeout` | 启动目标(exec/method 即插件名) |
| | `addr` / `entry` | 加载地址 / 跳转执行地址;缺省都取 `uboot.load_addr`,加载与入口不同时分别指定 |
| | `fdt` / `initrd` | booti 执行插件附加键:设备树地址(必需)/ initrd 地址(可选) |
| | `reset_before` | 开头自动开机:关→开→等提示符(不依赖设备初始状态) |
| | `after = off/reset/none` | 收尾动作(断电 / 重启回提示符 / 保持) |
| | `expect` / `expect_re` / `fail_re` | 输出断言:子串 / 正则须命中 / 正则禁止命中(如 panic);全命中才 PASS,退出码 0/1 |

## 架构(松耦合,单向依赖)

```
boardctl/
├── cli.py        命令行接线(argparse + 分发,无业务逻辑)
├── config.py     板卡 TOML 加载(不依赖其他模块)
├── session.py    U-Boot 串口会话 ← config
├── power.py      电源/冷启动   ← config, session
├── shell.py      命令执行(本机/ssh)← config
├── runner.py     run 编排       ← 上述全部 + plugins
└── plugins/      插件(目录约定自动发现,零注册代码)
    ├── transport/   传输插件:loady.py、tftp.py
    ├── executors/   执行插件:go.py、source.py、none.py、booti.py、bootm.py
    └── power/       电源插件:mijia.py(小米云)、command.py(命令,默认)
```

**插件接口**(约定写在各 `__init__.py`;可选声明 `CFG_SECTION` + `DEFAULTS` 自带配置默认值,TOML 优先):

- 传输插件:`NAME` + `send(cfg, path, addr) -> bool`
- 执行插件:`NAME` + `build_cmd(addr, t) -> str | None`
- 电源插件:`NAME` + `set_power(cfg, on)` + `get_power(cfg) -> bool | None`

新建插件 = 加一个文件,`[run].method`/`exec`/`[power].method` 立即可用,核心零改动。

## 开发

```bash
git clone https://github.com/yfblock/boardctl && cd boardctl
uv venv && uv pip install -e '.[mijia]'   # 依赖唯一来源:pyproject.toml
uv run python tests/test_software.py      # 纯软件测试(无需硬件)
```

发布:打 tag(`git tag vX.Y.Z && git push origin vX.Y.Z`)即经 GitHub Actions
自动构建并发布到 PyPI(trusted publishing)。

## 依赖

Python 3.11+(stdlib `tomllib`)+ pyserial。裸机测试固件交叉构建另需
`riscv64-linux-gnu-gcc`、`mkimage`(uboot-tools)、`lrzsz`。

## License

MIT(见 [LICENSE](LICENSE))
