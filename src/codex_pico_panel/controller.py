"""Single-owner controller for Pico events, panel state, and actions."""

from __future__ import annotations

import logging
import queue
import time
import threading

from .codex.composer import (
    ComposerMonitor,
    ComposerStateChanged,
)
from .codex.desktop_log import CodexDesktopLog
from .codex.hook_event import CodexHookEvent
from .codex.reasoning import (
    ReasoningResolved,
    ReasoningResolver,
)
from .codex.remote_status import (
    RemoteStatusesResolved,
    RemoteStatusResolver,
)
from .codex.shortcuts import CodexShortcuts
from .codex.window import is_codex_foreground
from .task_slots import TaskSlots
from .task_status import TaskStatuses
from .panel_state import PanelState
from .pico_link import (
    PicoConnected,
    PicoDisconnected,
    PicoError,
    PicoKeyMask,
    PicoLink,
)
from .protocol import KEY_COUNT
from .runtime import RuntimeState



FOREGROUND_POLL_SECONDS = 0.1
REASONING_POLL_SECONDS = 0.1
REMOTE_SETTINGS_POLL_SECONDS = 5.0
REMOTE_STATUS_POLL_SECONDS = 5.0
PICO_KEEPALIVE_SECONDS = 2.0
LOGGER = logging.getLogger(__name__)
SHORT_PRESS_SECONDS = 2.0

REGISTER_HOLD_SECONDS = 1.0
COMPOSER_HOLD_SECONDS = 0.4
LED_OFF = 0x0
LED_RUNNING = 0x1
LED_SEND_READY = 0x3
LED_APPROVE = 0x3  # 緑
LED_YELLOW = 0x5
LED_CLEAR_READY = 0x6
LED_REJECT = 0x7   # 通常赤
LED_WHITE = 0xD
ACTIVE_TASK_POLL_SECONDS = 0.1

CODEX_FOREGROUND_ONLY_KEYS = frozenset({
    0x8,
    0x9,
    0xA,
    0xC,
    0xD,
    0xE,
    0xF,
})

REASONING_LED_STATES = {
    "low":    0xC,  # 灰
    "medium": 0x3,  # 緑
    "high":   0x2,  # 水色
    "xhigh":  0x1,  # 青
    "max":    0x6,  # オレンジ
    "ultra":  0x7,  # 赤
}


