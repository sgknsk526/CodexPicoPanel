import unittest

from codex_pico_panel.codex.hook_event import (
    CodexHookEvent,
)
from codex_pico_panel.task_status import (
    LED_ERROR,
    LED_REGISTERED,
    LED_THINKING,
    LED_UNREAD,
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

    def test_successful_tool_after_failure_marks_turn_successful(
        self,
    ):
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
                event_name="PostToolUse",
                failed=False,
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
            LED_UNREAD,
        )

    def test_successful_tool_clears_explicit_tool_failure(
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
                event_name="PostToolUse",
                failed=False,
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
            LED_UNREAD,
        )

    def test_initial_remote_completion_stays_read(self):
        statuses = TaskStatuses()
        statuses.set_active("other-thread")

        changed = statuses.reconcile_remote(
            "thread-1",
            state="completed",
            turn_id="turn-1",
            failed=False,
            initial=True,
        )

        self.assertTrue(changed)
        self.assertEqual(
            statuses.led_state("thread-1"),
            LED_REGISTERED,
        )

    def test_remote_running_then_completion_is_unread(self):
        statuses = TaskStatuses()
        statuses.set_active("other-thread")
        statuses.reconcile_remote(
            "thread-1",
            state="running",
            turn_id="turn-1",
            failed=False,
            initial=True,
        )

        self.assertEqual(
            statuses.led_state("thread-1"),
            LED_THINKING,
        )

        statuses.reconcile_remote(
            "thread-1",
            state="completed",
            turn_id="turn-1",
            failed=False,
            initial=False,
        )

        self.assertEqual(
            statuses.led_state("thread-1"),
            LED_UNREAD,
        )

    def test_remote_failed_completion_is_error(self):
        statuses = TaskStatuses()
        statuses.set_active("other-thread")
        statuses.reconcile_remote(
            "thread-1",
            state="running",
            turn_id="turn-1",
            failed=False,
            initial=True,
        )
        statuses.reconcile_remote(
            "thread-1",
            state="completed",
            turn_id="turn-1",
            failed=True,
            initial=False,
        )

        self.assertEqual(
            statuses.led_state("thread-1"),
            LED_ERROR,
        )

    def test_remote_running_preserves_same_turn_approval(self):
        statuses = TaskStatuses()
        statuses.apply_hook(
            CodexHookEvent(
                session_id="thread-1",
                event_name="PermissionRequest",
                turn_id="turn-1",
            )
        )

        changed = statuses.reconcile_remote(
            "thread-1",
            state="running",
            turn_id="turn-1",
            failed=False,
            initial=True,
        )

        self.assertFalse(changed)
        self.assertEqual(
            statuses.phase("thread-1"),
            "action_required",
        )


if __name__ == "__main__":
    unittest.main()
