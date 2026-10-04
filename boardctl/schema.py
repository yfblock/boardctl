"""配置建模:msgspec.Struct 声明板卡 toml 的形状,加载即校验。

全部段(核心与插件)都在此建模,默认值只在此处声明一份;`boardctl check`
即用此形状校验配置。加载后配置即以 BoardCfg 模型对象流通(不再是 dict)。

- 严格与宽容分界:各段 forbid_unknown_fields,拼错的键(如 expcet)当场
  报错;顶层宽容——未来的段不设阻(新插件加段时在此加字段,暂不定形的
  段可先声明为 dict)。
- 缺省即缺省:可缺省字段建模为 None,消费端判 None 取自己的默认值
  (如 runner 的 after 缺省逻辑带条件,数据层不替它决定);有明确缺省值
  的字段(如 power.method)在此声明。
"""
from typing import Annotated, Literal

import msgspec


class SerialCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    url: str = 'socket://localhost:5000'
    timeout: float = 0.2


class ConsoleCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    prompt: str = '=>'    # console prompt (U-Boot/Linux shell/any other CLI)


class UbootCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    load_addr: str = '0x80080000'
    ip_addr: str = ''
    server_ip: str = ''
    ensure_server_ip: bool = False


class MijiaCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    """[power.mijia] 米家插座参数(method = "mijia" 时生效)"""

    did: str | None = None       # device id (either this or dev_name)
    dev_name: str | None = None
    prop: str = 'on'             # on/off property name: 'on' for most sockets, others per the device spec


class PowerCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    """[power] 电源:两种方式的键共存一份(method 选插件,未用到的键无害)"""

    method: str = 'command'        # command (default) | mijia (needs pip install 'boardctl[mijia]')
    reset_delay: float = 3.0       # seconds between power-off and power-on (cadence lives in the board domain)
    on_cmd: str | None = None      # on/off/status commands for the command method
    off_cmd: str | None = None
    status_cmd: str | None = None
    mijia: MijiaCfg = MijiaCfg()   # parameters for the mijia method


class TftpCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    """[tftp] tftp 传输:文件就位方式由 method 显式声明"""

    method: str = 'remote'         # remote: scp to a remote tftp server
                                   # external: a resident tftpd already serves this host; just stage the file, no privileges
    ssh_host: str = ''             # ssh alias for method=remote (from ~/.ssh/config)
    remote_dir: str = ''
    local_dir: str = 'tftpboot'    # tftp root dir for method=external


class LoadyCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    """[loady] loady(Ymodem)传输"""

    sender: str = ''               # Ymodem sender; empty = autodetect (Arch: lrzsz-sb, Debian: sb)


_PosFloat = Annotated[float, msgspec.Meta(ge=0)]


class RunTarget(msgspec.Struct, forbid_unknown_fields=True):
    """[run.<名>] 一个启动目标。

    method/mode 为宽松 str,不限枚举——传输与启动模式都是插件,
    名字集合随插件注册表开放(注册表在运行期给"未知名字"报错,
    报错文案比 schema 校验更友好)。
    """

    # what it is: description, file, transport and boot mode
    desc: str | None = None
    file: str | None = None
    method: str | None = None       # transport plugin name (tftp/loady/...)
    mode: str | None = None         # boot mode (uboot default/console/watch)

    # how to execute: cmd template and its variables
    cmd: str | None = None
    addr: str | None = None         # load address, defaults to uboot.load_addr
    entry: str | None = None        # entry address, defaults to addr
    initrd: str | None = None       # initial ramdisk
    fdt: str | None = None          # device tree

    # execution control
    reset_before: bool | None = None
    after: Literal['off', 'reset', 'none'] | None = None
    timeout: _PosFloat | None = None
    fail_linger: _PosFloat | None = None
    interactive: bool | None = None

    # assertions: positive substrings, positive regexes, negative regexes
    expect: list[str] = msgspec.field(default_factory=list)
    expect_re: list[str] = msgspec.field(default_factory=list)
    fail_re: list[str] = msgspec.field(default_factory=list)


class BoardCfg(msgspec.Struct):
    """一块板的全部配置;name 由加载器注入(非 toml 内容)。"""

    name: str
    description: str = ''
    ssh_host: str = ''

    # sections: shapes and defaults declared here once (single source; plugins take what they need by attribute)
    serial: SerialCfg = SerialCfg()
    console: ConsoleCfg = ConsoleCfg()
    uboot: UbootCfg = UbootCfg()
    power: PowerCfg = PowerCfg()
    tftp: TftpCfg = TftpCfg()
    loady: LoadyCfg = LoadyCfg()

    # run targets: keys are user-chosen names, naturally a dict; value shape in RunTarget
    run: dict[str, RunTarget] = msgspec.field(default_factory=dict)
