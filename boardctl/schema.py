"""配置建模:msgspec Struct 声明板卡 toml 的形状——加载即校验(类型/
枚举/拼错的键),核心默认值从此只在此处声明一份。建模三原则:

- 严格与宽容分界:[serial]/[console]/[uboot] 与 [run.*] 目标严格
  (forbid_unknown_fields:拼错的键当场报错,如 expcet);插件段
  (power/tftp/loady)宽容(键随插件演化,默认值归插件 DEFAULTS,
  渐进迁入);顶层宽容(未来的插件段不设阻)
- "缺省即缺省":可缺省字段建模为 None,加载后剥除——默认值的取舍
  留在消费端(runner 的 after 缺省逻辑带条件,不在数据层替它决定)
- 旧式写法在建模前归一(config._normalize):[uboot].prompt 继承进
  [console],断言键标量包列表;exec="watch" 由 runner._resolve_mode
  运行时转译,这里只收留其类型
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
    prompt: str | None = None     # 旧式:提示符现归 [console],加载时自动继承


_PosFloat = Annotated[float, msgspec.Meta(ge=0)]


class RunTarget(msgspec.Struct, forbid_unknown_fields=True):
    """[run.<名>] 一个启动目标;method/mode 宽容(str 不限枚举)——
    传输与启动模式都是插件,名字集合随插件注册表开放"""
    desc: str | None = None
    file: str | None = None
    method: str | None = None     # 传输插件名(tftp/loady/...)
    mode: str | None = None       # 启动模式插件名(uboot 缺省/console/watch)
    exec: str | None = None       # 旧式,仅剩合法值 "watch"(被动观察)
    cmd: str | None = None
    addr: str | None = None       # 加载地址,缺省 uboot.load_addr
    entry: str | None = None      # 跳转地址,缺省 addr(cmd 模板变量)
    initrd: str | None = None     # cmd 模板变量
    fdt: str | None = None        # cmd 模板变量
    reset_before: bool | None = None
    reset_after: bool | None = None      # 旧式:after 的前身
    after: Literal['off', 'reset', 'none'] | None = None
    timeout: _PosFloat | None = None
    fail_linger: _PosFloat | None = None
    interactive: bool | None = None
    expect: list[str] = msgspec.field(default_factory=list)      # 正向断言子串
    expect_re: list[str] = msgspec.field(default_factory=list)   # 正向断言正则
    fail_re: list[str] = msgspec.field(default_factory=list)     # 负向断言正则


class BoardCfg(msgspec.Struct):
    """一块板的全部配置;name 由加载器注入(非 toml 内容)"""
    name: str
    description: str = ''
    ssh_host: str = ''
    serial: SerialCfg = SerialCfg()
    console: ConsoleCfg = ConsoleCfg()
    uboot: UbootCfg = UbootCfg()
    # 插件段:宽容透传,默认值由各插件 DEFAULTS 在加载末段合并
    power: dict = msgspec.field(default_factory=dict)
    tftp: dict = msgspec.field(default_factory=dict)
    loady: dict = msgspec.field(default_factory=dict)
    run: dict[str, RunTarget] = msgspec.field(default_factory=dict)
