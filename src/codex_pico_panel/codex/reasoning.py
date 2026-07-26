from __future__ import annotations

import json
import queue
import time
import threading
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


EFFORTS = {
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
}

LOGGER = logging.getLogger(__name__)

TAIL_BYTES = 4 * 1024 * 1024

REMOTE_PROBE = r"""
import json
import sys
from pathlib import Path

EFFORTS = {
    "low", "medium", "high",
    "xhigh", "max", "ultra",
}

COLLABORATION_MODES = {
    "default",
    "plan",
}


def pick_effort(container):
    if not isinstance(container, dict):
        return None

    for key in ("reasoning_effort", "effort"):
        value = container.get(key)

        if value in EFFORTS:
            return value

    collaboration = container.get(
        "collaboration_mode"
    )

    if isinstance(collaboration, dict):
        settings = collaboration.get("settings")

        if isinstance(settings, dict):
            value = settings.get(
                "reasoning_effort"
            )

            if value in EFFORTS:
                return value

    return None


def pick_mode(container):
    if not isinstance(container, dict):
        return None

    collaboration = container.get(
        "collaboration_mode"
    )

    if isinstance(collaboration, dict):
        mode = collaboration.get("mode")

        if mode in COLLABORATION_MODES:
            return mode

    mode = container.get(
        "collaboration_mode_kind"
    )

    if mode in COLLABORATION_MODES:
        return mode

    return None


def record_effort(record):
    if not isinstance(record, dict):
        return None

    payload = record.get("payload")

    if not isinstance(payload, dict):
        return None

    if record.get("type") == "turn_context":
        return pick_effort(payload)

    if (
        record.get("type") == "event_msg"
        and payload.get("type")
        == "thread_settings_applied"
    ):
        return pick_effort(
            payload.get("thread_settings")
        )

    return None


def record_mode(record):
    if not isinstance(record, dict):
        return None

    payload = record.get("payload")

    if not isinstance(payload, dict):
        return None

    if record.get("type") == "turn_context":
        return pick_mode(payload)

    if record.get("type") != "event_msg":
        return None

    if payload.get("type") == "thread_settings_applied":
        return pick_mode(
            payload.get("thread_settings")
        )

    if payload.get("type") == "task_started":
        return pick_mode(payload)

    return None


conversation_id = sys.argv[1]
root = Path.home() / ".codex" / "sessions"

paths = list(
    root.rglob(
        "*" + conversation_id + "*.jsonl"
    )
)

effort = None
collaboration_mode = None

if paths:
    path = max(
        paths,
        key=lambda item:
            item.stat().st_mtime_ns,
    )

    with path.open("rb") as file:
        file.seek(0, 2)
        size = file.tell()
        file.seek(
            max(0, size - 4 * 1024 * 1024)
        )
        text = file.read().decode(
            "utf-8",
            errors="replace",
        )

    for line in reversed(text.splitlines()):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        if effort is None:
            effort = record_effort(record)

        if collaboration_mode is None:
            collaboration_mode = record_mode(
                record
            )

        if (
            effort is not None
            and collaboration_mode is not None
        ):
            break

print(json.dumps({
    "effort": effort,
    "collaboration_mode": collaboration_mode,
}))
"""

COLLABORATION_MODES = {
    "default",
    "plan",
}

@dataclass
class _TailState:
    path: Path
    offset: int
    remainder: bytes
    effort: str | None
    collaboration_mode: str | None
    identity: tuple[int, int]


@dataclass(frozen=True)
class ReasoningResolved:
    conversation_id: str
    effort: str | None
    source: str
    collaboration_mode: str | None = None

def _pick_effort(
    container: object,
) -> str | None:
    if not isinstance(container, dict):
        return None

    for key in ("reasoning_effort", "effort"):
        value = container.get(key)

        if value in EFFORTS:
            return value

    collaboration = container.get(
        "collaboration_mode"
    )

    if not isinstance(collaboration, dict):
        return None

    settings = collaboration.get("settings")

    if not isinstance(settings, dict):
        return None

    value = settings.get("reasoning_effort")

    return value if value in EFFORTS else None


def _record_effort(
    record: object,
) -> str | None:
    if not isinstance(record, dict):
        return None

    payload = record.get("payload")

    if not isinstance(payload, dict):
        return None

    if record.get("type") == "turn_context":
        return _pick_effort(payload)

    if (
        record.get("type") == "event_msg"
        and payload.get("type")
        == "thread_settings_applied"
    ):
        return _pick_effort(
            payload.get("thread_settings")
        )

    return None

