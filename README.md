# boardctl

Dev-board control tool (design inspired by [ostool](https://crates.io/crates/ostool)): one TOML
config per board, a **modular + plugin** architecture — one-shot full flow
(cold boot → transport → execute → assert → finish); adding a
transport/execution/power method is just dropping a file into a plugin
directory.

- `run <target>`: automatic power-on → TFTP/Ymodem transport → `cmd`
  template execution (`go {addr}`, `booti …`) → output assertions
  (PASS/FAIL) → automatic power-off; `--repeat N` for multi-round stress runs
- Serial output is **shown as captured from power-on** (resident capture +
  display hooked on capture events): boot logs, command echo, transport and
  execution output all visible, no window gaps
- `power on|off|status`: manual power control/query (via power plugins, for
  use outside the run full flow)
- Passive watching `mode = "watch"`: when the board runs its own automatic
  flow (bootcmd/on-board scripts), zero writes the whole way — no transport,
  no commands sent (not even Ctrl-C, which would interrupt); after a quiet
  power-on, capture starts from the first byte, assertions and finish as usual
- Interrupt guarantee: on Ctrl-C / kill, if the board is powered on it is
  powered off automatically — after the program ends the device is always off
- Board configs live in `~/.config/boardctl/`, fully decoupled from the code

## Install

```bash
pip install boardctl             # core: run full flow (tftp + loady transport, command power)
pip install 'boardctl[mijia]'    # + Mijia smart socket power plugin (native Xiaomi cloud)
```

## Quick start

```bash
# 1. Create a board config (template: the bundled example, or boardctl/boards/example.toml in the repo)
mkdir -p ~/.config/boardctl
cp <template> ~/.config/boardctl/myboard.toml   # adapt serial address/power commands/boot targets

# 2. Run it
boardctl ls                        # list configured boards
boardctl -b myboard run            # list this board's boot targets
boardctl -b myboard run hello      # full flow: power-on → transport → execute → assert → power-off
boardctl -b myboard run hello -r 10   # 10 stress rounds, summary N/10 PASS
boardctl -b myboard power status   # query power (on/off)
boardctl -b myboard power off      # manual power-off (on likewise)
boardctl check                     # validate board config format (all boards when the name is omitted)
# -b can be omitted when there's exactly one board
```

## Board config (~/.config/boardctl/*.toml)

Search order: `$BOARDCTL_BOARDS` (temporary override) → `~/.config/boardctl/`
→ the bundled example (template fallback only); local/project folders don't
take part in resolution.

| Section | Keys | Description |
|---|---|---|
| Top level | `ssh_host` | where command-mode commands run: empty = local; an ssh alias (e.g. `myserver`) = remote via ssh, alias/port/user come from `~/.ssh/config` |
| `[serial]` | `url` / `timeout` | serial URL (TCP bridge `socket://host:port`, local `ttyUSB0`, `rfc2217://...`) |
| `[console]` | `prompt` | console prompt (the basis for command-end detection) — configure whatever runs on the board: U-Boot `=>`, Linux shell `#`… anything works |
| `[uboot]` | `load_addr` | U-Boot default load address |
| | `server_ip` / `ensure_server_ip` | TFTP server address; set true when the target's U-Boot environment is volatile (no saveenv): restored automatically on connect |
| `[power]` | `method = "mijia"` + `[power.mijia]` dev_name/did | power plugin: native Xiaomi cloud (credentials reuse the `mijiaAPI` CLI login state; `mijiaAPI login` QR scan needed once), doesn't go through ssh_host |
| | `[power.mijia]` prop | on/off property name, default `"on"`; some devices' power prop isn't `on` — change per the device's property table |
| | `method = "command"` + `on_cmd`/`off_cmd`/`status_cmd` | command plugin: arbitrary power on/off shell commands (local or remote per ssh_host); the default when method isn't configured |
| `[tftp]` | `method=remote` + `ssh_host`/`remote_dir` | scp to a remote tftpd server |
| | `method=external` + `local_dir` | **a resident tftpd (e.g. tftpd-hpa) already serves UDP 69 on this host**: just drop the file into its root dir — no port probing, no server setup, no privileges |
| `[loady]` | `sender` | Ymodem sender (empty = autodetect: `lrzsz-sb` on Arch, `sb` on Debian/Ubuntu) |
| `[run.<name>]` | `mode` / `file` / `cmd` / `method` / `timeout` | boot target (mode is the mode-plugin name): `uboot` (default: transport the file + execute cmd, `{addr}`/`{entry}` default to `uboot.load_addr`), `console` (no transport, execute `cmd` directly once at the prompt, no address semantics), `watch` (passive: zero writes, the board runs itself) |
| | `cmd` | U-Boot command template: `go {addr}`, `source {addr}`, `booti {addr} - {fdt}`; variables come from this target's own keys (`{addr}`/`{entry}` default to `uboot.load_addr`), a missing variable errors by name; omitted = load only; for command sequences write a .scr and `source` it |
| | `addr` / `entry` | load address / jump-execution address; both default to `uboot.load_addr`, specify separately when load and entry differ |
| | `fdt` / `initrd` | extra keys for the booti executor: device-tree address (required) / initrd address (optional) |
| | `reset_before` | automatic power-on at the start: off→on→wait for prompt (no dependence on the device's initial state) |
| | `after = off/reset/none` | finish action (power down / reboot to prompt / keep state) |
| | `expect` / `expect_re` / `fail_re` | output assertions: substrings / regexes that must hit / regexes that must not; all must hit for PASS, exit code 0/1. **A fail_re hit is an instant streaming negative verdict** (regexes are case-sensitive; Linux `Kernel panic` and Rust `panicked` need separate coverage or `(?i)`) |
| | `fail_linger` | seconds to keep collecting output after a fail_re hit (default 2) — lets error messages/stacks finish before wrap-up and power-off; 0 = immediate |

## Architecture (loosely coupled, one-way dependencies)

```
boardctl/
├── cli.py        CLI wiring (cyclopts annotation-driven, no business logic)
├── schema.py     config modeling (msgspec.Struct): single source of every
│                 section's shape and defaults, validated on load;
│                 config circulates as a BoardCfg model object
├── config.py     board TOML loading → BoardCfg model ← schema
├── serial.py     serial domain: pure byte channel + fd lending (depends on nothing else)
├── stream.py     resident-capture domain: a reader thread continuously captures
│                 bytes into a log, waiting = watermark + predicate + condition variable;
│                 the display tap hooks capture events, shown as captured ← serial
├── console.py    console domain: prompt-driven interactive sessions, U-Boot/Linux
│                 shell/any other CLI ← stream
├── power.py      power domain: the Power facade wraps PowerDevice plugins, pure
│                 on/off/status, never touches the serial ← plugins
├── board.py      board domain: Board composes serial + stream + power + console
│                 (mirrors the config sections; context manager starts/stops the
│                 capture thread; display tap attaches before power-on, detaches
│                 before power-off) ← power, serial, stream, console
├── shell.py      command domain: command execution (local/ssh) ← config
├── runner.py     run orchestration domain: Runner (one board ↔ many runners) ← board + plugins
└── plugins/      plugins are classes (auto-discovered by directory convention, zero registration code)
    ├── transport/   transport plugins: loady.py, tftp.py (Transport subclasses)
    ├── power/       power plugins: mijia.py (Xiaomi cloud), command.py (commands, default)
    └── mode/        boot-mode plugins: uboot.py, console.py, watch.py (RunMode
                     subclasses, selected via [run.*].mode; streaming/assertions/
                     finish are held uniformly by the runner)
```

**Plugins are classes** (base classes and conventions written in each
`plugins/<family>/__init__.py`; a plugin module provides `PLUGIN = <class>`,
the class declares `NAME`; config section shapes and defaults live uniformly
in `schema.py`, plugins take the sections they need via cfg attributes;
creating a plugin = drop in a file):

- transport plugin: `Transport` subclass, `send(stream, path, addr) -> bool`
  (stream is the board's lent resident capture stream; the plugin opens no
  connection of its own; `park()` before an fd lend, `resume()` after returning it)
- power plugin: `PowerDevice` subclass, `on()` / `off()` / `status() -> bool | None`

Creating a plugin = adding one file; `[run].method`/`[power].method` work
immediately, zero core changes; when it brings a new config section, just add
one field to `schema.BoardCfg` (a section not yet settled can first be
declared as dict) (the executed command is not a plugin: it's a `[run].cmd`
config template, expanded by the runner).

## MCP (let clients like Claude drive the board directly)

```bash
pip install 'boardctl[mcp]'
claude mcp add boardctl -- boardctl-mcp      # Claude Code; for Desktop, fill in the mcpServers JSON likewise
```

The model can then call three tools: `ls_boards` (list boards and targets),
`power_status` (query power), and `run_target` (full-flow test on real
hardware: automatic power on/off → transport → execute → assert, `repeat`
supports stress runs). The tools really control the hardware power, as noted
in their descriptions; mind client timeout settings for long tasks.

## Development

```bash
git clone https://github.com/yfblock/boardctl && cd boardctl
uv venv && uv pip install -e '.[mijia]'   # single source of dependencies: pyproject.toml
uv run python tests/test_software.py      # pure-software tests (no hardware needed)
```

Release: push a tag (`git tag vX.Y.Z && git push origin vX.Y.Z`) and GitHub
Actions builds and publishes to PyPI automatically (trusted publishing).

## Dependencies

Python 3.11+ (stdlib `tomllib`) + pyserial + cyclopts (CLI parsing,
transitively rich) + msgspec (config modeling). Cross-building bare-metal
test firmware additionally needs `riscv64-linux-gnu-gcc`, `mkimage`
(uboot-tools), `lrzsz`.

## License

MIT (see [LICENSE](LICENSE))
