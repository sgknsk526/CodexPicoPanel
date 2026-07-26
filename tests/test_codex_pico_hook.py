import json
import tempfile
import unittest
from pathlib import Path

from hooks.codex_pico_hook import stop_turn_failed


def response_item(
    turn_id: str,
    exit_code: int,
) -> dict[str, object]:
    return {
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "output": (
                f"Exit code: {exit_code}\n"
                "Wall time: 0.1 seconds\n"
                "Output:\n"
            ),
            "internal_chat_message_metadata_passthrough": {
                "turn_id": turn_id,
            },
        },
    }


class StopTurnFailedTests(unittest.TestCase):
    def run_check(
        self,
        records: list[dict[str, object]],
        turn_id: str = "turn-1",
    ) -> bool:
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "rollout.jsonl"
            transcript.write_text(
                "".join(
                    json.dumps(record) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )

            return stop_turn_failed(
                {
                    "hook_event_name": "Stop",
                    "transcript_path": str(transcript),
                    "turn_id": turn_id,
                }
            )

    def test_later_success_clears_earlier_failure(self):
        failed = self.run_check(
            [
                response_item("turn-1", 1),
                response_item("turn-1", 0),
            ]
        )

        self.assertFalse(failed)

    def test_latest_failure_is_reported(self):
        failed = self.run_check(
            [
                response_item("turn-1", 0),
                response_item("turn-1", 7),
            ]
        )

        self.assertTrue(failed)

    def test_other_turn_does_not_change_latest_result(self):
        failed = self.run_check(
            [
                response_item("turn-1", 7),
                response_item("turn-2", 0),
            ]
        )

        self.assertTrue(failed)


if __name__ == "__main__":
    unittest.main()
