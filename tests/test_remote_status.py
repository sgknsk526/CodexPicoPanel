import json
import unittest

from codex_pico_panel.codex.remote_status import (
    parse_probe_output,
)


class RemoteStatusProbeTests(unittest.TestCase):
    def test_valid_snapshots_are_parsed(self):
        output = json.dumps({
            "snapshots": [
                {
                    "conversation_id": "thread-1",
                    "state": "running",
                    "turn_id": "turn-1",
                    "failed": False,
                    "timestamp": "2026-07-27T00:00:00Z",
                },
                {
                    "conversation_id": "thread-2",
                    "state": "completed",
                    "turn_id": "turn-2",
                    "failed": True,
                    "timestamp": None,
                },
            ],
        })

        snapshots = parse_probe_output(output)

        self.assertEqual(len(snapshots), 2)
        self.assertEqual(
            snapshots[0].conversation_id,
            "thread-1",
        )
        self.assertEqual(snapshots[0].state, "running")
        self.assertTrue(snapshots[1].failed)

    def test_invalid_snapshot_is_ignored(self):
        output = json.dumps({
            "snapshots": [
                {
                    "conversation_id": "thread-1",
                    "state": "unknown",
                    "turn_id": "turn-1",
                    "failed": False,
                    "timestamp": None,
                },
            ],
        })

        self.assertEqual(parse_probe_output(output), ())

    def test_invalid_output_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_probe_output("not-json")


if __name__ == "__main__":
    unittest.main()
