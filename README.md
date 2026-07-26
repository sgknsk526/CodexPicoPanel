# Codex Pico Panel

[日本語](README.ja.md)

Codex Pico Panel turns a Raspberry Pi Pico and a Pimoroni Pico RGB Keypad Base
into a 16-key control and status panel for Codex Desktop on Windows.

The Pico is not exposed as a keyboard. It sends the 16 physical key states to a
small Windows resident process over USB CDC. The Windows process performs only
fixed, whitelisted shortcuts and UI actions, observes Codex state, and sends
compact LED state changes back to the Pico.

> [!WARNING]
> This is an experimental, unofficial project and is not affiliated with
> OpenAI, Pimoroni, or Raspberry Pi. It depends on Codex Desktop logs, UI
> Automation, session JSONL, and an alpha app-server interface. Codex updates
> may break it. Keys C and D can approve or reject requests; review the code and
> your Codex approval settings before enabling them.

## Hardware and software

- Raspberry Pi Pico (RP2040)
- Pimoroni Pico RGB Keypad Base
- Data-capable Micro-USB cable
- Windows 10 or 11
- Python 3.11 or newer
- Windows OpenSSH client for remote tasks
- Codex Desktop

Tested with CircuitPython 10.2.1, Codex Desktop 26.715.10079, and the bundled
Codex app-server 0.145.0-alpha.30. These are compatibility observations, not
minimum-version guarantees.

## Architecture and protocol

```text
Pico key mask -> Windows resident -> fixed shortcut or Codex UI action
Codex hooks/logs/session/app-server -> Windows resident -> Pico LED state
```

- Windows to Pico: one-byte statecode `0xXY` (`LED X <- state Y`)
- Pico to Windows: two-byte little-endian 16-bit physical-key mask
- Initial connection: all 16 LED states are synchronized
- Normal operation: only changed key masks and LED states are transferred

USB HID and MIDI are disabled by `firmware/boot.py`. The Pico exposes a CDC
console and a separate CDC data port; the resident process opens the data port.

## Key map

| Key | Action | LED |
|---|---|---|
| 0 | Release within 2 seconds to launch or focus Codex | Blue while Codex is foreground |
| 1–7 | Release for `Ctrl+1`–`Ctrl+7`; hold 1 second to register/unregister the visible task | Task status |
| 8 | Hold `Ctrl+Shift+F` for push-to-talk | White when available, yellow while held |
| 9 | Hold 0.6 seconds to send or stop the running turn | Green when ready, blue while running |
| A | Hold 0.6 seconds to clear the composer | Orange when available |
| B | Open the local status page | Yellow while held |
| C | Hold 0.6 seconds to approve | Green when available |
| D | Hold 0.6 seconds to reject | Red when available |
| E | Send `Ctrl+Shift+W` to cycle reasoning effort | Current effort color |
| F | Send `Ctrl+Shift+X` to toggle Plan mode | White for default, purple for Plan |

Task LEDs for keys 1–7 are: off=unregistered, white=idle,
green=unread successful completion, blue=thinking, pink=action required, and
red=unread failed completion. Opening a registered task marks it as read.

Reasoning colors are: low=gray, medium=green, high=cyan, xhigh=blue,
max=orange, and ultra=red.

Configure Codex Desktop so that push-to-talk, reasoning effort, and Plan mode
use the chords shown above. Keys 9/A/C/D use Windows UI Automation rather than
custom shortcuts.

## Pico setup

1. Install CircuitPython for Raspberry Pi Pico.
2. Install Pimoroni's PMK library under `CIRCUITPY/lib/pmk`.
3. Copy `adafruit_dotstar.mpy` from the matching CircuitPython library bundle
   to `CIRCUITPY/lib`.
4. Copy `firmware/boot.py` and `firmware/code.py` to `CIRCUITPY`.
5. Power-cycle the Pico after changing `boot.py`.

