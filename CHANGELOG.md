# Changelog

## Unreleased

- Internal: comment/docstring density pass across boardctl/ and tests/ —
  narration and code-restating comments removed, multi-sentence explanations
  compressed to one-liners; contracts and invariants (watermark semantics,
  tap lifecycle, park/resume, ordering discipline) kept. Code verified
  AST-identical before/after (sole functional-adjacent delta: dropped a
  redundant `import termios` in runner's interactive-mode finally)
- **Breaking: `run --repeat/-r` removed (tool minimalism)** — multi-round
  stress runs are a shell loop over the one-shot flow
  (`for i in $(seq N); do boardctl -b b run t; done`), exit code per round
  as usual. With the feature retired: do_run/run_collect lost their loops,
  round headers and summaries; run_collect returns a flat single-run
  result; the MCP run_target tool lost its repeat parameter (clients call
  it repeatedly for stress runs); the repeat>1 auto-enable of reset_before
  is gone with it

## 0.14.0 - 2026-10-04

- **Config modeling with msgspec: validated on load (new dependency msgspec)** —
  schema.py declares the board toml's shape with Structs; the loading
  pipeline = toml parse → model validation → strip absent → plugin default
  merge. Misspelled keys (e.g. expcet), type errors (timeout = "abc"),
  illegal enums (after = "reboot"), negative timeouts, unknown keys in core
  sections **error on the spot with field paths**; core sections
  ([serial]/[console]/[uboot]/[run.*]) are strict (unknown keys rejected),
  plugin sections (power/tftp/loady) lenient; core defaults are from now on
  declared exactly once in schema.py. Also fixed the silent loss where the
  user's `[loady]` section never reached the config (long masked by the
  sender autodetect fallback)
- **Legacy config formats removed (breaking: error on load with field paths)** —
  the compat layer retired, one format only; migrate old configs per the
  table below (`boardctl check` verifies afterwards):
  | Old form | Migrate to |
  |---|---|
  | `prompt = "..."` in the `[uboot]` section | `prompt = "..."` in the `[console]` section |
  | `expect = "marker"` (scalar) | `expect = ["marker"]` (list) |
  | `exec = "watch"` | `mode = "watch"` |
  | `reset_after = true` | `after = "reset"` |
- **New `boardctl check [board]` subcommand**: validates config format per
  board against the schema, reports OK/error per board, exit code 1 when any
  config is invalid; omitting the board validates all, no hardware touched
- **`-h` help prints directly**: no more less full-screen paging (fire's
  default on a tty); sequential output, scrollable and pipeable
- Internal: available_boards converged to a pathlib glob; runner assertion
  lookups no longer defend against scalars everywhere (types are guaranteed
  by the schema); check's unknown-board detection converged back into
  load_board as the single point; comments restructured into paragraphs
  (summary line + blank line + bullet list)

## 0.13.0 - 2026-10-04

