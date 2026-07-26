"""Forward selected Codex lifecycle events to Windows resident app."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import re

HOOK_PORT = os.environ.get(
    "CODEX_PICO_HOOK_PORT",
    "48973" if os.name == "nt" else "48974",
)
ENDPOINT = os.environ.get(
    "CODEX_PICO_HOOK_ENDPOINT",
    f"http://127.0.0.1:{HOOK_PORT}/api/hooks",
)
TIMEOUT_SECONDS = 0.5

ALLOWED_EVENTS = {
    "UserPromptSubmit",
    "PermissionRequest",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
}


EXIT_CODE_PATTERN = re.compile(
    r"(?m)^Exit code:\s*(-?\d+)\s*$"
)

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


def turn_reasoning_effort(
    payload: dict[str, object],
) -> str | None:
    transcript_path = payload.get(
        "transcript_path"
    )
    turn_id = payload.get("turn_id")

    if (
        not isinstance(transcript_path, str)
        or not isinstance(turn_id, str)
    ):
        return None

    result = None

    try:
        with open(
            transcript_path,
            "r",
            encoding="utf-8",
            errors="replace",
        ) as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if record.get("type") != "turn_context":
                    continue

                context = record.get("payload")

                if (
                    not isinstance(context, dict)
                    or context.get("turn_id") != turn_id
                ):
                    continue

                effort = context.get("effort")

                if effort in REASONING_EFFORTS:
                    result = effort
                    continue

                collaboration = context.get(
                    "collaboration_mode"
                )

                if isinstance(collaboration, dict):
                    settings = collaboration.get(
                        "settings"
                    )

                    if isinstance(settings, dict):
                        effort = settings.get(
                            "reasoning_effort"
                        )

                        if effort in REASONING_EFFORTS:
                            result = effort

    except OSError:
        return None

    return result


def turn_collaboration_mode(
    payload: dict[str, object],
) -> str | None:
    transcript_path = payload.get(
        "transcript_path"
    )
    turn_id = payload.get("turn_id")

    if (
        not isinstance(transcript_path, str)
        or not isinstance(turn_id, str)
    ):
        return None

    result = None

    try:
        with open(
            transcript_path,
            "r",
            encoding="utf-8",
            errors="replace",
        ) as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if record.get("type") != "turn_context":
                    continue

                context = record.get("payload")

                if (
                    not isinstance(context, dict)
                    or context.get("turn_id") != turn_id
                ):
                    continue

                collaboration = context.get(
                    "collaboration_mode"
                )

                if isinstance(collaboration, dict):
                    mode = collaboration.get("mode")

                    if mode in COLLABORATION_MODES:
                        result = mode

                mode = context.get(
                    "collaboration_mode_kind"
                )

                if mode in COLLABORATION_MODES:
                    result = mode

    except OSError:
        return None

    return result

def turn_approvals_reviewer(
    payload: dict[str, object],
) -> str | None:
    transcript_path = payload.get(
        "transcript_path"
    )
    turn_id = payload.get("turn_id")

    if (
        not isinstance(transcript_path, str)
        or not isinstance(turn_id, str)
    ):
        return None

    reviewer: str | None = None

    try:
        with open(
            transcript_path,
            "r",
            encoding="utf-8",
            errors="replace",
        ) as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if record.get("type") != "turn_context":
                    continue

                context = record.get("payload")

                if not isinstance(context, dict):
                    continue

                if context.get("turn_id") != turn_id:
                    continue

                value = context.get(
                    "approvals_reviewer"
                )

                if isinstance(value, str):
                    reviewer = value

    except OSError:
        return None

    return reviewer

def stop_turn_failed(
    payload: dict[str, object],
) -> bool:
    if payload.get("hook_event_name") != "Stop":
        return False

    transcript_path = payload.get(
        "transcript_path"
    )
    turn_id = payload.get("turn_id")

    if (
        not isinstance(transcript_path, str)
        or not isinstance(turn_id, str)
    ):
        return False

    try:
        with open(
            transcript_path,
            "r",
            encoding="utf-8",
            errors="replace",
        ) as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if record.get("type") != "response_item":
                    continue

                item = record.get("payload")

                if not isinstance(item, dict):
                    continue

                if item.get("type") != "function_call_output":
                    continue

                metadata = item.get(
                    "internal_chat_message_metadata_passthrough"
                )

                if not isinstance(metadata, dict):
                    continue

                if metadata.get("turn_id") != turn_id:
                    continue

                output = item.get("output")

                if not isinstance(output, str):
                    continue

                match = EXIT_CODE_PATTERN.search(
                    output
                )

                if (
                    match is not None
                    and int(match.group(1)) != 0
                ):
                    return True

    except OSError:
        return False

    return False

def post_tool_failed(
    payload: dict[str, object],
) -> bool:
    event_name = payload.get("hook_event_name")

    if event_name == "PostToolUseFailure":
        return True

    if event_name != "PostToolUse":
        return False

    def contains_failure(value: object) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = key.lower().replace("_", "")

                if normalized in {"iserror", "failed"}:
                    if child is True:
                        return True

                if normalized == "success":
                    if child is False:
                        return True

                if normalized in {"exitcode", "exitstatus"}:
                    try:
                        if int(child) != 0:
                            return True
                    except (TypeError, ValueError):
                        pass

                if contains_failure(child):
                    return True

            return False

        if isinstance(value, list):
            return any(
                contains_failure(item)
                for item in value
            )

        if isinstance(value, str):
            match = re.search(
                r"(?im)\bexit\s+code\s*:\s*(-?\d+)",
                value,
            )

            return (
                match is not None
                and int(match.group(1)) != 0
            )

        return False

    return contains_failure(
        payload.get("tool_response")
    )

def send_event(payload: dict[str, object]) -> None:
    session_id = payload.get("session_id")
    event_name = payload.get("hook_event_name")

    if (
        not isinstance(session_id, str)
        or not session_id
    ):
        return

    if event_name not in ALLOWED_EVENTS:
        return

    failed = post_tool_failed(payload)

    if event_name == "Stop":
        failed = stop_turn_failed(payload)

    if event_name == "PermissionRequest":
        reviewer = turn_approvals_reviewer(
            payload
        )

        if reviewer == "auto_review":
            return

    event = {
        "session_id": session_id,
        "hook_event_name": event_name,
        "turn_id": payload.get("turn_id"),
        "failed": failed,
        "reasoning_effort": (
            turn_reasoning_effort(payload)
        ),
        "collaboration_mode": (
            turn_collaboration_mode(payload)
        ),
    }

    body = json.dumps(
        event,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=TIMEOUT_SECONDS,
        ) as response:
            response.read()
    except Exception:
        # 常駐アプリが停止していてもCodexを止めない。
        pass


def main() -> None:
    try:
        payload = json.load(sys.stdin)

        if isinstance(payload, dict):
            send_event(payload)
    except Exception:
        pass
    finally:
        # Stop hookはJSON出力を要求する。
        sys.stdout.write("{}")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
