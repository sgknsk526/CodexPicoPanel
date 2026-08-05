import unittest

from codex_pico_panel.codex.composer import (
    ComposerMonitor,
)


class FakeElementInfo:
    def __init__(
        self,
        name: str,
        class_name: str = "",
    ) -> None:
        self.name = name
        self.class_name = class_name


class FakeEdit:
    def __init__(
        self,
        name: str,
        class_name: str = "",
    ) -> None:
        self.element_info = FakeElementInfo(
            name,
            class_name,
        )


class FakeButton(FakeEdit):
    def __init__(
        self,
        name: str,
        *,
        enabled: bool = True,
        visible: bool = True,
    ) -> None:
        super().__init__(name)
        self.enabled = enabled
        self.visible = visible

    def is_enabled(self) -> bool:
        return self.enabled

    def is_visible(self) -> bool:
        return self.visible


class FakeWindow:
    def __init__(
        self,
        edits: list[FakeEdit] | None = None,
        buttons: list[FakeButton] | None = None,
    ) -> None:
        self.edits = edits or []
        self.buttons = buttons or []

    def descendants(self, control_type: str):
        if control_type == "Edit":
            return self.edits
        if control_type == "Button":
            return self.buttons
        raise AssertionError(control_type)


def find(edits: list[FakeEdit]):
    monitor = object.__new__(ComposerMonitor)
    return monitor._find_composer(FakeWindow(edits))


class ComposerMonitorTests(unittest.TestCase):
    def test_finds_current_japanese_composer_name(
        self,
    ) -> None:
        composer = FakeEdit("何でもどうぞ")

        self.assertIs(find([composer]), composer)

    def test_keeps_previous_composer_names(
        self,
    ) -> None:
        old_japanese = FakeEdit("何でもできます")
        english = FakeEdit("Ask anything")

        self.assertIs(find([old_japanese]), old_japanese)
        self.assertIs(find([english]), english)

    def test_falls_back_to_prosemirror_class(
        self,
    ) -> None:
        composer = FakeEdit(
            "A future placeholder",
            "ProseMirror other-class",
        )

        self.assertIs(find([composer]), composer)

    def test_ignores_unrelated_edit(self) -> None:
        unrelated = FakeEdit("URL を入力")

        self.assertIsNone(find([unrelated]))

    def test_finds_current_decision_button_names(
        self,
    ) -> None:
        monitor = object.__new__(ComposerMonitor)
        approve = FakeButton("許可する")
        reject = FakeButton("許可しない")
        window = FakeWindow(
            buttons=[approve, reject]
        )

        from codex_pico_panel.codex.composer import (
            APPROVE_BUTTON_NAMES,
            REJECT_BUTTON_NAMES,
        )

        self.assertIs(
            monitor._find_decision_button(
                window,
                APPROVE_BUTTON_NAMES,
            ),
            approve,
        )
        self.assertIs(
            monitor._find_decision_button(
                window,
                REJECT_BUTTON_NAMES,
            ),
            reject,
        )

    def test_accepts_decision_button_hotkey_suffix(
        self,
    ) -> None:
        monitor = object.__new__(ComposerMonitor)
        approve = FakeButton("今回のみ許可 (Enter)")
        window = FakeWindow(buttons=[approve])

        from codex_pico_panel.codex.composer import (
            APPROVE_BUTTON_NAMES,
        )

        self.assertIs(
            monitor._find_decision_button(
                window,
                APPROVE_BUTTON_NAMES,
            ),
            approve,
        )

    def test_does_not_click_request_approval_control(
        self,
    ) -> None:
        monitor = object.__new__(ComposerMonitor)
        request = FakeButton("承認を依頼")
        window = FakeWindow(buttons=[request])

        from codex_pico_panel.codex.composer import (
            APPROVE_BUTTON_NAMES,
        )

        self.assertIsNone(
            monitor._find_decision_button(
                window,
                APPROVE_BUTTON_NAMES,
            )
        )
