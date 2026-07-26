# 現行アーキテクチャ

## Pico

- `firmware/boot.py`: USB HID/MIDIを無効化し、CDC console/dataを有効化
- `firmware/code.py`: key mask送信、statecode受信、LED描画、初期同期

PicoはCodexの意味を解釈せず、Windowsから受け取った4-bit LED状態だけを保持する。

## Windows resident

- `__main__.py`: 設定、起動時状態復元、各workerのlifecycle
- `protocol.py`: 1-byte statecodeと2-byte key mask
- `pico_link.py`: COM所有、自動再接続、送受信backpressure
- `panel_state.py`: Windows側の16 LED authoritative state
- `controller.py`: key edge、長押し、foreground条件、状態遷移
- `runtime.py`: 接続状態と切断診断snapshot
- `task_slots.py`: 1–7とconversation IDの永続登録
- `task_status.py`: conversation別phase、未読、error、thread settings
- `status_server.py`: loopback dashboard、status API、hook ingress

## Codex adapters

- `codex/shortcuts.py`: 固定shortcutだけをWindowsへ送信
- `codex/composer.py`: UI Automationによる入力欄・停止・承認操作
- `codex/desktop_log.py`: 表示中conversationと承認応答の検出
- `codex/reasoning.py`: local/remote rolloutからthread settingsを解決
- `codex/app_server.py`: 起動時の登録タスク状態復元
- `codex/hook_event.py`: hook payloadのvalidation

## Event flow

```text
Pico key mask -> PicoLink -> Controller -> shortcut/UI action
Codex hook -> StatusServer -> Controller -> TaskStatuses
Desktop/session/app-server -> Controller -> TaskStatuses
TaskStatuses -> PanelState -> PicoLink -> Pico LED
```

workerは共有queueへimmutable eventを送り、panelと操作判断はControllerが
single ownerとして処理する。状態ページ用snapshotだけはlockで保護して共有する。
