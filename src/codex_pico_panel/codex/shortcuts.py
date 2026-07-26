"""Whitelisted Windows shortcuts for Codex Desktop."""

from __future__ import annotations

import ctypes
import logging
import os
import time
from typing import Literal

from .window import is_codex_foreground


LOGGER = logging.getLogger(__name__)
KeyAction = Literal["press", "release"]

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_0 = 0x30
VK_F = 0x46
VK_W = 0x57
VK_X = 0x58
KEYEVENTF_KEYUP = 0x0002
CODEX_ACTIVATION_TIMEOUT_SECONDS = 3.0
CODEX_ACTIVATION_POLL_SECONDS = 0.05
STATUS_PAGE_URL = "http://127.0.0.1:48973/"

user32 = ctypes.WinDLL("user32", use_last_error=True)

class CodexShortcuts:
    """Emit only the fixed chords used by the panel."""

    def __init__(
        self,
        status_page_url: str = STATUS_PAGE_URL,
    ) -> None:
        self._voice_input_held = False
        self.status_page_url = status_page_url

    def open_status_page(self) -> bool:
        try:
            os.startfile(self.status_page_url)
        except OSError:
            LOGGER.exception("Could not open status page")
            return False

        LOGGER.info("Opened status page")
        return True

    def wait_until_codex_foreground(
        self,
        timeout: float = (
            CODEX_ACTIVATION_TIMEOUT_SECONDS
        ),
    ) -> bool:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if is_codex_foreground():
                return True

            time.sleep(
                CODEX_ACTIVATION_POLL_SECONDS
            )

        return False

    def handle_key(
        self,
        key_number: int,
        action: KeyAction,
    ) -> None:
        if key_number == 8:
            if action == "press":
                self.set_voice_input_held(True)

            elif action == "release":
                self.set_voice_input_held(False)

        elif key_number == 0xB:
            if action == "release":
                self.open_status_page()

            return

        elif key_number == 0xE:
            if action == "release":
                self.cycle_reasoning_effort()
            return

        elif key_number == 0xF:
            if action == "release":
                self.toggle_plan_mode()
            return

        return

    def cycle_reasoning_effort(self) -> bool:
        if not is_codex_foreground():
            return False

        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_SHIFT, 0, 0, 0)

        try:
            user32.keybd_event(VK_W, 0, 0, 0)
            time.sleep(0.03)
            user32.keybd_event(
                VK_W, 0, KEYEVENTF_KEYUP, 0
            )
        finally:
            user32.keybd_event(
                VK_SHIFT, 0, KEYEVENTF_KEYUP, 0
            )
            user32.keybd_event(
                VK_CONTROL, 0, KEYEVENTF_KEYUP, 0
            )

        LOGGER.info("Sent Ctrl+Shift+W")
        return True

    def set_voice_input_held(
        self,
        held: bool,
    ) -> None:
        # 重複press/releaseを無視する
        if held == self._voice_input_held:
            return

        if held:
            # 修飾キーから順に押す
            user32.keybd_event(
                VK_CONTROL, 0, 0, 0
            )
            user32.keybd_event(
                VK_SHIFT, 0, 0, 0
            )
            user32.keybd_event(
                VK_F, 0, 0, 0
            )

            self._voice_input_held = True
            LOGGER.info(
                "Voice input hotkey held"
            )
            return

        # 通常キーから逆順に離す
        user32.keybd_event(
            VK_F, 0, KEYEVENTF_KEYUP, 0
        )
        user32.keybd_event(
            VK_SHIFT, 0, KEYEVENTF_KEYUP, 0
        )
        user32.keybd_event(
            VK_CONTROL, 0, KEYEVENTF_KEYUP, 0
        )

        self._voice_input_held = False
        LOGGER.info(
            "Voice input hotkey released"
        )

    def release_all(self) -> None:
        self.set_voice_input_held(False)

    def activate_codex(self) -> bool:
        """Codexを起動、または既存インスタンスへURIを渡す。"""

        try:
            os.startfile("codex://")
        except OSError:
            LOGGER.exception("Could not activate Codex Desktop")
            return False

        LOGGER.info("Requested Codex Desktop activation")
        return True

    def open_pinned_task(self, task_number: int) -> bool:
        if not 1 <= task_number <= 7:
            raise ValueError("task_number must be 1..7")

        # 別アプリへCtrl+数字を誤送信しない
        if not is_codex_foreground():
            LOGGER.info(
                "Activating Codex before Ctrl+%d",
                task_number,
            )

            if not self.activate_codex():
                return False

            if not self.wait_until_codex_foreground():
                LOGGER.warning(
                    "Codex did not become foreground "
                    "before Ctrl+%d",
                    task_number,
                )
                return False

        digit_key = VK_0 + task_number

        # Ctrlを押す
        user32.keybd_event(VK_CONTROL, 0, 0, 0)

        try:
            # 数字を押して離す
            user32.keybd_event(digit_key, 0, 0, 0)
            time.sleep(0.03)
            user32.keybd_event(
                digit_key,
                0,
                KEYEVENTF_KEYUP,
                0,
            )
        finally:
            # Ctrlは必ず離す
            user32.keybd_event(
                VK_CONTROL,
                0,
                KEYEVENTF_KEYUP,
                0,
            )

        LOGGER.info("Sent Ctrl+%d", task_number)
        return True

    def toggle_plan_mode(self) -> bool:
        if not is_codex_foreground():
            return False

        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_SHIFT, 0, 0, 0)

        try:
            user32.keybd_event(VK_X, 0, 0, 0)
            time.sleep(0.03)
            user32.keybd_event(
                VK_X, 0, KEYEVENTF_KEYUP, 0
            )
        finally:
            user32.keybd_event(
                VK_SHIFT, 0, KEYEVENTF_KEYUP, 0
            )
            user32.keybd_event(
                VK_CONTROL, 0, KEYEVENTF_KEYUP, 0
            )

        LOGGER.info("Sent Ctrl+Shift+X")
        return True