See Pimoroni's
[CircuitPython and Pico RGB Keypad guide](https://learn.pimoroni.com/circuitpython-and-keybow-2040)
for PMK and DotStar installation details.

At startup, all LEDs briefly show white. While no Windows process has opened
the CDC data port, key 0 pulses purple. Normal operation begins after the
resident process has synchronized all 16 LED states.

## Windows setup

```powershell
git clone https://github.com/sgknsk526/CodexPicoPanel.git
cd CodexPicoPanel
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Find the Pico's CDC data port in Device Manager. CircuitPython commonly exposes
two COM ports; use the data port, not the console port.

Local tasks only:

```powershell
.\.venv\Scripts\python.exe -m codex_pico_panel --port COM4 --no-remote
```

Local and SSH remote tasks:

```powershell
.\.venv\Scripts\python.exe -m codex_pico_panel `
    --port COM4 `
    --remote-host my-ssh-alias
```

`CODEX_PICO_REMOTE_HOST` may be used instead of `--remote-host`.

## Codex hooks

Hooks send lifecycle state to the loopback-only resident API. Merge the event
entries from [`examples/hooks.windows.json`](examples/hooks.windows.json) into
the Windows user's `~/.codex/hooks.json`, replace `C:\\path\\to` with the
absolute checkout path, and restart Codex.

For a remote host:

1. Configure a working OpenSSH alias in Windows `~/.ssh/config`.
2. Copy `hooks/codex_pico_hook.py` and `hooks/codex_pico_remote_hook.py` to
   `~/.codex/hooks/` on the remote host.
3. Merge [`examples/hooks.remote.json`](examples/hooks.remote.json) into the
   remote `~/.codex/hooks.json`.
4. Start the resident process with `--remote-host my-ssh-alias`.

The resident process maintains a reverse tunnel from remote loopback
`127.0.0.1:48974` to Windows loopback `127.0.0.1:48973`. No hook listener is
exposed on the LAN.

## Start at logon

Use Windows Task Scheduler with **Run only when the user is logged on**. Desktop
shortcuts and UI Automation require an interactive user session.

- Program: `C:\path\to\CodexPicoPanel\.venv\Scripts\pythonw.exe`
- Arguments:
  `-m codex_pico_panel --port COM4 --remote-host my-ssh-alias --log-file "C:\path\to\CodexPicoPanel\.runtime\resident.log"`
- Start in: `C:\path\to\CodexPicoPanel`
- Trigger: At log on
- If already running: Do not start a new instance

Omit `--remote-host` or add `--no-remote` when remote tasks are not needed.

Restart the scheduled resident process from a terminal or by double-clicking
the command file:

```powershell
.\scripts\restart-resident.cmd
```

The script requests a graceful shutdown through Windows loopback, waits for
COM and SSH cleanup, starts the `\Codex Pico Panel` scheduled task, and waits
for the status API to return. Use `-TaskName` when your scheduled task has a
different name.

## Status and diagnostics

Open [http://127.0.0.1:48973/](http://127.0.0.1:48973/) or press key B. The
page shows the COM connection, disconnect count and reason, key mask, LED
states, registrations, visible task, reasoning effort, and collaboration mode.

Runtime registrations are stored in `data/slots.json`. Registrations, virtual
environments, logs, backups, probes, and build output are ignored by Git.

Common problems:

- **Key 0 keeps pulsing purple:** nothing opened the CDC data port, or initial
  LED synchronization did not finish.
- **COM port disappears for several seconds:** check the data cable, USB port,
  and power. The resident process reconnects automatically.
- **Remote task stays white while running:** check for
  `Starting SSH hook tunnel` in the resident log and verify that
  `127.0.0.1:48974` is listening on the remote host.
- **Hook produces no visible error:** delivery failures are intentionally
  non-fatal to Codex. Use the resident log and status page to diagnose them.
- **Port 48973 is already in use:** stop duplicate resident processes.

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m build
```

## Privacy and security

The status and hook servers bind only to `127.0.0.1`. Hook events contain the
session ID, turn ID, lifecycle state, reasoning effort, and collaboration mode;
prompt and response text are not sent to the resident API. The hook may read
the local session transcript to derive failure and thread-setting state.

Approval automation is intentionally guarded by a long press and visible-task
state, but it is still automation. Do not use it in environments where an
accidental approval would be unacceptable.

## License

[MIT](LICENSE)
