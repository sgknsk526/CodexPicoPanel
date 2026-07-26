from __future__ import annotations

import logging
import queue
import time
import threading
from dataclasses import dataclass
from typing import Literal

from .window import (
    foreground_window_handle,
    is_codex_foreground,
)


LOGGER = logging.getLogger(__name__)
POLL_SECONDS = 0.2

ComposerAction = Literal[
    "send",
    "clear",
    "stop",
    "approve_request",
    "reject_request",
    "approve_message",
    "reject_message",
]

APPROVE_BUTTON_NAMES = {
    "承認",
    "リクエストを承認",
    "許可",
    "今回のみ許可",
    "Approve",
    "Approve request",
    "Allow",
    "Allow once",
}

REJECT_BUTTON_NAMES = {
    "拒否",
    "リクエストを拒否",
    "却下",
    "Reject",
    "Reject request",
    "Deny",
}


@dataclass(frozen=True)
class ComposerStateChanged:
    ready: bool
    running: bool
    available: bool = False


class ComposerMonitor(threading.Thread):
    def __init__(
        self,
        events: queue.Queue[object],
    ) -> None:
        super().__init__(
            name="composer-monitor",
            daemon=True,
        )
        self.events = events
        self._commands = queue.SimpleQueue()
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def perform(
        self,
        action: ComposerAction,
    ) -> None:
        self._commands.put(action)

    def _window(self, desktop):
        hwnd = foreground_window_handle()

        if hwnd is None:
            return None

        return desktop.window(handle=hwnd)

    def _find_composer(self, window):
        for edit in window.descendants(
            control_type="Edit"
        ):
            name = (
                edit.element_info.name or ""
            ).strip()

            if name in {
                "何でもできます",
                "Ask anything",
            }:
                return edit

        return None

    def _find_stop_button(self, window):
        for button in window.descendants(
            control_type="Button"
        ):
            name = (
                button.element_info.name or ""
            ).strip()

            if name in {"停止", "Stop"}:
                return button

        return None

    def _read_state(
        self,
        desktop,
    ) -> tuple[bool, bool, bool]:
        if not is_codex_foreground():
            return False, False, False

        window = self._window(desktop)

        if window is None:
            return False, False, False

        composer = self._find_composer(window)
        available = composer is not None
        ready = False

        if composer is not None:
            name = (
                composer.element_info.name or ""
            ).strip()
            value = (
                composer.get_value() or ""
            ).strip()

            ready = bool(
                value and value != name
            )

        stop_button = self._find_stop_button(
            window
        )

        running = (
            stop_button is not None
            and stop_button.is_enabled()
        )

        return ready, running, available

    def _find_decision_button(
        self,
        window,
        names: set[str],
    ):
        for button in window.descendants(
            control_type="Button"
        ):
            name = (
                button.element_info.name or ""
            ).strip()

            if (
                name in names
                and button.is_enabled()
            ):
                return button

        return None

    def _execute(
        self,
        desktop,
        action: ComposerAction,
    ) -> None:
        if not is_codex_foreground():
            return

        window = self._window(desktop)

        if window is None:
            return

        # 実際のpermission requestを操作する。
        # ボタンがなければ何もしない。
        if action in {
            "approve_request",
            "reject_request",
        }:
            names = (
                APPROVE_BUTTON_NAMES
                if action == "approve_request"
                else REJECT_BUTTON_NAMES
            )

            decision_button = (
                self._find_decision_button(
                    window,
                    names,
                )
            )

            if decision_button is not None:
                decision_button.invoke()

            return


        # idle状態でチャットへ承認・拒否を送る。
        # native approval buttonは操作しない。
        if action in {
            "approve_message",
            "reject_message",
        }:
            if self._find_stop_button(window) is not None:
                return

            composer = self._find_composer(window)

            if composer is None:
                return

            composer_name = (
                composer.element_info.name or ""
            ).strip()

            existing = (
                composer.get_value() or ""
            ).strip()

            # 入力済み内容を上書きしない。
            if existing and existing != composer_name:
                return

            message = (
                "承認"
                if action == "approve_message"
                else "拒否"
            )

            composer.set_edit_text(message)
            time.sleep(0.1)
            composer.set_focus()
            composer.type_keys("{ENTER}")
            return

        if action == "stop":
            button = self._find_stop_button(
                window
            )

            if button is not None:
                button.invoke()

            return

        composer = self._find_composer(window)

        if composer is None:
            return

        value = (
            composer.get_value() or ""
        ).strip()

        if not value:
            return

        if action == "clear":
            composer.set_edit_text("")
            return

        if action == "send":
            composer.set_focus()
            composer.type_keys("{ENTER}")

    def run(self) -> None:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        previous = None

        while not self._stop_event.is_set():
            try:
                while True:
                    action = (
                        self._commands.get_nowait()
                    )
                    self._execute(
                        desktop,
                        action,
                    )
            except queue.Empty:
                pass
            except Exception:
                LOGGER.exception(
                    "Composer action failed"
                )

            try:
                state = self._read_state(desktop)
            except Exception:
                LOGGER.debug(
                    "Could not read composer",
                    exc_info=True,
                )
                state = (False, False, False)

            if state != previous:
                previous = state
                self.events.put(
                    ComposerStateChanged(
                        ready=state[0],
                        running=state[1],
                        available=state[2],
                    )
                )

            self._stop_event.wait(POLL_SECONDS)