- **Serial output shown as captured from power-on (event-driven display)**:
  new stream domain — a resident capture thread continuously reads the
  serial into a log, the display (tap) hooks capture events and shows as
  read; the whole chain left polling behind. Cold boot/transport/execution
  visible throughout: SPL bytes, the U-Boot banner, command echo shown
  verbatim — waiting is no longer a black box
  - status lines (powering off.../powering on.../waiting for console
    prompt...) land on screen first, then the display attaches, then
    power-on — not torn apart by boot bytes, nor later than any write to
    the serial; line noise in the power-off window stays off screen
    (backlog flushed before detaching, the display tail isn't lost)
  - programmatic calls (run_collect/MCP) can swap the display sink for a
    buffer — device bytes never land on the service process's stdout
- **Transport success stays silent**: tftp/loady no longer print an
  "OK: N bytes" summary line on success — the echo (shown as captured)
  already has tftpboot / Bytes transferred / Total Size, a repeat carries no
  information; only locally-known facts (size mismatch) or failure verdicts
  get printed
- **`[run.*].mode` boot-mode plugin family (new config key, default uboot)**:
  mode = uboot / console / watch distinguishes target shapes; the authority
  to interpret "how this target gets brought up" (power-on style/transport
  or not/command shape) belongs to the plugin; streaming/assertions/finish/
  repeat are held uniformly by the runner, verdict semantics identical for
  every mode. The old form exec = "watch" equals mode = "watch"; existing
  configs need zero changes
- **Domain consolidation completed (purely internal, zero config impact)**:
  console domain landed — Board no longer assumes U-Boot, the console
  payload comes from `[console].prompt`; power/orchestration also
  consolidated into the Power / Runner classes; Board composes the four
  domains serial / stream / power / console, the display (tap) lifecycle
  belongs to the board; loady's fd lending yields via park/resume, protocol
  bytes during the lend belong to the sender and pick up seamlessly after
  resume

## 0.12.0 - 2026-10-03

- **Four-domain split (purely internal refactor, zero config impact)**:
  core re-split along serial/board/power/command domains, one-way
  dependencies: `board → {power, session/serial, shell}` —
  - new `serial.py` (serial domain): `SerialChannel` pure byte channel,
    collecting the low-level serial details once scattered across
    UbootSession (open/read/write) and the loady plugin (fd lending +
    O_NONBLOCK cleanup); `blocking_fd()` lends the fd cleanly to the Ymodem
    sender
  - new `board.py` (board domain): `Board.cold_boot()` / `quiet_boot()` /
    session factory — power-on flow moved in from power.py (the power domain
    no longer carries serial knowledge), cold-boot and quiet-power-on
    semantics unchanged
  - `power.py` narrowed to pure power actions (on/off/status + power/reset
    subcommands), never touches the serial; `session.py` becomes the U-Boot
    protocol layer, byte data via SerialChannel
  - `shell.py` (command domain) untouched
- **Plugins are classes**: the transport/power plugin families went from
  "module functions" to classes — base classes `Transport` / `PowerDevice`
  (abstract on/off/status or send) live in each plugin package's
  `__init__.py`; a plugin module provides `PLUGIN = <class>`, the class
  declares `NAME` and optional `CFG_SECTION`/`DEFAULTS` (the config
  default-merge convention unchanged). Encapsulation = each plugin's details
  hide inside its class; polymorphism = different subclasses, one
  interface. New power plugin example: implementing the three methods
  `on()/off()/status()` is enough to be selectable via `[power].method`

## 0.11.0 - 2026-10-03

- **tftp `method = "local"` removed (breaking)**: boardctl no longer
  self-hosts a temporary TFTP server (the built-in `tftp_server.py` deleted
  with the package) — file staging keeps exactly two explicit ways:
  `remote` (scp to a remote tftpd) and `external` (resident tftpd on this
  host, just stage the file); without tftpd use `loady` (Ymodem over
  serial, no privileges, no server). Leftover `local` configs get migration
  guidance instead of an obscure error
- **Executor plugin family retired, `exec` → `cmd` template (breaking)**:
  executed commands return to being config data —
  `[run.<name>] cmd = "go {addr}"`. Variables come from the target's own
  config keys (`{addr}`/`{entry}` default to `uboot.load_addr`); a missing
  variable errors by name; omitting `cmd` = load only (the old exec=none);
  command sequences still go in a .scr executed via `source {addr}`.
  `exec = "watch"` is kept (passive mode is a behavior, not a command).
  Migration mapping: `go`→`cmd = "go {entry}"`,
  `source`→`cmd = "source {entry}"`, `booti`→`cmd = "booti {entry} - {fdt}"`
  (with initrd use `{initrd}`), `bootm`→`cmd = "bootm {entry} {initrd} {fdt}"`,
  `none`→delete the exec line

## 0.10.0 - 2026-10-03

- **CLI engine cyclopts → google-fire**: the Boardctl class is the command
  surface (methods are subcommands); the command surface and usage are
  completely unchanged (`-b board` still before the subcommand,
  `run <target> -r N`, `power on|off|status`, `ls`, single-board
  auto-selection without `-b`); `sys.exit` exit codes propagate as-is
  (0/1/130 semantics unchanged). Dependency cyclopts → fire (transitive
  dependency termcolor). Differences: fire doesn't validate parameters, so
  power state and repeat got manual validation in this tool; all-digit
  board names get literalized to int by fire, restored with a fallback;
  help-page format changed
- Fixed two brittle CI test assertions (a cyclopts version-dependent exit-code
  assertion, and a mis-assertion of `$BOARDCTL_BOARDS` directory replacement
  semantics — it's actually first-in-priority)

## 0.9.0 - 2026-10-01

- **Board config directory lost its `boards/` subdirectory (breaking)**:
  board TOMLs go directly into `~/.config/boardctl/` (i.e. board_dir
  itself), no `boards/` subfolder needed anymore; the `$BOARDCTL_BOARDS`
  environment variable semantics unchanged (drop `*.toml` directly into the
  directory it points to). Upgrading from an old version:
  `mv ~/.config/boardctl/boards/*.toml ~/.config/boardctl/`

## 0.8.0 - 2026-10-01

- **`power` subcommand**: `boardctl [-b board] power on|off|status` —
  control/query power directly via power plugins (manual operation outside
  the run full flow); status prints on/off for parseable plugins (mijia),
  passes through for unparseable ones (command)
- **mijia plugin property name configurable**: some devices' on/off prop
  isn't `'on'`; new `[power.mijia] prop = "..."` (default still `'on'`,
  existing configs unaffected)
- **CLI migrated to cyclopts** (hand-written argparse dropped):
  annotation-driven declaration of commands and parameters; command surface
  and usage completely unchanged (`-b board` still before the subcommand,
  `run <target> -r N`, `power on|off|status`, `ls`); the global `-b` is
  parsed through the meta entry, board config loaded once and injected into
  subcommands; new `--version`; friendlier error messages for illegal
  parameters

## 0.7.0 - 2026-10-01

- **Passive watch mode `exec = "watch"`**: when the board does its own
  transport and execution (U-Boot bootcmd, on-board automatic scripts),
  boardctl writes nothing the whole way — no `loady`/`tftpboot`/`go` typed,
  not even the cold boot's prompt-waiting Ctrl-C (it would interrupt the
  board's automatic flow); it only does: quiet power-on (serial attached
  first, power-off line noise cleared, capture from the first boot byte) →
  passive capture → assertions (expect/fail_re/fail_linger as usual) →
  after finish; such targets neither need nor allow `file` (the board
  fetches by itself)
