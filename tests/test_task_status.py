import unittest

from codex_pico_panel.codex.hook_event import (
    CodexHookEvent,
)
from codex_pico_panel.task_status import (
    LED_ERROR,
    TaskStatuses,
)


class TaskStatusesTests(unittest.TestCase):
    def test_post_tool_failure_is_preserved_until_stop(self):
        statuses = TaskStatuses()
        statuses.set_active("other-thread")
        statuses.apply_hook(
            CodexHookEvent(
                session_id="thread-1",
                event_name="UserPromptSubmit",
            )
        )
        statuses.apply_hook(
            CodexHookEvent(
                session_id="thread-1",
                event_name="PostToolUse",
                failed=True,
            )
        )
        statuses.apply_hook(
            CodexHookEvent(
                session_id="thread-1",
                event_name="Stop",
                failed=False,
            )
        )

        self.assertEqual(
            statuses.led_state("thread-1"),
            LED_ERROR,
        )

    def test_explicit_post_tool_failure_is_preserved_until_stop(
        self,
    ):
        statuses = TaskStatuses()
        statuses.set_active("other-thread")
        statuses.apply_hook(
            CodexHookEvent(
                session_id="thread-1",
                event_name="PostToolUseFailure",
            )
        )
        statuses.apply_hook(
            CodexHookEvent(
                session_id="thread-1",
                event_name="Stop",
            )
        )

        self.assertEqual(
            statuses.led_state("thread-1"),
            LED_ERROR,
        )


if __name__ == "__main__":
    unittest.main()
