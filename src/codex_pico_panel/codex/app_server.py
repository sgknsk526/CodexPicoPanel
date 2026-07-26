from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ThreadSnapshot:
    runtime_type: str
    active_flags: frozenset[str]
    last_turn_status: str | None
    last_turn_completed_at: int | None

    @property
    def running(self) -> bool:
        if self.runtime_type == "active":
            return True

        return (
            self.last_turn_status == "interrupted"
            and self.last_turn_completed_at is None
        )

    @property
    def waiting_on_approval(self) -> bool:
        return (
            "waitingOnApproval"
            in self.active_flags
        )

    @property
    def system_error(self) -> bool:
        return self.runtime_type == "systemError"


class AppServerClient:
    def __init__(
        self,
        command: Sequence[str],
        *,
        request_timeout: float = 5.0,
    ) -> None:
        creationflags = (
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt"
            else 0
        )

        self.process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=creationflags,
        )
        self._next_id = 1
        self.request_timeout = request_timeout
        self._messages: queue.Queue[
            dict | BaseException | None
        ] = queue.Queue()
        self._pending: dict[int, dict] = {}
        self._reader = threading.Thread(
            target=self._read_messages,
            name="app-server-reader",
            daemon=True,
        )
        self._reader.start()

        try:
            self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "codex_pico_panel",
                        "title": "Codex Pico Panel",
                        "version": "0.1.0",
                    },
                },
            )

            self._send({
                "method": "initialized",
                "params": {},
            })
        except Exception:
            self.close()
            raise

    def _read_messages(self) -> None:
        stdout = self.process.stdout

        if stdout is None:
            self._messages.put(
                RuntimeError(
                    "App Server stdout is unavailable"
                )
            )
            self._messages.put(None)
            return

        try:
            for line in stdout:
                message = json.loads(line)

                if isinstance(message, dict):
                    self._messages.put(message)
        except BaseException as error:
            self._messages.put(error)
        finally:
            self._messages.put(None)

    def _send(self, message: dict) -> None:
        if self.process.stdin is None:
            raise RuntimeError(
                "App Server stdin is unavailable"
            )

        self.process.stdin.write(
            json.dumps(message) + "\n"
        )
        self.process.stdin.flush()

    def request(
        self,
        method: str,
        params: dict,
    ) -> dict:
        request_id = self._next_id
        self._next_id += 1

        self._send({
            "method": method,
            "id": request_id,
            "params": params,
        })

        pending = self._pending.pop(
            request_id,
            None,
        )

        if pending is not None:
            return pending

        deadline = (
            time.monotonic()
            + self.request_timeout
        )

        while True:
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                raise RuntimeError(
                    f"App Server request timed out: {method}"
                )

            try:
                message = self._messages.get(
                    timeout=remaining
                )
            except queue.Empty as error:
                raise RuntimeError(
                    f"App Server request timed out: {method}"
                ) from error

            if message is None:
                raise RuntimeError(
                    "App Server terminated"
                )

            if isinstance(message, BaseException):
                raise RuntimeError(
                    "App Server output reader failed"
                ) from message

            response_id = message.get("id")

            if response_id == request_id:
                return message

            if isinstance(response_id, int):
                self._pending[response_id] = message

    def read_thread(
        self,
        thread_id: str,
    ) -> ThreadSnapshot | None:
        response = self.request(
            "thread/read",
            {
                "threadId": thread_id,
                "includeTurns": True,
            },
        )

        if "error" in response:
            return None

        result = response.get("result")

        if not isinstance(result, dict):
            raise RuntimeError(
                "Invalid App Server thread/read result"
            )

        thread = result.get("thread")

        if not isinstance(thread, dict):
            raise RuntimeError(
                "Invalid App Server thread"
            )

        runtime = thread.get("status", {})
        turns = thread.get("turns", [])

        if not isinstance(runtime, dict):
            runtime = {}

        if not isinstance(turns, list):
            turns = []

        last_turn = (
            turns[-1]
            if turns
            and isinstance(turns[-1], dict)
            else {}
        )
        active_flags = runtime.get(
            "activeFlags",
            [],
        )

        if not isinstance(active_flags, list):
            active_flags = []

        return ThreadSnapshot(
            runtime_type=runtime.get(
                "type",
                "notLoaded",
            ),
            active_flags=frozenset(
                flag
                for flag in active_flags
                if isinstance(flag, str)
            ),
            last_turn_status=last_turn.get(
                "status"
            ),
            last_turn_completed_at=(
                last_turn.get("completedAt")
            ),
        )

    def close(self) -> None:
        stdin = self.process.stdin

        if stdin is not None and not stdin.closed:
            try:
                stdin.close()
            except OSError:
                pass

        if self.process.poll() is None:
            self.process.terminate()

            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)

        self._reader.join(timeout=1.0)

        stdout = self.process.stdout

        if stdout is not None and not stdout.closed:
            try:
                stdout.close()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
