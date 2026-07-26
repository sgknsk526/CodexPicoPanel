import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_pico_panel.task_slots import TaskSlots


class TaskSlotsTests(unittest.TestCase):
    def test_failed_save_does_not_mutate_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            slots = TaskSlots(
                Path(directory) / "slots.json"
            )

            with patch.object(
                slots,
                "_save",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaises(OSError):
                    slots.register(1, "thread-1")

            self.assertFalse(
                slots.is_registered(1)
            )


if __name__ == "__main__":
    unittest.main()
