"""Detect the active Codex Desktop conversation."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path


ACTIVE_MARKER = (
    "thread_stream_view_activity_changed active=true"
)

APPROVAL_RESPONSE_MARKER = (
    "method=item/commandExecution/requestApproval"
)

APPROVAL_DECISION_PATTERN = re.compile(
    r'response=\{"decision":"([^"]+)"\}'
)

CONVERSATION_PATTERN = re.compile(
    r"conversationId=([0-9a-f-]{36})"
)

TAIL_BYTES = 2 * 1024 * 1024

@dataclass(frozen=True)
class ActiveConversation:
    conversation_id: str
    token: str

@dataclass(frozen=True)
class ApprovalResponse:
    decision: str | None
    token: str

class CodexDesktopLog:
    def __init__(self) -> None:
        local_app_data = Path(
            os.environ["LOCALAPPDATA"]
        )

        # Store版の実パスを優先する。
        self.log_roots = (
            local_app_data
            / "Packages"
            / "OpenAI.Codex_2p2nqsd0c76g0"
            / "LocalCache"
            / "Local"
            / "Codex"
            / "Logs",
            local_app_data / "Codex" / "Logs",
        )

    def _latest_log_path(self) -> Path | None:
        # 両方を混ぜると同一ログを重複検出する場合があるため、
        # 最初にログが見つかったrootだけを使う。
        for root in self.log_roots:
            if not root.exists():
                continue

            candidates = list(
                root.rglob("*-t0-*.log")
            )

            if not candidates:
                continue

            try:
                return max(
                    candidates,
                    key=lambda path: (
                        path.stat().st_mtime_ns
                    ),
                )
            except OSError:
                continue

        return None

    def current(self) -> ActiveConversation | None:
        path = self._latest_log_path()

        if path is None:
            return None

        try:
            with path.open("rb") as file:
                file.seek(0, os.SEEK_END)
                size = file.tell()

                file.seek(
                    max(0, size - TAIL_BYTES)
                )

                data = file.read()
        except OSError:
            return None

        text = data.decode(
            "utf-8",
            errors="replace",
        )

        for line in reversed(text.splitlines()):
            if ACTIVE_MARKER not in line:
                continue

            if "rendererWindowFocused=true" not in line:
                continue

            if "rendererWindowVisible=true" not in line:
                continue

            match = CONVERSATION_PATTERN.search(line)

            if match is None:
                continue

            return ActiveConversation(
                conversation_id=match.group(1),
                token=f"{path}:{line}",
            )

        return None

    def latest_approval_response(
        self,
    ) -> ApprovalResponse | None:
        path = self._latest_log_path()

        if path is None:
            return None

        try:
            with path.open("rb") as file:
                file.seek(0, os.SEEK_END)
                size = file.tell()

                file.seek(
                    max(0, size - TAIL_BYTES)
                )

                data = file.read()
        except OSError:
            return None

        text = data.decode(
            "utf-8",
            errors="replace",
        )

        for line in reversed(text.splitlines()):
            if APPROVAL_RESPONSE_MARKER not in line:
                continue

            match = APPROVAL_DECISION_PATTERN.search(
                line
            )

            decision = (
                match.group(1)
                if match is not None
                else None
            )

            return ApprovalResponse(
                decision=decision,
                token=f"{path}:{line}",
            )

        return None

    def wait_after(
        self,
        previous: ActiveConversation | None,
        timeout: float = 1.0,
        *,
        fallback_to_previous: bool = False,
    ) -> ActiveConversation | None:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            current = self.current()

            if current is not None:
                if previous is None:
                    return current

                if current.token != previous.token:
                    return current

            time.sleep(0.05)

        if fallback_to_previous:
            return previous

        return None
