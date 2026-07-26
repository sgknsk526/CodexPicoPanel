import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_pico_panel.controller import Controller
from codex_pico_panel.panel_state import PanelState
from codex_pico_panel.pico_link import PicoConnected, PicoKeyMask
from codex_pico_panel.runtime import RuntimeState
from codex_pico_panel.task_slots import TaskSlots
from codex_pico_panel.task_status import TaskStatuses


class FakePico:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)


class FakeShortcuts:
    def __init__(self):
        self.events = []
        self.activations = 0

    def handle_key(self, key_number, action):
        self.events.append((key_number, action))

    def activate_codex(self):
        self.activations += 1
        return True

    def release_all(self):
        pass


class FakeDesktopLog:
    def current(self):
        return None

    def latest_approval_response(self):
        return None


class FakeComposer:
    def perform(self, _action):
        pass


class FakeReasoning:
    def resolve_async(self, *_args, **_kwargs):
        return True

    def poll_local(self, _conversation_id):
        return None

    def tracks_local(self, _conversation_id):
        return False


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.foreground = patch(
            "codex_pico_panel.controller.is_codex_foreground",
            return_value=False,
        )
        self.foreground.start()
        self.addCleanup(self.foreground.stop)

        self.pico = FakePico()
        self.panel = PanelState()
        self.runtime = RuntimeState()
        self.shortcuts = FakeShortcuts()
        self.controller = Controller(
            queue.Queue(),
            self.pico,
            self.panel,
            self.runtime,
            self.shortcuts,
            TaskSlots(
                Path(self.temporary_directory.name)
                / "slots.json"
            ),
            FakeDesktopLog(),
            TaskStatuses(),
            FakeComposer(),
            FakeReasoning(),
        )

    def test_connect_sends_one_full_state(self):
        self.controller.handle_event(
            PicoConnected("COM4")
        )

        runtime = self.runtime.snapshot()
        self.assertTrue(runtime.pico_connected)
        self.assertEqual(runtime.pico_port, "COM4")
        self.assertEqual(runtime.connect_count, 1)
        self.assertEqual(
            self.pico.sent,
            [bytes(index << 4 for index in range(16))],
        )

    def test_key_mask_produces_zero_based_edges_only(self):
        with patch(
            "codex_pico_panel.controller.is_codex_foreground",
            return_value=True,
        ):
            self.controller.handle_event(
                PicoKeyMask(0x8001)
            )
            self.controller.handle_event(
                PicoKeyMask(0x8001)
            )
            self.controller.handle_event(
                PicoKeyMask(0x0000)
            )

        self.assertEqual(
            self.shortcuts.events,
            [
                (0x0, "press"),
                (0xF, "press"),
                (0x0, "release"),
                (0xF, "release"),
            ],
        )
        self.assertEqual(
            self.shortcuts.activations,
            1,
        )

    def test_keepalive_reuses_current_led_zero_state(self):
        self.controller.handle_event(
            PicoConnected("COM4")
        )
        self.pico.sent.clear()

        self.controller._poll_pico_keepalive()

        self.assertEqual(
            self.pico.sent,
            [b"\x00"],
        )


if __name__ == "__main__":
    unittest.main()
