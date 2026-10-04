"""配置建模:msgspec.Struct 声明板卡 toml 的形状,加载即校验。

核心默认值从此只在此处声明一份;`boardctl check` 即用此形状校验配置。

- 严格与宽容分界:核心段([serial]/[console]/[uboot] 与 [run.*])开
  forbid_unknown_fields,拼错的键(如 expcet)当场报错;插件段与顶层
  宽容——键随插件演化,未来的段不设阻。
- 缺省即缺省:可缺省字段建模为 None,加载后剥除(config._strip_none)。
  默认值的取舍留在消费端——如 runner 的 after 缺省逻辑带条件,数据层
  不替它决定。
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


_PosFloat = Annotated[float, msgspec.Meta(ge=0)]


class RunTarget(msgspec.Struct, forbid_unknown_fields=True):
    """[run.<名>] 一个启动目标。

    method/mode 为宽松 str,不限枚举——传输与启动模式都是插件,
    名字集合随插件注册表开放。
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

    # 核心段:形状见上方各 Struct
    serial: SerialCfg = SerialCfg()
    console: ConsoleCfg = ConsoleCfg()
    uboot: UbootCfg = UbootCfg()

    # 插件段:宽容透传,默认值由各插件 DEFAULTS 在加载末段合并
    power: dict = msgspec.field(default_factory=dict)
    tftp: dict = msgspec.field(default_factory=dict)
    loady: dict = msgspec.field(default_factory=dict)

    run: dict[str, RunTarget] = msgspec.field(default_factory=dict)
