import json
import tempfile
import unittest
from pathlib import Path

from codex_pico_panel.codex.reasoning import (
    ReasoningResolver,
)


def record(
    effort,
    mode,
):
    return {
        "type": "event_msg",
        "payload": {
            "type": "thread_settings_applied",
            "thread_settings": {
                "reasoning_effort": effort,
                "collaboration_mode": {
                    "mode": mode,
                },
            },
        },
    }


class ReasoningResolverTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )
        self.addCleanup(
            self.temporary_directory.cleanup
        )
        self.root = Path(
            self.temporary_directory.name
        )
        self.thread_id = "thread-1"
        self.path = (
            self.root
            / f"rollout-{self.thread_id}.jsonl"
        )
        self.resolver = ReasoningResolver()
        self.resolver.sessions_root = self.root

    def append(self, value, *, newline=True):
        with self.path.open(
            "a",
            encoding="utf-8",
        ) as file:
            file.write(value)

            if newline:
                file.write("\n")

    def test_initial_restore_ignores_invalid_json(self):
        self.append("{invalid")
        self.append(json.dumps(
            record("max", "plan")
        ))

        resolved = self.resolver.resolve_local(
            self.thread_id
        )

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.effort, "max")
        self.assertEqual(
            resolved.collaboration_mode,
            "plan",
        )

    def test_partial_append_and_truncation_are_followed(self):
        self.append(json.dumps(
            record("low", "default")
        ))
        initial = self.resolver.poll_local(
            self.thread_id
        )
        self.assertEqual(initial.effort, "low")

        encoded = json.dumps(
            record("xhigh", "plan")
        )
        split = len(encoded) // 2
        self.append(
            encoded[:split],
            newline=False,
        )
        self.assertIsNone(
            self.resolver.poll_local(
                self.thread_id
            )
        )
        self.append(encoded[split:])
        appended = self.resolver.poll_local(
            self.thread_id
        )
        self.assertEqual(
            appended.effort,
            "xhigh",
        )
        self.assertEqual(
            appended.collaboration_mode,
            "plan",
        )

        self.path.write_text(
            json.dumps(
                record("high", "default")
            )
            + "\n",
            encoding="utf-8",
        )
        truncated = self.resolver.poll_local(
            self.thread_id
        )
        self.assertEqual(truncated.effort, "high")
        self.assertEqual(
            truncated.collaboration_mode,
            "default",
        )


if __name__ == "__main__":
    unittest.main()
