"""Normalized Codex lifecycle event."""

from __future__ import annotations

from dataclasses import dataclass


ALLOWED_HOOK_EVENTS = {
    "UserPromptSubmit",
    "PermissionRequest",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
}

REASONING_EFFORTS = {
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
}

COLLABORATION_MODES = {
    "default",
    "plan",
}

@dataclass(frozen=True)
class CodexHookEvent:
    session_id: str
    event_name: str
    turn_id: str | None = None
    failed: bool = False
    reasoning_effort: str | None = None
    collaboration_mode: str | None = None

    @classmethod
    def from_payload(
        cls,
        payload: object,
    ) -> "CodexHookEvent":
        if not isinstance(payload, dict):
            raise ValueError(
                "hook payload must be an object"
            )

        reasoning_effort = payload.get(
            "reasoning_effort"
        )
        collaboration_mode = payload.get(
            "collaboration_mode"
        )

        if (
            reasoning_effort is not None
            and reasoning_effort
            not in REASONING_EFFORTS
        ):
            raise ValueError(
                "invalid reasoning_effort"
            )

        if (
            collaboration_mode is not None
            and collaboration_mode
            not in COLLABORATION_MODES
        ):
            raise ValueError(
                "invalid collaboration_mode"
            )
        session_id = payload.get("session_id")
        event_name = payload.get(
            "hook_event_name"
        )
        turn_id = payload.get("turn_id")
        failed = payload.get("failed", False)

        if (
            not isinstance(session_id, str)
            or not session_id
        ):
            raise ValueError(
                "session_id must be a string"
            )

        if event_name not in ALLOWED_HOOK_EVENTS:
            raise ValueError(
                "unsupported hook event"
            )

        if turn_id is not None:
            if not isinstance(turn_id, str):
                raise ValueError(
                    "turn_id must be a string or null"
                )

        if not isinstance(failed, bool):
            raise ValueError(
                "failed must be a boolean"
            )

        return cls(
            session_id=session_id,
            event_name=event_name,
            turn_id=turn_id,
            failed=failed,
            reasoning_effort=reasoning_effort,
            collaboration_mode=(
                collaboration_mode
            ),
        )