- The executor plugin interface gained the optional declaration
  `PASSIVE = True` (watch is its first user); an active mode missing `file`
  now errors clearly instead of a bare KeyError

## 0.6.3 - 2026-09-29

- **Delayed wrap-up after a fail_re hit**: new `[run].fail_linger`
  (seconds, default 2) — after a fail_re hit, don't cut power immediately;
  keep collecting output so error messages/stacks finish, then verdict FAIL
  and run the finish; set 0 to restore immediate wrap-up. Within the linger
  window only output is collected, no other end-condition judging

## 0.6.2 - 2026-09-29

- **fail_re instant streaming negative verdict**: the moment `fail_re`
  hits during execution, wrap up (end reason `fail`), verdict FAIL and run
  the after finish — panic-class faults stop the loss immediately instead
  of waiting out the timeout (previously fail_re was only judged uniformly
  by assertions after the stream ended; during streaming, positive
  assertions could wrap up early but negative ones couldn't); when positive
  and negative assertions hit in the same batch of output, the negative
  verdict wins

## 0.6.1 - 2026-09-29

- **tftp `method` split: explicit declaration, no more guessing** (`local`
  previously packed two semantics into one method and guessed intent by
  port probing — the root of the non-root false-positive problem)
  - new `method = "external"`: when a resident tftpd (e.g. tftpd-hpa)
    already serves UDP 69 on this host, just drop the file into its root
    dir — **no port probing, no server setup, no privileges**; a file
    already in `local_dir` isn't re-staged (fixes the self-copy
    `SameFileError`)
  - `method = "local"` narrowed to "boardctl self-hosts a temporary TFTP
    server": probing only for fast failure with alternatives — 69 occupied
    suggests `external`, free but unprivileged suggests
    `sudo`/`external`/`loady` (occupancy detection reads `/proc/net/udp`:
    a non-root attempt to bind a privileged port always gets EACCES, the
    kernel checks permissions before occupancy, the old probing couldn't
    tell them apart)
- **run finish backstop**: `after` moved into `finally` — every exit path
  (transport failure, plugin `sys.exit`, `exec=none` early return, ...)
  runs the finish (with `after=off` even a failure powers down; fixes
  "transport error after cold boot leaves the board powered on"); a finish
  failure of its own is only reported, never masking the original error

## 0.6.0 - 2026-09-15

- **Streaming execution**: run's execution phase switched to real-time
  streaming output (instead of waiting out the whole timeout before
  printing)
  - all positive assertions (expect/expect_re) hit → early wrap-up:
    infinite-loop targets (e.g. bare-metal go) go from "wait out timeout"
    to "wrap up once the markers are out"
  - prompt reappears → wrap up (executors like source that return to the
    prompt)
