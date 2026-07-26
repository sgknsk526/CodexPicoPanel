import queue
import unittest

import serial

from codex_pico_panel.pico_link import PicoLink


class FakeConnection:
    def __init__(self):
        self.attempts = 0
        self.written = bytearray()

    def write(self, payload):
        self.attempts += 1

        if self.attempts == 1:
            raise serial.SerialTimeoutException(
                "busy"
            )

        self.written.extend(payload)
        return len(payload)


class PicoLinkTests(unittest.TestCase):
    def test_transient_write_timeout_is_retried(self):
        link = PicoLink("COM4", queue.Queue())
        connection = FakeConnection()
        link.send(b"\x13")

        link._write_pending(connection)
        link._write_pending(connection)

        self.assertEqual(
            bytes(connection.written),
            b"\x13",
        )
        self.assertIsNone(link._pending_write)


if __name__ == "__main__":
    unittest.main()
