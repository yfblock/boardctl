"""boardctl — dev-board control toolkit (design inspired by ostool on crates.io)

Four-domain split (loosely coupled, one-way dependencies: wiring →
orchestration → board domain → {power, serial, capture, console, command
domain}):
  serial.py    serial domain: pure byte channel, fd lending (depends on no
               other module)
  stream.py    resident-capture domain: a reader thread continuously lands
               channel bytes in a capture log, waiting = watermark +
               predicate + condition-variable wakeup; the display (tap)
               hangs on capture events, shown as captured; fd lending
               yields via park/resume (depends on serial)
  console.py   console domain: prompt sessions for the board's interactive
               payload (U-Boot/Linux shell/other CLIs) — waiting for the
               prompt/executing commands all unfold on the capture stream's
               watermarks (depends on stream)
  power.py     power domain: the Power facade wraps PowerDevice plugins,
               pure power actions never touch the serial, holds only the
               cadence value reset_delay (cadence orchestration is in the
               board domain) (depends on plugins)
  shell.py     command domain: local/ssh command execution (depends on config)
  board.py     dev-board domain: Board composes SerialChannel + ConsoleStream
               + Power + Console (mirroring the config's
               [serial]/[power]/[console] sections), cold boot/quiet
               power-on/session factory; display (tap) lifecycle: attach
               before power-on, detach before power-off, programmatic calls
               can swap the sink; context manager starts/stops the capture
               thread (depends on power, serial, stream, console)
  config.py    board TOML loading → BoardCfg model object (depends on schema)
  schema.py    config modeling: single source of every section's shape and
               defaults, validated on load
  runner.py    run orchestration domain: Runner, one board ↔ many runners
               (depends on board + plugins)
  cli.py       CLI entry, wiring only (cyclopts annotation-driven)
  mcp_server.py MCP server (depends on runner)
  plugins/     plugins, three families: transport, power, mode (boot mode,
               selected via [run.*].mode) — plugins are classes,
               auto-discovered by directory convention (see
               plugins/__init__.py; executed commands are [run.*].cmd
               config templates, not plugins)
"""

# Single source of the version: pyproject references it dynamically via
# hatch; the CLI's --version reads it directly (source trees also show the
# true version, no install metadata needed)
__version__ = '0.14.0'