- **Interactive mode** `[run].interactive = true` (TTY): output streams
  live + stdin forwarded verbatim into the device — after `go`/`booti`
  enters the kernel you can type directly in the run session; `Ctrl-\` to
  quit (non-TTY/MCP automatically degrades to streaming + time limit,
  behavior compatible)
- run_collect round results gained an `ended` field
  (prompt/matched/timeout/user/loaded)

## 0.5.0 - 2026-09-15

- **MCP server**: after `pip install 'boardctl[mcp]'`,
  `claude mcp add boardctl -- boardctl-mcp` lets clients like Claude drive
  the board directly
  - tools: `ls_boards` (list boards and targets) / `power_status` (query
    power) / `run_target` (full-flow test on real hardware, repeat supports
    stress runs; really controls the hardware power)
  - compatible with mcp 1.x (FastMCP) and 2.x (MCPServer)
  - new `runner.run_collect()`: programmatic API, captures output and
    returns a structured result (the CLI's live printing unchanged);
    tests/test_mcp.py protocol-level smoke joined CI

## 0.4.4 - 2026-09-15

- Leak fix: CHANGELOG entries no longer mention concrete intranet
  addresses; the hardware-acceptance directory (containing
  specific-hardware-environment info) moved out of the repo and release
  artifacts entirely — the repo working tree has contained no
  intranet/personal-environment information since

## 0.4.3 - 2026-09-15

- Fixed 0.4.2's release blemish: the v0.4.2 tag mistakenly pointed at a
  pre-cleanup commit; three comments in the wheel retained intranet
  environment info (code comments only, no functional impact); this version
  is clean

## 0.4.2 - 2026-09-15

- Bundled board example de-personalized: `sg2002.toml` (with intranet
  addresses and personal environment) replaced by the generic template
  `example.toml` (IPs all use RFC 5737 documentation ranges)
- `-b` no longer defaults to `sg2002`: when unspecified and exactly one
  user board exists it's auto-selected; multiple boards prompt for a choice
- README rewritten for public release (intranet environment info and
  maintainer release notes removed)

## 0.4.1 - 2026-09-15

- Example board config: the `run script` target gained `reset_before` +
  `after = "off"` (automatic power on/off; previously it assumed the board
  was already at the prompt — a powered-off device would time out and fail)

## 0.4.0 - 2026-09-15

**Breaking change**: the `boards` subcommand renamed to `ls`.

- **Interrupt power-off guarantee**: if `run` is interrupted by Ctrl-C /
  SIGTERM or hits an uncaught exception while the board is powered on, a
  power-off runs automatically — guaranteeing the device is off after the
  program ends; the finish of a normal completion is still decided by
  `[run].after` (off/reset/none)

## 0.3.1 - 2026-09-15

- Board config resolution narrowed: **only `~/.config/boardctl/boards/` is
  recognized** (`$BOARDCTL_BOARDS` can temporarily override; the bundled
  example demoted to the lowest-priority template). Local/project folders
  no longer take part in resolution; the repo-root boards/ directory
  removed, the example moved into the package (boardctl/boards/), packaging
  no longer needs force-include

## 0.3.0 - 2026-09-15

**Breaking change**: CLI command surface radically simplified.

- Only `run` (one-shot full flow: cold boot → transport → execute → assert
  → finish, `--repeat N` stress) and `boards` (list boards) kept
- Removed subcommands: `console`, `power`, `reset`, `cmd`, `send`, `exec`;
  the capabilities remain: power operations are covered by run's
  `reset_before`/`after` and power plugins, transport/execution plugins are
  driven by run's `method`/`exec`, all usable via the Python API
- the `console` interactive terminal module removed along with its
  subcommand (the `off_on_exit` config option deleted with it)
- boards/run.sh deleted: power on/off commands inlined directly into board
  configs (command power mode works installed)
- e2e/verify_e2e.py switched to the Python API (no longer depends on CLI
  subcommands)

## 0.2.0 - 2026-09-15

- New executor plugins: `booti` (boot a Linux raw kernel; fdt required /
  initrd optional for run targets), `bootm` (legacy uImage)
- `run --repeat N`: multi-round stress, cold boot each round (repeat>1
  auto-enables reset_before), ending with an `N/M rounds PASS` summary,
  exit code 1 if any round fails
- Assertion engine enhanced (`expect` keeps substring semantics; added):
  - `expect_re`: list of regexes, all must hit
  - `fail_re`: list of regexes, a hit means FAIL (e.g. `panic`,
    `Unknown command`)
- Executor plugin interface extended: `build_cmd(addr, t)`'s second
  parameter is the run target's config table (booti/bootm read fdt/initrd
  from it)
- Directory reorganization: boards/ (board configs + board assets),
  examples/, tests/ (pure software), e2e/ (hardware acceptance);
  requirements.txt and main.py deleted; new LICENSE (MIT), CHANGELOG, CI
  (push/PR auto compile + software tests + build check)

## 0.1.0 - 2026-09-15

Initial release: plugin-based dev-board control tool (design inspired by
[ostool](https://crates.io/crates/ostool)).

- Subcommands: `console` (interactive serial terminal) / `power` / `reset`
  / `cmd` / `send` / `run` / `exec` / `boards`
- Three plugin families, auto-discovered by directory convention:
  - transport: loady (Ymodem), tftp (remote scp / local built-in server)
  - executors: go, source, none
  - power: mijia (native Xiaomi cloud), command (custom power commands,
    default)
- One-shot launch `run`: cold boot → transport → execute → expect
  assertions (PASS/FAIL exit code) → finish (off/reset/none)
- Board configs `boards/*.toml`, search order `$BOARDCTL_BOARDS` →
  `./boards` → `~/.config/boardctl/boards` → bundled
- `ssh_host` field: command-mode commands can run on a remote host via ssh
- End-to-end acceptance `e2e/verify_e2e.py` (bare metal + U-Boot script on
  real hardware, byte-by-byte assertions)
