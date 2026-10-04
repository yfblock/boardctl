"""Config modeling: msgspec.Struct declares the shape of a board toml,
validated on load.

All sections (core and plugins) are modeled here, defaults declared exactly
once; `boardctl check` validates configs against this shape. After loading,
the config circulates as a BoardCfg model object (no longer a dict).

- Strict vs lenient boundary: each section forbids unknown fields, so a
  misspelled key (e.g. expcet) errors on the spot; the top level stays
  lenient — future sections face no barrier (when a new plugin adds a
  section, add the field here; a section not yet settled can first be
  declared as dict).
- Absent means absent: optional fields are modeled as None, consumers
  None-check and take their own defaults (e.g. runner's after-default logic
  is conditional; the data layer doesn't decide for it); fields with a
  definite default (e.g. power.method) are declared here.
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
    """[power.mijia] Mijia socket parameters (effective when method = "mijia")"""

    did: str | None = None       # device id (either this or dev_name)
    dev_name: str | None = None
    prop: str = 'on'             # on/off property name: 'on' for most sockets, others per the device spec


class PowerCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    """[power] power: keys of both approaches coexist in one place (method picks the plugin; unused keys are harmless)"""

    method: str = 'command'        # command (default) | mijia (needs pip install 'boardctl[mijia]')
    reset_delay: float = 3.0       # seconds between power-off and power-on (cadence lives in the board domain)
    on_cmd: str | None = None      # on/off/status commands for the command method
    off_cmd: str | None = None
    status_cmd: str | None = None
    mijia: MijiaCfg = MijiaCfg()   # parameters for the mijia method


class TftpCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    """[tftp] tftp transport: how files get staged is declared explicitly via method"""

    method: str = 'remote'         # remote: scp to a remote tftp server
                                   # external: a resident tftpd already serves this host; just stage the file, no privileges
    ssh_host: str = ''             # ssh alias for method=remote (from ~/.ssh/config)
    remote_dir: str = ''
    local_dir: str = 'tftpboot'    # tftp root dir for method=external


class LoadyCfg(msgspec.Struct, forbid_unknown_fields=True, frozen=True):
    """[loady] loady (Ymodem) transport"""

    sender: str = ''               # Ymodem sender; empty = autodetect (Arch: lrzsz-sb, Debian: sb)


_PosFloat = Annotated[float, msgspec.Meta(ge=0)]


class RunTarget(msgspec.Struct, forbid_unknown_fields=True):
    """[run.<name>] one boot target.

    method/mode are loose strs, not enum-limited — transport and boot mode
    are both plugins, their name sets stay open with the plugin registry
    (the registry errors on "unknown name" at runtime, with friendlier
    messages than schema validation).
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
    """A board's full config; name is injected by the loader (not toml content)."""

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
