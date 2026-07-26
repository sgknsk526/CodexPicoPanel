"""Runtime state of registered Codex tasks."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .codex.hook_event import CodexHookEvent


LED_UNREGISTERED = 0x0
LED_THINKING = 0x1
LED_UNREAD = 0x3
LED_ACTION_REQUIRED = 0x8
LED_REGISTERED = 0xD
LED_ERROR = 0xF


@dataclass
class TaskStatus:
    phase: str = "idle"
    outcome: str = "none"
    unread: bool = False
    turn_had_error: bool = False
    last_event: str | None = None
    updated_at: str | None = None
    reasoning_effort: str | None = None
    collaboration_mode: str | None = None
    settings_source: str | None = None

class TaskStatuses:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, TaskStatus] = {}
        self._active_conversation_id: str | None = None

    def ensure(
        self,
        conversation_id: str,
    ) -> None:
        with self._lock:
            self._values.setdefault(
                conversation_id,
                TaskStatus(),
            )

    def set_active(
        self,
        conversation_id: str,
    ) -> None:
        with self._lock:
            self._active_conversation_id = (
                conversation_id
            )

            status = self._values.setdefault(
                conversation_id,
                TaskStatus(),
            )

            status.unread = False
            status.outcome = "none"


    def apply_hook(
        self,
        event: CodexHookEvent,
    ) -> None:
        with self._lock:
            status = self._values.setdefault(
                event.session_id,
                TaskStatus(),
            )

            if event.reasoning_effort is not None:
                status.reasoning_effort = (
                    event.reasoning_effort
                )

            if event.collaboration_mode is not None:
                status.collaboration_mode = (
                    event.collaboration_mode
                )

            if (
                event.reasoning_effort is not None
                or event.collaboration_mode is not None
            ):
                status.settings_source = "hook"

            status.last_event = event.event_name
            status.updated_at = datetime.now(
                timezone.utc
            ).isoformat()

            if event.event_name == "UserPromptSubmit":
                status.phase = "thinking"
                status.outcome = "none"
                status.unread = False
                status.turn_had_error = False

            elif event.event_name == "PermissionRequest":
                status.phase = "action_required"

            elif event.event_name in {
                "PostToolUse",
                "PostToolUseFailure",
            }:
                status.phase = "thinking"

                if (
                    event.failed
                    or event.event_name
                    == "PostToolUseFailure"
                ):
                    status.turn_had_error = True

            elif event.event_name == "Stop":
                failed = (
                    event.failed
                    or status.turn_had_error
                )
                status.phase = "idle"
                status.outcome = (
                    "error"
                    if failed
                    else "success"
                )
                status.unread = (
                    event.session_id
                    != self._active_conversation_id
                )
                status.turn_had_error = False

    def led_state(
        self,
        conversation_id: str,
    ) -> int:
        with self._lock:
            status = self._values.get(
                conversation_id
            )

            if status is None:
                return LED_REGISTERED

            if status.phase == "action_required":
                return LED_ACTION_REQUIRED

            if status.phase == "thinking":
                return LED_THINKING

            if status.unread:
                if status.outcome == "error":
                    return LED_ERROR

                if status.outcome == "success":
                    return LED_UNREAD

            return LED_REGISTERED

    def update_settings(
        self,
        conversation_id: str,
        *,
        effort: str | None,
        collaboration_mode: str | None,
        source: str,
    ) -> bool:
        with self._lock:
            status = self._values.setdefault(
                conversation_id,
                TaskStatus(),
            )
            changed = False

            if (
                effort is not None
                and effort
                != status.reasoning_effort
            ):
                status.reasoning_effort = effort
                changed = True

            if (
                collaboration_mode is not None
                and collaboration_mode
                != status.collaboration_mode
            ):
                status.collaboration_mode = (
                    collaboration_mode
                )
                changed = True

            if (
                changed
                or source != status.settings_source
            ):
                status.updated_at = datetime.now(
                    timezone.utc
                ).isoformat()
                status.settings_source = source

            return changed

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "active_conversation_id":
                    self._active_conversation_id,
                "tasks": {
                    conversation_id: asdict(status)
                    for conversation_id, status
                    in self._values.items()
                },
            }

    def set_reasoning_effort(
        self,
        conversation_id: str,
        effort: str,
    ) -> None:
        with self._lock:
            status = self._values.setdefault(
                conversation_id,
                TaskStatus(),
            )
            status.reasoning_effort = effort


    def reasoning_effort(
        self,
        conversation_id: str,
    ) -> str | None:
        with self._lock:
            status = self._values.get(
                conversation_id
            )

            if status is None:
                return None

            return status.reasoning_effort

    def set_collaboration_mode(
        self,
        conversation_id: str,
        mode: str,
    ) -> None:
        with self._lock:
            status = self._values.setdefault(
                conversation_id,
                TaskStatus(),
            )
            status.collaboration_mode = mode


    def collaboration_mode(
        self,
        conversation_id: str,
    ) -> str | None:
        with self._lock:
            status = self._values.get(conversation_id)

            if status is None:
                return None

            return status.collaboration_mode

    def phase(
        self,
        conversation_id: str,
    ) -> str | None:
        with self._lock:
            status = self._values.get(
                conversation_id
            )

            if status is None:
                return None

            return status.phase

    def resolve_approval(self) -> str | None:
        with self._lock:
            pending = [
                conversation_id
                for conversation_id, status
                in self._values.items()
                if status.phase == "action_required"
            ]

            target: str | None = None

            if len(pending) == 1:
                target = pending[0]

            elif (
                self._active_conversation_id
                in pending
            ):
                target = self._active_conversation_id

            if target is None:
                return None

            status = self._values[target]
            status.phase = "thinking"
            status.last_event = "ApprovalResolved"
            status.updated_at = datetime.now(
                timezone.utc
            ).isoformat()

            return target

    def restore_runtime_status(
        self,
        conversation_id: str,
        *,
        running: bool,
        waiting_on_approval: bool,
        system_error: bool,
    ) -> None:
        with self._lock:
            status = self._values.setdefault(
                conversation_id,
                TaskStatus(),
            )

            if waiting_on_approval:
                status.phase = "action_required"

            elif running:
                status.phase = "thinking"

            elif system_error:
                status.phase = "idle"
                status.outcome = "error"
                status.unread = True

            else:
                status.phase = "idle"
