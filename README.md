# remote-serial / boardctl

开发板控制工具(设计参考 [ostool](https://crates.io/crates/ostool)):每块开发板一个
TOML 配置,**模块化 + 插件化**架构——加传输方式/执行方式只需在插件目录丢一个文件,
改某块功能只需动对应模块。

当前接入的板卡:**Sipeed LicheeRv Nano**(Sophgo SG2002 / CV181x,RISC-V 玄铁 C906,
U-Boot 2021.10,提示符 `soph#`),串口经 TCP 桥(gem12)透传,电源为小米智能插座。

## 快速上手

```bash
./boardctl.sh -b sg2002 run           # 列出该板一键启动目标
./boardctl.sh -b sg2002 run hello     # 裸机测试:冷启动→传输→go→断言→断电
./boardctl.sh -b sg2002 run script    # U-Boot 脚本测试
./boardctl.sh -b sg2002 console       # 交互终端(Ctrl-\ 退出;配置 off_on_exit 时退出自动断电)
./boardctl.sh -b sg2002 cmd 'printenv'
./boardctl.sh -b sg2002 exec 'ls /srv/tftp'   # 在板卡命令环境执行 shell(配置 ssh_host 则经 ssh 远端执行)
./boardctl.sh -b sg2002 send FILE [--method loady|tftp] [--addr 0x80080000]
./boardctl.sh -b sg2002 power on|off|status
./boardctl.sh -b sg2002 reset
# 等价:./.venv/bin/python -m boardctl ...(任意目录可用 boardctl.sh)
```

## 架构(松耦合,单向依赖)

```
boardctl/
├── cli.py        命令行接线(argparse + 分发,无业务逻辑)
├── config.py     板卡 TOML 加载(不依赖其他模块)
├── session.py    U-Boot 串口会话 ← config
├── power.py      电源/冷启动   ← config, session
├── console.py    交互终端       ← config, session, power
├── runner.py     run/cmd 编排   ← 上述全部 + plugins
└── plugins/      插件(目录约定自动发现,零注册代码)
    ├── transport/   传输插件:loady.py、tftp.py
    ├── executors/   执行插件:go.py、source.py、none.py
    └── power/       电源插件:mijia.py(原生小米云调用,免子进程)
```

**插件接口**(接口约定写在各 `__init__.py` 里;插件可选声明 `CFG_SECTION` + `DEFAULTS` 自带配置默认值,TOML 优先):

- 传输插件(`plugins/transport/xxx.py`):`NAME` + `send(cfg, path, addr) -> bool`
- 执行插件(`plugins/executors/xxx.py`):`NAME` + `build_cmd(addr) -> str | None`
- 电源插件(`plugins/power/xxx.py`):`NAME` + `set_power(cfg, on)` + `get_power(cfg) -> bool | None`

新建插件 = 加一个文件,`--method`/`[run].exec` 立即可用,核心代码零改动。

## 板卡配置(boards/*.toml)

搜索顺序(先找到的优先):`$BOARDCTL_BOARDS` → 当前目录 `./boards` →
**`~/.config/boardctl/boards/`(推荐:用户自己的板放这里)** → 包内置示例。

| 段 | 键 | 说明 |
|---|---|---|
| 顶层 | `ssh_host` | 命令执行位置:空 = 本机(power/exec 等);填 ssh 别名(如 `gem12`)= 经 ssh 在远端主机执行,别名/端口/用户走 `~/.ssh/config` |
| `[serial]` | `url` / `timeout` | 串口桥 URL(本板为 `socket://...` 裸 TCP) |
| `[uboot]` | `prompt` / `load_addr` | 提示符、默认加载地址 |
| | `server_ip` / `ensure_server_ip` | TFTP 服务器地址;该 U-Boot 无 saveenv,连接时自动恢复 |
| `[power]` | `method = "mijia"` + `[power.mijia]` dev_name/did | **方式一·电源插件**:进程内原生调用小米云(凭证复用 `~/.config/mijia-api/auth.json`,首次需 `mijiaAPI login` 扫码),不走 ssh_host |
| | `method = "command"` + `on_cmd`/`off_cmd`/`status_cmd` | **方式二·命令插件**:任意开关机 shell 命令(经 ssh_host 决定本机/远端);method 未配置时默认即此。改 `method` 一行切换 |
| | `off_on_exit = true` | console 退出时自动断电(覆盖所有退出路径:Ctrl-\、Ctrl-A x、kill、串口掉线) |
| `[tftp]` | `method=remote` + `ssh_host`/`remote_dir` | scp 到远端 tftpd(gem12 的 tftpd-hpa) |
| | `method=local` + `local_dir` | 本机临时拉起 `tftp_server.py`(UDP 69 需特权,退出自动回收) |
| `[loady]` | `sender` | Ymodem 发送器(Arch 为 `lrzsz-sb`) |
| `[run.<名字>]` | `file` / `exec` / `method` / `timeout` | 一键启动目标(exec/method 即插件名) |
| | `addr` / `entry` | 加载地址 / 跳转执行地址(`go 0x...` 的目标);缺省都取 `uboot.load_addr`,加载与入口不同时分别指定 |
| | `reset_before` | 开头冷启动:关→开→等提示符(从任意脏状态恢复) |
| | `after = off/reset/none` | 收尾动作 |
| | `expect = [..]` | 输出断言,全命中才 PASS(退出码 0/1) |

## 端到端验收

```bash
./.venv/bin/python e2e/verify_e2e.py     # reset→tftp 部署→原始流逐字节断言,两套测试
```

裸机测试:`e2e/baremetal/`(riscv64-linux-gnu-gcc,注意 DW APB UART reg-shift=2、
`-fno-pie`、`--build-id=none`)。脚本测试:`e2e/script/`(`source` 需 mkimage 的
legacy uImage 头)。构建细节与踩坑记录见 `e2e/README.md`。

## 依赖

Python 3.11+(stdlib `tomllib`)+ pyserial。开发安装:`uv venv && uv pip install -e '.[mijia]'`
(依赖唯一事实来源是 pyproject.toml)。交叉构建另需 `riscv64-linux-gnu-gcc`、
`mkimage`(uboot-tools)、`lrzsz`。

## 安装与发布

```bash
# 从 PyPI 安装(发布后)
pip install boardctl            # 核心:串口/console/cmd/send(loady)
pip install 'boardctl[mijia]'   # + 小米云电源插件

# 板卡配置搜索顺序:$BOARDCTL_BOARDS → ./boards → ~/.config/boardctl/boards → 包内置示例
# 用户自己的板卡放 ~/.config/boardctl/boards/(优先级高于包内置示例),不碰安装目录

# 发布(项目根目录)
uv build                        # 产出 dist/*.whl + *.tar.gz
uv publish --token <PyPI_API_Token>   # 建议先发 TestPyPI 演练
```

可选发布路径:GitHub 仓库 + Actions trusted publishing(打 tag 自动发布,免 token),
或直接 `pip install git+https://...`(零发布设施,适合私有/内网)。

