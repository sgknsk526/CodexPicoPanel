from __future__ import annotations

import json
import logging
import queue
import shutil
import subprocess
import threading
from dataclasses import dataclass


LOGGER = logging.getLogger(__name__)

REMOTE_STATUS_PROBE = r"""
import json
import re
import sys
from pathlib import Path

STATE_EVENTS = {
    "task_started": "running",
    "task_complete": "completed",
    "turn_aborted": "aborted",
}

EXIT_PATTERNS = (
    re.compile(
        r"(?im)^Exit code:\s*(-?\d+)\s*$"
    ),
    re.compile(
        r"(?im)Process exited with code\s+(-?\d+)"
    ),
)


def reverse_records(path):
    chunk_size = 64 * 1024

    with path.open("rb") as file:
        file.seek(0, 2)
        position = file.tell()
        fragment = b""

        while position > 0:
            amount = min(chunk_size, position)
            position -= amount
            file.seek(position)
            block = file.read(amount) + fragment
            lines = block.split(b"\n")
            fragment = lines[0]

            for line in reversed(lines[1:]):
                if not line:
                    continue

                try:
                    yield json.loads(
                        line.decode(
                            "utf-8",
                            errors="replace",
                        )
                    )
                except json.JSONDecodeError:
                    continue

        if fragment:
            try:
                yield json.loads(
                    fragment.decode(
                        "utf-8",
                        errors="replace",
                    )
                )
            except json.JSONDecodeError:
                pass


def output_failed(output):
    if not isinstance(output, str):
        return False

    for pattern in EXIT_PATTERNS:
        match = pattern.search(output)

        if match is not None:
            return int(match.group(1)) != 0

    return False


def latest_tool_failed(records, turn_id):
    for record in records:
        if record.get("type") != "response_item":
            continue

        payload = record.get("payload")

        if not isinstance(payload, dict):
            continue

        if payload.get("type") not in {
            "function_call_output",
            "custom_tool_call_output",
        }:
            continue

        metadata = payload.get(
            "internal_chat_message_metadata_passthrough"
        )

        if (
            not isinstance(metadata, dict)
            or metadata.get("turn_id") != turn_id
        ):
            continue

        return output_failed(payload.get("output"))

    return False


def read_snapshot(path, conversation_id):
    records = reverse_records(path)

    for record in records:
        if record.get("type") != "event_msg":
            continue

        payload = record.get("payload")

        if not isinstance(payload, dict):
            continue

        event_name = payload.get("type")
        state = STATE_EVENTS.get(event_name)
        turn_id = payload.get("turn_id")

        if (
            state is None
            or not isinstance(turn_id, str)
        ):
            continue

        failed = (
            latest_tool_failed(records, turn_id)
            if state == "completed"
            else False
        )

        return {
            "conversation_id": conversation_id,
            "state": state,
            "turn_id": turn_id,
            "failed": failed,
            "timestamp": record.get("timestamp"),
        }

    return None


wanted = set(sys.argv[1:])
root = Path.home() / ".codex" / "sessions"
paths = {}

for path in root.rglob("rollout-*.jsonl"):
    name = path.name

    for conversation_id in tuple(wanted):
        if conversation_id not in name:
            continue

        previous = paths.get(conversation_id)

        if (
            previous is None
            or path.stat().st_mtime_ns
            > previous.stat().st_mtime_ns
        ):
            paths[conversation_id] = path

snapshots = []

for conversation_id, path in paths.items():
    snapshot = read_snapshot(
        path,
        conversation_id,
    )

    if snapshot is not None:
        snapshots.append(snapshot)

print(json.dumps(
    {"snapshots": snapshots},
    separators=(",", ":"),
))
"""


@dataclass(frozen=True)
class RemoteTaskSnapshot:
    conversation_id: str
    state: str
    turn_id: str
    failed: bool
    timestamp: str | None


@dataclass(frozen=True)
class RemoteStatusesResolved:
    snapshots: tuple[RemoteTaskSnapshot, ...]
    initial_ids: frozenset[str]


def parse_probe_output(
    output: str,
) -> tuple[RemoteTaskSnapshot, ...]:
    try:
        payload = json.loads(
            output.strip().splitlines()[-1]
        )
    except (IndexError, json.JSONDecodeError):
        raise ValueError(
            "invalid remote status probe output"
        ) from None

    values = payload.get("snapshots")

    if not isinstance(values, list):
        raise ValueError(
            "remote status snapshots must be a list"
        )

    snapshots: list[RemoteTaskSnapshot] = []

    for value in values:
        if not isinstance(value, dict):
            continue

        conversation_id = value.get(
            "conversation_id"
        )
        state = value.get("state")
        turn_id = value.get("turn_id")
        failed = value.get("failed")
        timestamp = value.get("timestamp")

        if (
            not isinstance(conversation_id, str)
            or state
            not in {"running", "completed", "aborted"}
            or not isinstance(turn_id, str)
            or not isinstance(failed, bool)
            or (
                timestamp is not None
                and not isinstance(timestamp, str)
            )
        ):
            continue

        snapshots.append(RemoteTaskSnapshot(
            conversation_id=conversation_id,
            state=state,
            turn_id=turn_id,
            failed=failed,
            timestamp=timestamp,
        ))

    return tuple(snapshots)


class RemoteStatusResolver:
    def __init__(
        self,
        host: str,
        *,
        timeout: float = 8.0,
    ) -> None:
        self.host = host
        self.timeout = timeout
        self._lock = threading.Lock()
        self._inflight = False
        self._last_values: dict[
            str,
            tuple[str, str, bool],
        ] = {}

    def resolve(
        self,
        conversation_ids: tuple[str, ...],
    ) -> tuple[RemoteTaskSnapshot, ...]:
        ssh = shutil.which("ssh")

        if ssh is None:
            raise RuntimeError("ssh.exe was not found")

        command = [
            ssh,
            "-T",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=3",
            self.host,
            "python3",
            "-",
            *conversation_ids,
        ]
        completed = subprocess.run(
            command,
            input=REMOTE_STATUS_PROBE,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout,
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            ),
        )

        if completed.returncode != 0:
            raise RuntimeError(
                "remote status probe exited "
                f"{completed.returncode}: "
                f"{completed.stderr.strip()}"
            )

        return parse_probe_output(completed.stdout)

    def resolve_async(
        self,
        conversation_ids: tuple[str, ...],
        events: queue.Queue[object],
    ) -> bool:
        with self._lock:
            if self._inflight:
                return False

            self._inflight = True

        def worker() -> None:
            try:
                snapshots = self.resolve(
                    conversation_ids
                )
                changed = []
                initial_ids = set()

                with self._lock:
                    for snapshot in snapshots:
                        value = (
                            snapshot.state,
                            snapshot.turn_id,
                            snapshot.failed,
                        )

                        previous = self._last_values.get(
                            snapshot.conversation_id
                        )

                        if previous == value:
                            continue

                        if previous is None:
                            initial_ids.add(
                                snapshot.conversation_id
                            )

                        self._last_values[
                            snapshot.conversation_id
                        ] = value
                        changed.append(snapshot)

                if changed:
                    events.put(RemoteStatusesResolved(
                        snapshots=tuple(changed),
                        initial_ids=frozenset(
                            initial_ids
                        ),
                    ))
            except (
                OSError,
                RuntimeError,
                subprocess.TimeoutExpired,
                ValueError,
            ):
                LOGGER.exception(
                    "Remote status reconciliation failed"
                )
            finally:
                with self._lock:
                    self._inflight = False

        threading.Thread(
            target=worker,
            name="remote-status-resolver",
            daemon=True,
        ).start()
        return True
