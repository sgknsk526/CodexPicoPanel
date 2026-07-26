import unittest

from codex_pico_panel.codex.hook_event import (
    CodexHookEvent,
)


class HookEventTests(unittest.TestCase):
    def test_payload_must_be_an_object(self):
        with self.assertRaisesRegex(
            ValueError,
            "must be an object",
        ):
            CodexHookEvent.from_payload([])

    def test_collaboration_mode_is_validated(self):
        event = CodexHookEvent.from_payload({
            "session_id": "thread-1",
            "hook_event_name": "Stop",
            "failed": False,
            "collaboration_mode": "plan",
        })
        self.assertEqual(
            event.collaboration_mode,
            "plan",
        )


if __name__ == "__main__":
    unittest.main()
