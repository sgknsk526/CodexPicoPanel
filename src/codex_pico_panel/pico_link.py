"""Persistent binary USB CDC link to the Pico."""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import TypeAlias

import serial

from .protocol import KEY_MASK_BYTES, decode_key_mask


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PicoConnected:
    port: str


@dataclass(frozen=True)
class PicoDisconnected:
    port: str
    reason: str | None = None


@dataclass(frozen=True)
class PicoKeyMask:
    key_mask: int


@dataclass(frozen=True)
class PicoError:
    message: str


PicoEvent: TypeAlias = PicoConnected | PicoDisconnected | PicoKeyMask | PicoError


class PicoLink(threading.Thread):
    """Own the serial port and exchange only raw binary protocol frames."""

    def __init__(
        self,
        port: str,
        events: queue.Queue[PicoEvent],
        *,
        reconnect_seconds: float = 1.0,
    ) -> None:
        super().__init__(name="pico-link", daemon=True)
        self.port = port
        self.reconnect_seconds = reconnect_seconds
        self.events = events
        self._outgoing: queue.Queue[bytes] = queue.Queue()
        self._stop_event = threading.Event()
        self._pending_write: bytes | None = None

    def send(self, payload: bytes) -> None:
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        if payload:
            self._outgoing.put(payload)

    def stop(self) -> None:
        self._stop_event.set()

    def _discard_outgoing(self) -> None:
        self._pending_write = None

        while True:
            try:
                self._outgoing.get_nowait()
            except queue.Empty:
                return

    def _write_pending(self, connection: serial.Serial) -> None:
        if self._pending_write is None:
            try:
                self._pending_write = (
                    self._outgoing.get_nowait()
                )
            except queue.Empty:
                return

        payload = self._pending_write

        try:
            written = connection.write(payload)
        except serial.SerialTimeoutException:
            # USB CDCの一時的なbackpressureではCOMポートを閉じない。
            # statecodeは冪等なので、次のloopで同じpayloadを再試行できる。
            LOGGER.debug(
                "Pico write timed out; retrying"
            )
            return

        if not 0 <= written <= len(payload):
            raise serial.SerialException(
                "Pico write returned an invalid length"
            )

        if written == len(payload):
            self._pending_write = None
        elif written > 0:
            self._pending_write = payload[written:]

    def _run_connection(self, connection: serial.Serial) -> None:
        receive_buffer = bytearray()

        while not self._stop_event.is_set():
            self._write_pending(connection)

            chunk = connection.read(64)
            if chunk:
                receive_buffer.extend(chunk)

            while len(receive_buffer) >= KEY_MASK_BYTES:
                raw = bytes(receive_buffer[:KEY_MASK_BYTES])
                del receive_buffer[:KEY_MASK_BYTES]
                self.events.put(PicoKeyMask(decode_key_mask(raw)))

    def run(self) -> None:
        while not self._stop_event.is_set():
            connected = False
            disconnect_reason = None
            try:
                LOGGER.info("Opening Pico CDC data port %s", self.port)
                with serial.Serial(
                    port=self.port,
                    baudrate=115200,
                    timeout=0.05,
                    write_timeout=0.2,
                ) as connection:
                    connected = True
                    # Deltas queued while disconnected are stale. The
                    # controller sends one authoritative 16-byte full sync.
                    self._discard_outgoing()
                    self.events.put(PicoConnected(self.port))
                    self._run_connection(connection)

            except Exception as error:
                if not self._stop_event.is_set():
                    message = (
                        f"{type(error).__name__}: {error}"
                    )
                    disconnect_reason = message
                    LOGGER.warning(
                        "Pico connection failed on %s: %s",
                        self.port,
                        message,
                    )
                    self.events.put(PicoError(message))
            finally:
                if (
                    connected
                    and not self._stop_event.is_set()
                ):
                    self.events.put(
                        PicoDisconnected(
                            self.port,
                            disconnect_reason,
                        )
                    )

            self._stop_event.wait(self.reconnect_seconds)