class Controller:
    def __init__(
        self,
        events: queue.Queue[object],
        pico: PicoLink,
        panel: PanelState,
        runtime: RuntimeState,
        shortcuts: CodexShortcuts,
        slots: TaskSlots,
        desktop_log: CodexDesktopLog,
        statuses: TaskStatuses,
        composer: ComposerMonitor,
        reasoning: ReasoningResolver,
        remote_status: (
            RemoteStatusResolver | None
        ) = None,
    ) -> None:
        self.events = events
        self.pico = pico
        self.panel = panel
        self.runtime = runtime
        self.shortcuts = shortcuts
        self._previous_key_mask = 0
        self._stop_event = threading.Event()
        self._pressed_at = [None] * KEY_COUNT
        self._codex_foreground = None
        self._next_foreground_check = 0.0
        self.slots = slots
        self.desktop_log = desktop_log
        self.statuses = statuses
        self._active_task_token = None
        self._next_active_task_check = 0.0
        self._suppressed_keys = [False] * KEY_COUNT
        self.composer = composer
        self._composer_ready = False
        self._composer_running = False
        self._composer_available = False
        self._armed_composer_actions = (
            [None] * KEY_COUNT
        )
        self.reasoning = reasoning
        self.remote_status = remote_status
        self._active_conversation_id = None
        self._next_reasoning_check = 0.0
        self._next_remote_settings_check = 0.0
        self._next_remote_status_check = 0.0
        self._next_pico_keepalive = 0.0

        for conversation_id in self.slots.snapshot().values():
            self.statuses.ensure(conversation_id)

        for slot in range(1, 8):
            conversation_id = self.slots.get(slot)

            if conversation_id is None:
                state = LED_OFF
            else:
                state = self.statuses.led_state(
                    conversation_id
                )

            self.panel.set(slot, state)

        approval = (
            self.desktop_log.latest_approval_response()
        )

        self._approval_response_token = (
            approval.token
            if approval is not None
            else None
        )

    def stop(self) -> None:
        self.shortcuts.release_all()
        self._stop_event.set()

    def set_led(self, led_index: int, state: int) -> None:
        """Update Windows state and send only the one-byte delta."""

        payload = self.panel.set(led_index, state)
        if payload is not None:
            self.pico.send(payload)

    def _handle_key_mask(self, current_mask: int) -> None:
        current_mask &= 0xFFFF
        pressed_mask = current_mask & ~self._previous_key_mask
        released_mask = self._previous_key_mask & ~current_mask
        self.runtime.update(key_mask=current_mask)

        self._previous_key_mask = current_mask

        for key_index in range(KEY_COUNT):
            bit = 1 << key_index

            if pressed_mask & bit:
                LOGGER.info("Key %X pressed", key_index)
                self._handle_key_edge(key_index, "press")

            if released_mask & bit:
                LOGGER.info("Key %X released", key_index)
                self._handle_key_edge(key_index, "release")

    def _decision_mode(self) -> str | None:
        if not is_codex_foreground():
            return None

        conversation_id = (
            self._active_conversation_id
        )

        if conversation_id is None:
            return None

        phase = self.statuses.phase(
            conversation_id
        )

        # permission request中
        if phase == "action_required":
            return "request"

        # idle時の文字送信
        if (
            phase == "idle"
            and self._composer_available
            and not self._composer_ready
            and not self._composer_running
        ):
            return "message"

        return None


    def _refresh_decision_leds(self) -> None:
        enabled = self._decision_mode() is not None

        self.set_led(
            0xC,
            LED_APPROVE if enabled else LED_OFF,
        )
        self.set_led(
            0xD,
            LED_REJECT if enabled else LED_OFF,
        )

    def _handle_key_edge(
        self,
        key_index,
        action,
    ):
        now = time.monotonic()

        if action == "press":
            # Codex非最前で始まった操作を抑止
            if (
                key_index
                in CODEX_FOREGROUND_ONLY_KEYS
                and not is_codex_foreground()
            ):
                self._suppressed_keys[
                    key_index
                ] = True
                self._pressed_at[key_index] = None

                LOGGER.info(
                    "Ignored key %X because "
                    "Codex is not foreground",
                    key_index,
                )
                return

            self._suppressed_keys[
                key_index
            ] = False
            self._pressed_at[key_index] = now

            if key_index == 0x9:
                if self._composer_running:
                    self._armed_composer_actions[
                        key_index
                    ] = "stop"
                elif self._composer_ready:
                    self._armed_composer_actions[
                        key_index
                    ] = "send"

            elif (
                key_index == 0xA
                and self._composer_ready
            ):
                self._armed_composer_actions[
                    key_index
                ] = "clear"

            elif key_index in (0xC, 0xD):
                mode = self._decision_mode()

                self._armed_composer_actions[
                    key_index
                ] = None

                if mode == "request":
                    self._armed_composer_actions[
                        key_index
                    ] = (
                        "approve_request"
                        if key_index == 0xC
                        else "reject_request"
                    )

                elif mode == "message":
                    self._armed_composer_actions[
                        key_index
                    ] = (
                        "approve_message"
                        if key_index == 0xC
                        else "reject_message"
                    )

            if key_index in (0x8, 0xB):
                self.set_led(key_index, 0x5)  # 黄色

            self.shortcuts.handle_key(
                key_index,
                action,
            )
            return

        if action == "release":
            # 非最前で始まったpressに対応するrelease
            if self._suppressed_keys[key_index]:
                self._suppressed_keys[
                    key_index
                ] = False
                self._pressed_at[key_index] = None
                return

            armed_action = (
                self._armed_composer_actions[
                    key_index
                ]
            )
            self._armed_composer_actions[
                key_index
            ] = None

            pressed_at = self._pressed_at[
                key_index
            ]
            self._pressed_at[key_index] = None

            if key_index == 0x8:
                state = (
                    LED_WHITE
                    if is_codex_foreground()
                    else LED_OFF
                )
                self.set_led(0x8, state)

            elif key_index == 0xB:
                self.set_led(0xB, LED_OFF)

            self.shortcuts.handle_key(
                key_index,
                action,
            )

            if pressed_at is None:
                return

            duration = now - pressed_at


        # Key 0：2秒以内のreleaseでCodex起動・前面化
        if key_index == 0:
            if duration <= SHORT_PRESS_SECONDS:
                self.shortcuts.activate_codex()
            return

        if key_index in (
            0x9,
            0xA,
            0xC,
            0xD,
        ):
            if (
                duration < COMPOSER_HOLD_SECONDS
                or armed_action is None
                or not is_codex_foreground()
            ):
                return

            if key_index in (0xC, 0xD):
                current_mode = (
                    self._decision_mode()
                )

                armed_mode = (
                    "request"
                    if armed_action.endswith(
                        "_request"
                    )
                    else "message"
                )

                # 長押し中にtask状態や
                # 入力内容が変わったら中止
                if current_mode != armed_mode:
                    LOGGER.info(
                        "Cancelled decision: "
                        "mode changed %s -> %s",
                        armed_mode,
                        current_mode,
                    )
                    self._refresh_decision_leds()
                    return

            self.composer.perform(armed_action)
            return

        # Key 1～7：releaseでCtrl+1～7
        if 1 <= key_index <= 7:
            # 登録済み・未登録を問わず、長押しは登録状態の反転。
            if duration >= REGISTER_HOLD_SECONDS:
                self._toggle_task_registration(key_index)
                return

            # 登録済みの短押しは開くだけ。
            if self.slots.is_registered(key_index):
                self.shortcuts.open_pinned_task(key_index)
                return

            # 消灯中の短押し。
            # 新しいactiveイベントが確認できた場合だけ自動登録。
            self._register_from_pinned_task(
                key_index,
                fallback_to_current=False,
            )
            return

        if key_index in (0xE, 0xF):
            conversation_id = (
                self._active_conversation_id
            )

            if conversation_id is not None:
                if (
                    key_index == 0xF
                    and is_codex_foreground()
                ):
                    self.set_led(0xF, 0xC)

                self.reasoning.resolve_async(
                    conversation_id,
                    self.events,
                    delay=0.3,
                )

            return

    def handle_event(self, event: object) -> None:
        if isinstance(
            event,
            ComposerStateChanged,
        ):
            self._composer_ready = event.ready
            self._composer_running = event.running
            self._composer_available = event.available

            if event.running:
                key_9_state = LED_RUNNING
            elif event.ready:
                key_9_state = LED_SEND_READY
            else:
                key_9_state = LED_OFF

            self.set_led(0x9, key_9_state)

            self.set_led(
                0xA,
                LED_CLEAR_READY
                if event.ready
                else LED_OFF,
            )
            self._refresh_decision_leds()
            return

        if isinstance(event, CodexHookEvent):
            self._handle_codex_hook(event)
            self._refresh_decision_leds()
            if (
                event.reasoning_effort is not None
                and event.session_id
                == self._active_conversation_id
                and is_codex_foreground()
            ):
                self.set_led(
                    0xE,
                    self._reasoning_led_state(),
                )

            if (
                event.collaboration_mode is not None
                and event.session_id
                == self._active_conversation_id
                and is_codex_foreground()
            ):
                self.set_led(
                    0xF,
                    self._plan_led_state(),
                )
            return

        if isinstance(event, ReasoningResolved):
            settings_changed = (
                self.statuses.update_settings(
                    event.conversation_id,
                    effort=event.effort,
                    collaboration_mode=(
                        event.collaboration_mode
                    ),
                    source=event.source,
                )
            )

            log = (
                LOGGER.info
                if settings_changed
                else LOGGER.debug
            )
            log(
                "Settings for %s: effort=%s "
                "mode=%s (%s)",
                event.conversation_id,
                event.effort,
                event.collaboration_mode,
                event.source,
            )

            if (
                event.conversation_id
                == self._active_conversation_id
                and is_codex_foreground()
            ):
                if event.effort is not None:
                    self.set_led(
                        0xE,
                        self._reasoning_led_state(),
                    )

                if event.collaboration_mode is not None:
                    self.set_led(
                        0xF,
                        self._plan_led_state(),
                    )

            return

        if isinstance(event, RemoteStatusesResolved):
            changed = False

            for snapshot in event.snapshots:
                snapshot_changed = (
                    self.statuses.reconcile_remote(
                        snapshot.conversation_id,
                        state=snapshot.state,
                        turn_id=snapshot.turn_id,
                        failed=snapshot.failed,
                        initial=(
                            snapshot.conversation_id
                            in event.initial_ids
                        ),
                    )
                )

                if snapshot_changed:
                    LOGGER.info(
                        "Remote rollout state for %s: "
                        "%s turn=%s failed=%s",
                        snapshot.conversation_id,
                        snapshot.state,
                        snapshot.turn_id,
                        snapshot.failed,
                    )

                changed = snapshot_changed or changed

            if changed:
                self._refresh_task_leds()

            return

        if isinstance(event, PicoConnected):
            LOGGER.info("Pico connected on %s", event.port)
            self.runtime.record_connection(event.port)
            self._previous_key_mask = 0

            current = is_codex_foreground()
            self._codex_foreground = current

            active = self.desktop_log.current()

            if active is not None:
                self._active_conversation_id = (
                    active.conversation_id
                )
                self._active_task_token = active.token

                self.statuses.set_active(
                    active.conversation_id
                )

                self.reasoning.resolve_async(
                    active.conversation_id,
                    self.events,
                )

            self.panel.set(
                0x0,
                0x1 if current else LED_OFF,
            )
            self.panel.set(
                0x8,
                LED_WHITE if current else LED_OFF,
            )
            decisions_enabled = (
                self._decision_mode() is not None
            )
            self.panel.set(
                0xC,
                (
                    LED_APPROVE
                    if decisions_enabled
                    else LED_OFF
                ),
            )
            self.panel.set(
                0xD,
                (
                    LED_REJECT
                    if decisions_enabled
                    else LED_OFF
                ),
            )
            self.panel.set(
                0xE,
                (
                    self._reasoning_led_state()
                    if current
                    else LED_OFF
                ),
            )
            self.panel.set(
                0xF,
                (
                    self._plan_led_state()
                    if current
                    else LED_OFF
                ),
            )

            self.pico.send(
                self.panel.full_sync_payload()
            )
            return

        if isinstance(event, PicoDisconnected):
            self.shortcuts.release_all()
            LOGGER.warning(
                "Pico disconnected from %s: %s",
                event.port,
                event.reason or "unknown reason",
            )

            self.runtime.record_disconnect(
                event.reason
            )

            self.panel.set(0x8, LED_OFF)
            self.panel.set(0xB, LED_OFF)
            self.panel.set(0xC, LED_OFF)
            self.panel.set(0xD, LED_OFF)
            self.panel.set(0xE, LED_OFF)
            self.panel.set(0xF, LED_OFF)

            self._previous_key_mask = 0
            self._pressed_at = [None] * KEY_COUNT
            self._suppressed_keys = [False] * KEY_COUNT
            self._armed_composer_actions = (
                [None] * KEY_COUNT
            )
            return

        if isinstance(event, PicoKeyMask):
            self._handle_key_mask(event.key_mask)
            return

        if isinstance(event, PicoError):
            self.runtime.update(last_error=event.message)

    def _poll_codex_foreground(self):
        now = time.monotonic()

        if now < self._next_foreground_check:
            return

        self._next_foreground_check = (
            now + FOREGROUND_POLL_SECONDS
        )

        current = is_codex_foreground()

        # No foreground change.
        if current == self._codex_foreground:
            return

        self._codex_foreground = current

        if current:
            LOGGER.info("Codex became foreground")
            self.set_led(0x0, 0x1)

            key_8_held = (
                self._pressed_at[0x8] is not None
            )

            self.set_led(
                0x8,
                LED_YELLOW
                if key_8_held
                else LED_WHITE,
            )
            self._refresh_decision_leds()

            self.set_led(
                0xE,
                self._reasoning_led_state(),
            )
            self.set_led(
                0xF,
                self._plan_led_state(),
            )

        else:
            LOGGER.info("Codex left foreground")
            self.set_led(0x0, LED_OFF)
            self.set_led(0x8, LED_OFF)
            self.set_led(0xC, LED_OFF)
            self.set_led(0xD, LED_OFF)
            self.set_led(0xE, LED_OFF)
            self.set_led(0xF, LED_OFF)

    def _register_from_pinned_task(
        self,
        slot: int,
        *,
        fallback_to_current: bool,
    ) -> bool:
        previous = self.desktop_log.current()

        # Codexが前面でなければ既存実装ではFalseになる。
        if not self.shortcuts.open_pinned_task(slot):
            LOGGER.info(
                "Could not open pinned task %d",
                slot,
            )
            return False

        active = self.desktop_log.wait_after(
            previous,
            timeout=1.0,
            fallback_to_previous=fallback_to_current,
        )

        if active is None:
            LOGGER.info(
                "Could not detect a new conversation "
                "for slot %d; leaving it unregistered",
                slot,
            )
            return False

        try:
            self.slots.register(
                slot,
                active.conversation_id,
            )
        except OSError as error:
            LOGGER.exception(
                "Could not save slot %d",
                slot,
            )
            self.runtime.update(
                last_error=str(error),
            )
            return False

        # 新しく登録したconversationを状態管理へ追加する。
        self.statuses.ensure(
            active.conversation_id
        )

        # TaskStatusesの状態からLEDを再計算する。
        # 新規登録なので、この時点では白になる。
        self._refresh_task_leds()
        self._refresh_decision_leds()

        self.runtime.update(last_error=None)

        LOGGER.info(
            "Registered slot %d to conversation %s",
            slot,
            active.conversation_id,
        )

        return True

    def _poll_approval_response(self) -> None:
        response = (
            self.desktop_log.latest_approval_response()
        )

        if response is None:
            return

        if (
            response.token
            == self._approval_response_token
        ):
            return

        self._approval_response_token = response.token

        conversation_id = (
            self.statuses.resolve_approval()
        )

        if conversation_id is None:
            return

        self._refresh_task_leds()
        self._refresh_decision_leds()

        LOGGER.info(
            "Approval resolved for %s: %s",
            conversation_id,
            response.decision,
        )

    def _toggle_task_registration(
        self,
        slot: int,
    ) -> None:
        # 点灯中の長押しは登録解除。
        if self.slots.is_registered(slot):
            try:
                self.slots.unregister(slot)
            except OSError as error:
                LOGGER.exception(
                    "Could not unregister slot %d",
                    slot,
                )
                self.runtime.update(
                    last_error=str(error),
                )
                return

            self.set_led(slot, LED_OFF)

            LOGGER.info(
                "Unregistered slot %d",
                slot,
            )
            return

        # 消灯中の長押しは明示的な登録。
        # すでに対象タスクが表示中で新しいactiveイベントが
        # 出なくても、現在のタスクへフォールバックする。
        self._register_from_pinned_task(
            slot,
            fallback_to_current=True,
        )

    def _refresh_task_leds(self) -> None:
        for slot in range(1, 8):
            conversation_id = self.slots.get(slot)

            if conversation_id is None:
                self.set_led(slot, 0x0)
                continue

            self.set_led(
                slot,
                self.statuses.led_state(
                    conversation_id
                ),
            )

    def _handle_codex_hook(
        self,
        event: CodexHookEvent,
    ) -> None:
        self.statuses.apply_hook(event)

        slot = (
            self.slots.find_slot_by_conversation_id(
                event.session_id
            )
        )

        if slot is None:
            LOGGER.debug(
                "Received hook for unregistered task %s",
                event.session_id,
            )
            return

        self._refresh_task_leds()

        LOGGER.info(
            "Task %d received %s",
            slot,
            event.event_name,
        )

    def _poll_active_task(self) -> None:
        now = time.monotonic()

        if now < self._next_active_task_check:
            return

        self._next_active_task_check = (
            now + ACTIVE_TASK_POLL_SECONDS
        )

        active = self.desktop_log.current()

        # Codex未起動・表示タスク不明
        if active is None:
            return

        # 新しいactiveイベントがなければ終了
        if active.token == self._active_task_token:
            return

        previous_conversation_id = (
            self._active_conversation_id
        )

        self._active_task_token = active.token
        self._active_conversation_id = (
            active.conversation_id
        )

        self.statuses.set_active(
            active.conversation_id
        )

        self._refresh_task_leds()
        self._refresh_decision_leds()

        # 別チャットへ切り替わったとき、
        # local rolloutまたはremote SSHから推論値を読む
        if (
            active.conversation_id
            != previous_conversation_id
        ):
            # 推論レベル照会中
            self.set_led(
                0xE,
                (
                    LED_YELLOW
                    if is_codex_foreground()
                    else LED_OFF
                ),
            )
            self.set_led(
                0xF,
                (
                    0xC
                    if is_codex_foreground()
                    else LED_OFF
                ),
            )

            self.reasoning.resolve_async(
                active.conversation_id,
                self.events,
            )
        else:
            self.set_led(
                0xE,
                (
                    self._reasoning_led_state()
                    if is_codex_foreground()
                    else LED_OFF
                ),
            )
            self.set_led(
                0xF,
                (
                    self._plan_led_state()
                    if is_codex_foreground()
                    else LED_OFF
                ),
            )

        LOGGER.info(
            "Active conversation changed to %s",
            active.conversation_id,
        )

    def _poll_reasoning_effort(self) -> None:
        now = time.monotonic()

        if now < self._next_reasoning_check:
            return

        self._next_reasoning_check = (
            now + REASONING_POLL_SECONDS
        )

        active = self.desktop_log.current()

        if active is None:
            return

        self._active_conversation_id = (
            active.conversation_id
        )

        resolved = self.reasoning.poll_local(
            active.conversation_id
        )

        if resolved is not None:
            self.handle_event(resolved)

        if (
            not self.reasoning.tracks_local(
                active.conversation_id
            )
            and now
            >= self._next_remote_settings_check
        ):
            self._next_remote_settings_check = (
                now + REMOTE_SETTINGS_POLL_SECONDS
            )
            self.reasoning.resolve_async(
                active.conversation_id,
                self.events,
            )

    def _poll_remote_statuses(self) -> None:
        if self.remote_status is None:
            return

        now = time.monotonic()

        if now < self._next_remote_status_check:
            return

        self._next_remote_status_check = (
            now + REMOTE_STATUS_POLL_SECONDS
        )
        conversation_ids = tuple(
            self.slots.snapshot().values()
        )

        if conversation_ids:
            self.remote_status.resolve_async(
                conversation_ids,
                self.events,
            )

    def _reasoning_led_state(self) -> int:
        conversation_id = (
            self._active_conversation_id
        )

        if conversation_id is None:
            return LED_OFF

        effort = self.statuses.reasoning_effort(
            conversation_id
        )

        return REASONING_LED_STATES.get(
            effort,
            LED_OFF,
        )

    def _poll_pico_keepalive(self) -> None:
        now = time.monotonic()

        if now < self._next_pico_keepalive:
            return

        self._next_pico_keepalive = (
            now + PICO_KEEPALIVE_SECONDS
        )

        if not self.runtime.snapshot().pico_connected:
            return

        # LED 0の現在値を冪等な1-byte statecodeとして再送する。
        # 無通信時のUSB selective suspendを避けるためのkeepalive。
        self.pico.send(
            self.panel.full_sync_payload()[:1]
        )

    def _plan_led_state(self) -> int:
        conversation_id = (
            self._active_conversation_id
        )

        if conversation_id is None:
            return LED_OFF

        mode = self.statuses.collaboration_mode(
            conversation_id
        )

        if mode == "plan":
            return 0xA       # 紫

        if mode == "default":
            return LED_WHITE

        return 0xC           # 不明・照会中

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                event = self.events.get(timeout=0.05)
            except queue.Empty:
                event = None

            if event is not None:
                self.handle_event(event)

            self._poll_codex_foreground()
            self._poll_active_task()
            self._poll_approval_response()
            self._poll_reasoning_effort()
            self._poll_remote_statuses()
            self._poll_pico_keepalive()
