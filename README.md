# remote-serial / boardctl

开发板控制工具(设计参考 [ostool](https://crates.io/crates/ostool)):每块开发板一个
TOML 配置,**模块化 + 插件化**架构——加传输方式/执行方式只需在插件目录丢一个文件,
改某块功能只需动对应模块。

当前接入的板卡:**Sipeed LicheeRv Nano**(Sophgo SG2002 / CV181x,RISC-V 玄铁 C906,
U-Boot 2021.10,提示符 `soph#`),串口经 TCP 桥(gem12)透传,电源为小米智能插座。

## 快速上手

```bash
./boardctl.sh -b sg2002 run              # 列出该板的一键启动目标
./boardctl.sh -b sg2002 run hello        # 全流程:冷启动→传输→执行→断言→断电
./boardctl.sh -b sg2002 run hello -r 10  # 10 轮压测,汇总 N/10 PASS
./boardctl.sh boards                     # 列出已配置开发板
# 等价:./.venv/bin/python -m boardctl ...(任意目录可用 boardctl.sh)
```

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
    └── power/       电源插件:mijia.py(原生小米云)、command.py(命令,默认)
```

**插件接口**(接口约定写在各 `__init__.py` 里;插件可选声明 `CFG_SECTION` + `DEFAULTS` 自带配置默认值,TOML 优先):

- 传输插件(`plugins/transport/xxx.py`):`NAME` + `send(cfg, path, addr) -> bool`
- 执行插件(`plugins/executors/xxx.py`):`NAME` + `build_cmd(addr) -> str | None`
- 电源插件(`plugins/power/xxx.py`):`NAME` + `set_power(cfg, on)` + `get_power(cfg) -> bool | None`

新建插件 = 加一个文件,`--method`/`[run].exec` 立即可用,核心代码零改动。

## 板卡配置(boards/*.toml)

板卡配置**只认 `~/.config/boardctl/boards/`**(搜索顺序:`$BOARDCTL_BOARDS` 覆盖 →
`~/.config/boardctl/boards/` → 包内置示例兜底;本地/项目文件夹不参与解析)。

| 段 | 键 | 说明 |
|---|---|---|
| 顶层 | `ssh_host` | 命令模式命令的执行位置:空 = 本机;填 ssh 别名(如 `gem12`)= 经 ssh 在远端主机执行,别名/端口/用户走 `~/.ssh/config` |
| `[serial]` | `url` / `timeout` | 串口桥 URL(本板为 `socket://...` 裸 TCP) |
| `[uboot]` | `prompt` / `load_addr` | 提示符、默认加载地址 |
| | `server_ip` / `ensure_server_ip` | TFTP 服务器地址;该 U-Boot 无 saveenv,连接时自动恢复 |
| `[power]` | `method = "mijia"` + `[power.mijia]` dev_name/did | **方式一·电源插件**:进程内原生调用小米云(凭证复用 `~/.config/mijia-api/auth.json`,首次需 `mijiaAPI login` 扫码),不走 ssh_host |
| | `method = "command"` + `on_cmd`/`off_cmd`/`status_cmd` | **方式二·命令插件**:任意开关机 shell 命令(经 ssh_host 决定本机/远端);method 未配置时默认即此。改 `method` 一行切换 |
| `[tftp]` | `method=remote` + `ssh_host`/`remote_dir` | scp 到远端 tftpd(gem12 的 tftpd-hpa) |
| | `method=local` + `local_dir` | 本机临时拉起 `tftp_server.py`(UDP 69 需特权,退出自动回收) |
| `[loady]` | `sender` | Ymodem 发送器(Arch 为 `lrzsz-sb`) |
| `[run.<名字>]` | `file` / `exec` / `method` / `timeout` | 一键启动目标(exec/method 即插件名;`run --repeat N` 多轮压测,每轮冷启动并汇总) |
| | `addr` / `entry` | 加载地址 / 跳转执行地址(`go 0x...` 的目标);缺省都取 `uboot.load_addr`,加载与入口不同时分别指定 |
| | `fdt` / `initrd` | booti 执行插件附加键:设备树地址(必需)/ initrd 地址(可选) |
| | `reset_before` | 开头冷启动:关→开→等提示符(从任意脏状态恢复) |
| | `after = off/reset/none` | 收尾动作 |
| | `expect = [..]` | 输出断言(子串,全命中才 PASS);`expect_re` 正则版;`fail_re` 正则禁止命中(如 panic);退出码 0/1 |

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
pip install boardctl            # 核心:run 全流程(loady/tftp 传输)
pip install 'boardctl[mijia]'   # + 小米云电源插件


# 发布(项目根目录)
uv build                        # 产出 dist/*.whl + *.tar.gz
uv publish --token <PyPI_API_Token>   # 建议先发 TestPyPI 演练
```

可选发布路径:GitHub 仓库 + Actions trusted publishing(打 tag 自动发布,免 token),
或直接 `pip install git+https://...`(零发布设施,适合私有/内网)。

