"""Read-only local web status server."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import queue

from .codex.hook_event import CodexHookEvent
from .panel_state import PanelState
from .runtime import RuntimeState
from .task_slots import TaskSlots
from .task_status import TaskStatuses


LOGGER = logging.getLogger(__name__)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 48973
HTML_PATH = Path(__file__).parent / "web" / "index.html"
MAX_HOOK_BODY_BYTES = 64 * 1024


def build_status(
    runtime: RuntimeState,
    panel: PanelState,
    slots: TaskSlots,
    statuses: TaskStatuses,
) -> dict[str, object]:
    status = runtime.as_dict()
    key_mask = int(status["key_mask"])
    status["key_mask_hex"] = f"0x{key_mask:04X}"
    status["pressed_keys"] = [
        f"{index:X}"
        for index in range(16)
        if key_mask & (1 << index)
    ]
    status["led_states"] = list(panel.snapshot())
    status["task_slots"] = {
        str(slot): conversation_id
        for slot, conversation_id
        in slots.snapshot().items()
    }

    task_snapshot = statuses.snapshot()
    status["task_statuses"] = task_snapshot
    active_conversation_id = task_snapshot[
        "active_conversation_id"
    ]
    active_status = task_snapshot["tasks"].get(
        active_conversation_id,
        {},
    )
    status["codex_context"] = {
        "thread_id": active_conversation_id,
        "phase": active_status.get("phase"),
        "reasoning_effort": active_status.get(
            "reasoning_effort"
        ),
        "collaboration_mode": active_status.get(
            "collaboration_mode"
        ),
        "source": active_status.get(
            "settings_source"
        ),
        "updated_at": active_status.get(
            "updated_at"
        ),
    }
    return status


def make_handler(
    runtime: RuntimeState,
    panel: PanelState,
    events: queue.Queue[object],
    slots: TaskSlots,
    statuses: TaskStatuses,
) -> type[BaseHTTPRequestHandler]:
    class StatusHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlsplit(self.path).path

            if path == "/":
                self._send(
                    200,
                    HTML_PATH.read_bytes(),
                    "text/html; charset=utf-8",
                )
                return

            if path == "/api/status":
                payload = json.dumps(
                    build_status(
                        runtime,
                        panel,
                        slots,
                        statuses,
                    ),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self._send(
                    200,
                    payload,
                    "application/json; charset=utf-8",
                )
                return

            if path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
                return

            self._send(404, b"Not found", "text/plain; charset=utf-8")

        def _send(
            self,
            status: int,
            body: bytes,
            content_type: str,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            LOGGER.debug(format, *args)

        def do_POST(self) -> None:
            path = urlsplit(self.path).path

            if path != "/api/hooks":
                self._send(
                    404,
                    b"Not found",
                    "text/plain; charset=utf-8",
                )
                return

            try:
                content_length = int(
                    self.headers.get(
                        "Content-Length",
                        "0",
                    )
                )
            except ValueError:
                content_length = 0

            if not (
                0 < content_length <= MAX_HOOK_BODY_BYTES
            ):
                self._send(
                    400,
                    b"Invalid body length",
                    "text/plain; charset=utf-8",
                )
                return

            try:
                body = self.rfile.read(content_length)
                payload = json.loads(
                    body.decode("utf-8")
                )
                event = CodexHookEvent.from_payload(
                    payload
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ) as error:
                self._send(
                    400,
                    str(error).encode("utf-8"),
                    "text/plain; charset=utf-8",
                )
                return

            events.put(event)

            self._send(
                204,
                b"",
                "application/json",
            )

    return StatusHandler


class StatusServer:
    def __init__(
        self,
        runtime,
        panel,
        events: queue.Queue[object],
        slots: TaskSlots,
        statuses: TaskStatuses,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
    ) -> None:
        self._server = ThreadingHTTPServer(
            (host, port),
            make_handler(
                runtime,
                panel,
                events,
                slots,
                statuses,
            ),
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="status-server",
            daemon=True,
        )

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address
        return str(host), int(port)

    def start(self) -> None:
        self._thread.start()
        host, port = self.address
        LOGGER.info("Status page: http://%s:%d/", host, port)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)
