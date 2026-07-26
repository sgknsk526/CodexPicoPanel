from __future__ import annotations

import argparse
import json
import shutil

from codex_pico_panel.codex.app_server import (
    AppServerClient,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("thread_id")
    parser.add_argument("--remote-host")
    return parser.parse_args()


def main():
    args = parse_args()
    codex = shutil.which("codex")

    if codex is None:
        raise RuntimeError("codex.exe not found")

    command = [codex, "app-server"]

    if args.remote_host:
        ssh = shutil.which("ssh")

        if ssh is None:
            raise RuntimeError("ssh.exe not found")

        command = [
            ssh,
            "-T",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=3",
            args.remote_host,
            "codex", "app-server",
        ]

    with AppServerClient(command) as client:
        snapshot = client.read_thread(
            args.thread_id
        )

    print(json.dumps(
        (
            {
                "runtime_type":
                    snapshot.runtime_type,
                "active_flags":
                    sorted(snapshot.active_flags),
                "last_turn_status":
                    snapshot.last_turn_status,
                "last_turn_completed_at":
                    snapshot.last_turn_completed_at,
                "running": snapshot.running,
                "waiting_on_approval":
                    snapshot.waiting_on_approval,
                "system_error":
                    snapshot.system_error,
            }
            if snapshot is not None
            else None
        ),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
