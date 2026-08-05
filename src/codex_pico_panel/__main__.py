"""Codex Pico Panel Windows resident process."""

from __future__ import annotations

import argparse
import logging
import os
import queue
import sys
from pathlib import Path

from .codex.app_server import AppServerClient
from .codex.composer import ComposerMonitor
from .codex.desktop_log import CodexDesktopLog
from .codex.reasoning import ReasoningResolver
from .codex.remote_status import RemoteStatusResolver
from .codex.shortcuts import CodexShortcuts
from .controller import Controller
from .panel_state import PanelState
from .pico_link import PicoEvent, PicoLink
from .runtime import RuntimeState
from .ssh_tunnel import SshHookTunnel
from .status_server import StatusServer
from .task_slots import TaskSlots
from .task_status import TaskStatuses



def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        required=True,
        help="Pico CDC data port, e.g. COM4",
    )
    parser.add_argument(
        "--status-port",
        type=int,
        default=int(
            os.environ.get(
                "CODEX_PICO_STATUS_PORT",
                "48973",
            )
        ),
        help="Loopback status/hook port",
    )
    parser.add_argument(
        "--remote-host",
        default=os.environ.get("CODEX_PICO_REMOTE_HOST"),
        help=(
            "SSH host for remote tasks "
            "(or CODEX_PICO_REMOTE_HOST)"
        ),
    )
    parser.add_argument(
        "--remote-hook-port",
        type=int,
        default=int(
            os.environ.get(
                "CODEX_PICO_REMOTE_HOOK_PORT",
                "48974",
            )
        ),
        help="Remote loopback port for the reverse hook tunnel",
    )
    parser.add_argument(
        "--no-remote",
        action="store_true",
        help="Disable remote app-server probes and SSH hook tunnel",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Optional UTF-8 resident log file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    handlers: list[logging.Handler] = [
        logging.StreamHandler()
    ]

    if args.log_file is not None:
        args.log_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        handlers.append(
            logging.FileHandler(
                args.log_file,
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ),
        handlers=handlers,
    )

    project_root = Path(__file__).resolve().parents[2]

    events: queue.Queue[object] = queue.Queue()
    composer_monitor = ComposerMonitor(events)

    runtime = RuntimeState()
    panel = PanelState()
    status_page_url = (
        f"http://127.0.0.1:{args.status_port}/"
    )
    shortcuts = CodexShortcuts(status_page_url)
    slots = TaskSlots(
        project_root / "data" / "slots.json"
    )
    desktop_log = CodexDesktopLog()
    statuses = TaskStatuses()
    bindings = slots.snapshot()
    unresolved = set(bindings.values())
    remote_host = (
        None
        if args.no_remote or not args.remote_host
        else args.remote_host
    )
    reasoning = ReasoningResolver(
        remote_host=remote_host
    )
    remote_status = (
        RemoteStatusResolver(remote_host)
        if remote_host is not None
        else None
    )

    commands = [
        ["codex", "app-server"],
    ]

    if remote_host is not None:
        commands.append([
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=3",
            remote_host,
            "codex", "app-server",
        ])

    for command in commands:
        if not unresolved:
            break

        try:
            with AppServerClient(command) as client:
                for conversation_id in list(
                    unresolved
                ):
                    snapshot = client.read_thread(
                        conversation_id
                    )

                    if snapshot is None:
                        continue

                    statuses.restore_runtime_status(
                        conversation_id,
                        running=snapshot.running,
                        waiting_on_approval=(
                            snapshot.waiting_on_approval
                        ),
                        system_error=(
                            snapshot.system_error
                        ),
                    )

                    unresolved.remove(conversation_id)

        except (OSError, RuntimeError):
            logging.getLogger(__name__).exception(
                "Could not read startup task status"
            )

    pico = PicoLink(
        args.port,
        events,
    )

    controller = Controller(
        events,
        pico,
        panel,
        runtime,
        shortcuts,
        slots,
        desktop_log,
        statuses,
        composer_monitor,
        reasoning,
        remote_status=remote_status,
    )

    status_server = StatusServer(
        runtime,
        panel,
        events,
        slots,
        statuses,
        port=args.status_port,
        shutdown_callback=controller.stop,
    )

    ssh_tunnel = (
        SshHookTunnel(
            host=remote_host,
            remote_port=args.remote_hook_port,
            local_port=args.status_port,
        )
        if remote_host is not None
        else None
    )

    status_server.start()
    if ssh_tunnel is not None:
        ssh_tunnel.start()
    pico.start()
    composer_monitor.start()
    try:
        controller.run()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Shutdown requested")
    finally:
        controller.stop()

        if ssh_tunnel is not None:
            ssh_tunnel.stop()
        pico.stop()

        if ssh_tunnel is not None:
            ssh_tunnel.join(timeout=3.0)
        pico.join(timeout=2.0)

        composer_monitor.stop()
        composer_monitor.join(timeout=2.0)

        status_server.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
