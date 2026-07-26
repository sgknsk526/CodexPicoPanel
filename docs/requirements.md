# Codex Pico Panel 要件 v1.0

更新日: 2026-07-26

## 責務

- Picoは16個の物理キーとLEDを扱い、USB CDC dataだけを公開する
- Windows常駐アプリはキーedge・長押し・foreground条件を判定する
- Windows常駐アプリだけが固定ショートカットとCodex UIを操作する
- Codex hook、Desktopログ、session rollout、app-serverから状態を復元する
- WindowsがLED状態の正本を持ち、接続時に16状態を全同期する

PicoのUSB HIDとMIDIは無効化し、Picoから任意キー、任意文字列、任意コマンドを
要求できない構造にする。

## 操作要件

キー配置と色は[日本語README](../README.ja.md#キー配置)を正本とする。

- 1–7はCodexが最前面でなければ起動・前面化してからshortcutを送る
- 8/9/A/C/D/E/FはCodexが最前面で始まった操作だけを受け付ける
- BはCodexのforeground状態に依存しない
- 9/A/C/Dの実行には600ms以上の長押しを要求する
- C/Dはpress時とrelease時の両方で実行条件を確認する
- C/Dは承認待ち、またはidleかつ入力欄が空のときだけ有効にする
- 切断時は保持中のvoice input chordを必ずreleaseする

## USB protocol v1

WindowsからPicoへは1-byte statecode `0xXY`を送る。PicoはX番LEDの内部状態を
Yへ更新する。

PicoからWindowsへは16-bit key maskを2-byte little-endianで送る。Windowsは
前回値との差分から0-based key `0..F`のpress/releaseを生成する。

初回同期が16 LEDすべて完了するまでPicoはキー状態を送信しない。Windowsは
一時的なwrite timeoutではCOMを閉じず、同じstatecodeを再試行する。実際の
serial切断後は自動再接続して全同期する。

## 状態監視

- hook: prompt開始、承認待ち、tool終了、turn終了、失敗結果
- Desktopログ: 表示中conversation ID、承認UIの応答
- local rollout: reasoning effortとcollaboration modeを追記監視
- remote rollout: SSH probeでreasoning effortとcollaboration modeを取得
- app-server: 常駐起動時に登録済みlocal/remoteタスクの実行状態を復元

reasoning effortとPlan状態はconversationごとに保持する。conversation IDを
伴わないDesktop全体のreasoningログを表示中conversationへ転用しない。

## 安全・運用要件

- Dashboardとhook APIは`127.0.0.1`へだけbindする
- remote hook ingressはSSH reverse tunnelのremote loopbackだけへ公開する
- hook bodyは64KiB以下のJSON objectに限定し、未知イベントを拒否する
- UI Automation失敗、hook送信失敗、SSH切断でCodex本体を停止させない
- app-server要求にはtimeoutを設け、常駐起動を無期限にblockしない
- runtime registration、probeログ、build metadataをGitへ含めない
- 状態ページは切断回数、最終切断理由、タスク状態、reasoning、Plan状態を表示する
