import unittest

from codex_pico_panel.panel_state import PanelState
from codex_pico_panel.protocol import (
    decode_key_mask,
    encode_full_state,
    encode_statecode,
)


class ProtocolTests(unittest.TestCase):
    def test_statecode_is_one_byte_xy(self):
        self.assertEqual(encode_statecode(0xA, 0xB), b"\xAB")

    def test_full_state_contains_one_command_per_led(self):
        states = bytes(range(16))
        self.assertEqual(
            encode_full_state(states),
            bytes(
                [
                0x00,
                0x11,
                0x22,
                0x33,
                0x44,
                0x55,
                0x66,
                0x77,
                0x88,
                0x99,
                0xAA,
                0xBB,
                0xCC,
                0xDD,
                0xEE,
                0xFF,
                ]
            ),
        )

    def test_key_mask_is_little_endian(self):
        self.assertEqual(decode_key_mask(b"\x01\x80"), 0x8001)

    def test_panel_returns_only_changed_delta(self):
        panel = PanelState()
        self.assertEqual(panel.set(3, 5), b"\x35")
        self.assertIsNone(panel.set(3, 5))
        self.assertEqual(panel.get(3), 5)


if __name__ == "__main__":
    unittest.main()
