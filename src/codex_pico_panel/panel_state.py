"""Windows-side authoritative state for the Pico's 16 LEDs."""

import threading

from .protocol import (
    KEY_COUNT,
    MAX_LED_STATE,
    encode_full_state,
    encode_statecode,
)


class PanelState:
    """Keep the latest 4-bit state for each LED."""

    def __init__(self, initial: bytes | bytearray | None = None) -> None:
        if initial is None:
            initial = bytes(KEY_COUNT)
        if len(initial) != KEY_COUNT:
            raise ValueError("initial state must contain exactly 16 values")
        if any(state > MAX_LED_STATE for state in initial):
            raise ValueError("each LED state must be 0..15")
        self._lock = threading.Lock()
        self._states = bytearray(initial)

    def set(self, led_index: int, state: int) -> bytes | None:
        """Update one LED and return its one-byte delta, if it changed."""

        if not 0 <= led_index < KEY_COUNT:
            raise ValueError("led_index must be 0..15")
        if not 0 <= state <= MAX_LED_STATE:
            raise ValueError("state must be 0..15")
        with self._lock:
            if self._states[led_index] == state:
                return None
            self._states[led_index] = state
        return encode_statecode(led_index, state)

    def get(self, led_index: int) -> int:
        if not 0 <= led_index < KEY_COUNT:
            raise ValueError("led_index must be 0..15")
        with self._lock:
            return self._states[led_index]

    def snapshot(self) -> bytes:
        with self._lock:
            return bytes(self._states)

    def full_sync_payload(self) -> bytes:
        return encode_full_state(self.snapshot())