def _pick_collaboration_mode(
    container: object,
) -> str | None:
    if not isinstance(container, dict):
        return None

    collaboration = container.get(
        "collaboration_mode"
    )

    if isinstance(collaboration, dict):
        mode = collaboration.get("mode")

        if mode in COLLABORATION_MODES:
            return mode

    mode = container.get(
        "collaboration_mode_kind"
    )

    return (
        mode
        if mode in COLLABORATION_MODES
        else None
    )


def _record_collaboration_mode(
    record: object,
) -> str | None:
    if not isinstance(record, dict):
        return None

    payload = record.get("payload")

    if not isinstance(payload, dict):
        return None

    if record.get("type") == "turn_context":
        return _pick_collaboration_mode(
            payload
        )

    if record.get("type") != "event_msg":
        return None

    if payload.get("type") == "thread_settings_applied":
        return _pick_collaboration_mode(
            payload.get("thread_settings")
        )

    if payload.get("type") == "task_started":
        return _pick_collaboration_mode(
            payload
        )

    return None


def _read_rollout_settings(
    path: Path,
) -> tuple[str | None, str | None]:
    try:
        with path.open("rb") as file:
            file.seek(0, 2)
            size = file.tell()
            file.seek(max(0, size - TAIL_BYTES))
            text = file.read().decode(
                "utf-8",
                errors="replace",
            )
    except OSError:
        return None, None

    effort = None
    collaboration_mode = None
    for line in reversed(text.splitlines()):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        if effort is None:
            effort = _record_effort(record)

        if collaboration_mode is None:
            collaboration_mode = (
                _record_collaboration_mode(record)
            )

        if (
            effort is not None
            and collaboration_mode is not None
        ):
            break

    return effort, collaboration_mode

