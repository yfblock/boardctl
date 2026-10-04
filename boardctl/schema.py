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
    prompt: str = '=>'    # 控制台提示符(U-Boot/Linux shell/其他 CLI 皆可)


class UbootCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    load_addr: str = '0x80080000'
    ip_addr: str = ''
    server_ip: str = ''
    ensure_server_ip: bool = False


class MijiaCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    """[power.mijia] 米家插座参数(method = "mijia" 时生效)"""

    did: str | None = None       # 设备 id(与 dev_name 二选一)
    dev_name: str | None = None
    prop: str = 'on'             # 开关量属性名:多数插座 on,其余按设备属性表配


class PowerCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    """[power] 电源:两种方式的键共存一份(method 选插件,未用到的键无害)"""

    method: str = 'command'        # command(缺省)| mijia(需 pip install 'boardctl[mijia]')
    reset_delay: float = 3.0       # 断电→上电间隔秒(节拍编排住板域)
    on_cmd: str | None = None      # command 方式的开/关/查命令
    off_cmd: str | None = None
    status_cmd: str | None = None
    mijia: MijiaCfg = MijiaCfg()   # mijia 方式的参数


class TftpCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    """[tftp] tftp 传输:文件就位方式由 method 显式声明"""

    method: str = 'remote'         # remote: scp 到远端 tftp 服务器
                                   # external: 本机已有常驻 tftpd,只落文件免特权
    ssh_host: str = ''             # method=remote 时的 ssh 别名(~/.ssh/config)
    remote_dir: str = ''
    local_dir: str = 'tftpboot'    # method=external 时的 tftp 根目录


class LoadyCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    """[loady] loady(Ymodem)传输"""

    sender: str = ''               # Ymodem 发送器;空则自动查找(Arch: lrzsz-sb,Debian: sb)


_PosFloat = Annotated[float, msgspec.Meta(ge=0)]


class RunTarget(msgspec.Struct, forbid_unknown_fields=True):
    """[run.<名>] 一个启动目标。

    method/mode 为宽松 str,不限枚举——传输与启动模式都是插件,
    名字集合随插件注册表开放(注册表在运行期给"未知名字"报错,
    报错文案比 schema 校验更友好)。
    """

    # 是什么:描述、文件、传输与启动方式
    desc: str | None = None
    file: str | None = None
    method: str | None = None       # 传输插件名(tftp/loady/...)
    mode: str | None = None         # 启动模式(uboot 缺省/console/watch)

    # 怎么执行:cmd 模板及其变量
    cmd: str | None = None
    addr: str | None = None         # 加载地址,缺省 uboot.load_addr
    entry: str | None = None        # 跳转地址,缺省 addr
    initrd: str | None = None       # 初始 ramdisk
    fdt: str | None = None          # 设备树

    # 执行控制
    reset_before: bool | None = None
    after: Literal['off', 'reset', 'none'] | None = None
    timeout: _PosFloat | None = None
    fail_linger: _PosFloat | None = None
    interactive: bool | None = None

    # 断言:正向子串、正向正则、负向正则
    expect: list[str] = msgspec.field(default_factory=list)
    expect_re: list[str] = msgspec.field(default_factory=list)
    fail_re: list[str] = msgspec.field(default_factory=list)


class BoardCfg(msgspec.Struct):
    """一块板的全部配置;name 由加载器注入(非 toml 内容)。"""

    name: str
    description: str = ''
    ssh_host: str = ''

    # 各段:形状与默认值统一在此声明(单一来源;插件按属性自取所需段)
    serial: SerialCfg = SerialCfg()
    console: ConsoleCfg = ConsoleCfg()
    uboot: UbootCfg = UbootCfg()
    power: PowerCfg = PowerCfg()
    tftp: TftpCfg = TftpCfg()
    loady: LoadyCfg = LoadyCfg()

    # 启动目标:键是用户起的目标名,天然 dict;值形状见 RunTarget
    run: dict[str, RunTarget] = msgspec.field(default_factory=dict)