class ReasoningResolver:
    def __init__(
        self,
        remote_host: str | None = None,
        remote_python: str = "python3",
    ) -> None:
        self.sessions_root = (
            Path.home() / ".codex" / "sessions"
        )
        self.remote_host = remote_host
        self.remote_python = remote_python
        self._tails = {}
        self._missing_retry_at = {}
        self._inflight_lock = threading.Lock()
        self._inflight: set[
            tuple[str, bool]
        ] = set()

    def tracks_local(
        self,
        conversation_id: str,
    ) -> bool:
        return conversation_id in self._tails

    def _find_local_rollout(
        self,
        conversation_id: str,
    ) -> Path | None:
        now = time.monotonic()

        if now < self._missing_retry_at.get(
            conversation_id,
            0.0,
        ):
            return None

        try:
            paths = list(
                self.sessions_root.rglob(
                    f"*{conversation_id}*.jsonl"
                )
            )
        except OSError:
            paths = []

        if not paths:
            # remoteタスクで毎回rglobしない
            self._missing_retry_at[
                conversation_id
            ] = now + 2.0
            return None

        try:
            return max(
                paths,
                key=lambda path:
                    path.stat().st_mtime_ns,
            )
        except OSError:
            return None


    def _initialize_tail(
        self,
        conversation_id: str,
        path: Path,
    ) -> ReasoningResolved | None:
        try:
            stat = path.stat()
        except OSError:
            return None

        (
            effort,
            collaboration_mode,
        ) = _read_rollout_settings(
            path
        )

        state = _TailState(
            path=path,
            offset=stat.st_size,
            remainder=b"",
            effort=effort,
            collaboration_mode=(
                collaboration_mode
            ),
            identity=(stat.st_dev, stat.st_ino),
        )

        self._tails[conversation_id] = state

        if (
            effort is None
            and collaboration_mode is None
        ):
            return None

        return ReasoningResolved(
            conversation_id=conversation_id,
            effort=effort,
            collaboration_mode=(
                collaboration_mode
            ),
            source="local_rollout_initial",
        )


    def poll_local(
        self,
        conversation_id: str,
    ) -> ReasoningResolved | None:
        state = self._tails.get(conversation_id)

        if state is None:
            path = self._find_local_rollout(
                conversation_id
            )

            if path is None:
                return None

            return self._initialize_tail(
                conversation_id,
                path,
            )

        try:
            stat = state.path.stat()
        except OSError:
            self._tails.pop(
                conversation_id,
                None,
            )
            return None

        identity = (stat.st_dev, stat.st_ino)

        if (
            identity != state.identity
            or stat.st_size < state.offset
        ):
            return self._initialize_tail(
                conversation_id,
                state.path,
            )

        if stat.st_size == state.offset:
            return None

        try:
            with state.path.open("rb") as file:
                file.seek(state.offset)
                data = file.read()
                state.offset = file.tell()
        except OSError:
            return None

        chunks = (
            state.remainder + data
        ).split(b"\n")

        state.remainder = chunks.pop()

        latest_effort = None
        latest_mode = None

        for chunk in chunks:
            if not chunk:
                continue

            try:
                record = json.loads(
                    chunk.decode(
                        "utf-8",
                        errors="replace",
                    )
                )
            except json.JSONDecodeError:
                continue

            effort = _record_effort(record)
            mode = _record_collaboration_mode(
                record
            )

            if effort is not None:
                latest_effort = effort

            if mode is not None:
                latest_mode = mode

        if state.remainder:
            try:
                record = json.loads(
                    state.remainder.decode(
                        "utf-8",
                        errors="replace",
                    )
                )

                effort = _record_effort(record)
                mode = (
                    _record_collaboration_mode(
                        record
                    )
                )

                if effort is not None:
                    latest_effort = effort

                if mode is not None:
                    latest_mode = mode

            except json.JSONDecodeError:
                pass

        effort_changed = (
            latest_effort is not None
            and latest_effort != state.effort
        )

        mode_changed = (
            latest_mode is not None
            and latest_mode
            != state.collaboration_mode
        )

        if not effort_changed and not mode_changed:
            return None

        if effort_changed:
            state.effort = latest_effort

        if mode_changed:
            state.collaboration_mode = (
                latest_mode
            )

        return ReasoningResolved(
            conversation_id=conversation_id,
            effort=state.effort,
            collaboration_mode=(
                state.collaboration_mode
            ),
            source="local_rollout_append",
        )

    def resolve_local(
        self,
        conversation_id: str,
    ) -> ReasoningResolved | None:
        try:
            paths = list(
                self.sessions_root.rglob(
                    f"*{conversation_id}*.jsonl"
                )
            )
        except OSError:
            return None

        if not paths:
            return None

        try:
            path = max(
                paths,
                key=lambda item:
                    item.stat().st_mtime_ns,
            )
        except OSError:
            return None

        (
            effort,
            collaboration_mode,
        ) = _read_rollout_settings(
            path
        )

        if (
            effort is None
            and collaboration_mode is None
        ):
            return None

        return ReasoningResolved(
            conversation_id=conversation_id,
            effort=effort,
            collaboration_mode=(
                collaboration_mode
            ),
            source="local_rollout",
        )

    def resolve_remote(
        self,
        conversation_id: str,
    ) -> ReasoningResolved | None:
        if self.remote_host is None:
            return None

        ssh = shutil.which("ssh")

        if ssh is None:
            LOGGER.warning("ssh.exe was not found")
            return None

        command = [
            ssh,
            "-T",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=3",
            self.remote_host,
            self.remote_python,
            "-",
            conversation_id,
        ]

        try:
            completed = subprocess.run(
                command,
                input=REMOTE_PROBE,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                creationflags=getattr(
                    subprocess,
                    "CREATE_NO_WINDOW",
                    0,
                ),
            )
        except (OSError, subprocess.TimeoutExpired):
            LOGGER.exception(
                "Remote reasoning probe failed"
            )
            return None

        if completed.returncode != 0:
            LOGGER.warning(
                "Remote reasoning probe exited %d: %s",
                completed.returncode,
                completed.stderr.strip(),
            )
            return None

        try:
            payload = json.loads(
                completed.stdout.strip().splitlines()[-1]
            )
        except (
            IndexError,
            json.JSONDecodeError,
        ):
            LOGGER.warning(
                "Invalid remote probe output: %r",
                completed.stdout,
            )
            return None

        effort = payload.get("effort")
        collaboration_mode = payload.get(
            "collaboration_mode"
        )

        if effort not in EFFORTS:
            effort = None

        if (
            collaboration_mode
            not in COLLABORATION_MODES
        ):
            collaboration_mode = None

        if (
            effort is None
            and collaboration_mode is None
        ):
            return None

        return ReasoningResolved(
            conversation_id=conversation_id,
            effort=effort,
            collaboration_mode=(
                collaboration_mode
            ),
            source="remote_rollout_ssh",
        )

    def resolve_async(
        self,
        conversation_id: str,
        events: queue.Queue[object],
        *,
        delay: float = 0.0,
    ) -> bool:
        inflight_key = (
            conversation_id,
            delay > 0,
        )

        with self._inflight_lock:
            if inflight_key in self._inflight:
                return False

            self._inflight.add(inflight_key)

        def worker() -> None:
            try:
                if delay > 0:
                    time.sleep(delay)

                result = self.resolve_local(
                    conversation_id
                )

                if result is None:
                    result = self.resolve_remote(
                        conversation_id
                    )

                if result is not None:
                    events.put(result)
            finally:
                with self._inflight_lock:
                    self._inflight.discard(
                        inflight_key
                    )

        threading.Thread(
            target=worker,
            name="reasoning-resolver",
            daemon=True,
        ).start()
        return True
