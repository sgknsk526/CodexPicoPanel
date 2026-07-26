# Codex Pico Panel

[English](README.md)

Raspberry Pi PicoとPimoroni Pico RGB Keypad Baseを、Windows版Codex Desktop用の
16キー操作・状態表示パネルとして使うためのWindows常駐アプリとCircuitPython
firmwareです。

Picoはキーボードとして認識されません。16個の物理キー状態をUSB CDCでWindows
常駐アプリへ送り、Windows側が固定ショートカットとCodex UI操作だけを実行します。
Codexの状態はコンパクトなstatecodeとしてPicoのLEDへ返します。

> [!WARNING]
> experimentalな非公式プロジェクトであり、OpenAI、Pimoroni、Raspberry Piとは
> 無関係です。Codex Desktopログ、UI Automation、session JSONL、alpha版
> app-serverへ依存するため、Codex更新で動かなくなる可能性があります。C/Dキーは
> 承認・拒否を自動操作するので、有効化前にコードとCodexの承認設定を確認してください。

## 必要環境

- Raspberry Pi Pico（RP2040）
- Pimoroni Pico RGB Keypad Base
- データ通信対応Micro-USBケーブル
- Windows 10または11
- Python 3.11以上
- remoteタスクを使う場合はWindows OpenSSH client
- Codex Desktop

動作確認環境はCircuitPython 10.2.1、Codex Desktop 26.715.10079、同梱
Codex app-server 0.145.0-alpha.30です。これは最小対応版の保証ではありません。

## 構成と通信仕様

```text
Pico key mask -> Windows常駐 -> 固定shortcut/Codex UI操作
Codex hook/log/session/app-server -> Windows常駐 -> Pico LED状態
```

- Windows → Pico：1-byte statecode `0xXY`（`LED X <- state Y`）
- Pico → Windows：16-bit物理key maskを2-byte little-endianで送信
- 接続時：16個のLED状態を全同期
- 通常時：キーまたはLED状態が変化したときだけ送信

`firmware/boot.py`でUSB HIDとMIDIを無効化します。PicoはCDC consoleとCDC dataを
公開し、常駐アプリはdata portを開きます。

## キー配置

| Key | 操作 | LED |
|---|---|---|
| 0 | 2秒以内に離すとCodexを起動・前面化 | Codex最前面で青 |
| 1–7 | 離すと`Ctrl+1`–`Ctrl+7`、1秒長押しで表示中タスクを登録/解除 | タスク状態 |
| 8 | 押している間`Ctrl+Shift+F` | 使用可能時は白、押下中は黄 |
| 9 | 0.6秒長押しで送信、または実行中turnを停止 | 送信可能は緑、実行中は青 |
| A | 0.6秒長押しで入力内容を全消去 | 消去可能はオレンジ |
| B | 状態ページを開く | 押下中は黄 |
| C | 0.6秒長押しで承認 | 使用可能時は緑 |
| D | 0.6秒長押しで拒否 | 使用可能時は赤 |
| E | `Ctrl+Shift+W`でreasoning effortを切替 | 現在のeffort色 |
| F | `Ctrl+Shift+X`でPlanモードを切替 | defaultは白、Planは紫 |

1–7の色は、未登録=消灯、idle=白、正常終了未読=緑、thinking=青、
承認待ち=ピンク、異常終了未読=赤です。登録タスクを表示すると既読になります。

reasoning effortの色はlow=灰、medium=緑、high=水色、xhigh=青、
max=オレンジ、ultra=赤です。

Codex Desktop側で、push-to-talk、reasoning effort、Planモードを表のshortcutへ
設定してください。9/A/C/DはshortcutではなくWindows UI Automationで操作します。

## Picoセットアップ

1. Raspberry Pi Pico用CircuitPythonを導入する
2. Pimoroni PMKを`CIRCUITPY/lib/pmk`へ導入する
3. 対応するCircuitPython library bundleの`adafruit_dotstar.mpy`を
   `CIRCUITPY/lib`へコピーする
4. `firmware/boot.py`と`firmware/code.py`を`CIRCUITPY`へコピーする
5. `boot.py`変更後はPicoを電源再投入する

詳しくはPimoroniの
[CircuitPython and Pico RGB Keypad guide](https://learn.pimoroni.com/circuitpython-and-keybow-2040)
を参照してください。

起動時は一時的に全LEDが白になります。WindowsがCDC data portを開くまでは0番が
紫で明滅し、16 LEDの初期同期が完了すると通常動作へ移ります。

## Windowsセットアップ

```powershell
git clone https://github.com/sgknsk526/CodexPicoPanel.git
cd CodexPicoPanel
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

デバイスマネージャーでPicoのCDC data portを確認します。CircuitPythonでは
consoleとdataの2個のCOM portが見えるため、consoleではなくdataを指定します。

localのみ：

```powershell
.\.venv\Scripts\python.exe -m codex_pico_panel --port COM4 --no-remote
```

SSH remoteも利用：

```powershell
.\.venv\Scripts\python.exe -m codex_pico_panel `
    --port COM4 `
    --remote-host my-ssh-alias
```

`--remote-host`の代わりに`CODEX_PICO_REMOTE_HOST`環境変数も使用できます。

## Codex hook

hookはloopback限定の常駐APIへライフサイクル状態を送ります。
[`examples/hooks.windows.json`](examples/hooks.windows.json)のevent設定をWindowsの
`~/.codex/hooks.json`へ統合し、`C:\\path\\to`をcheckout先の絶対パスへ置き換えて
Codexを再起動してください。

remote hostでは以下を行います。

1. Windowsの`~/.ssh/config`へ接続可能なSSH aliasを設定する
2. `hooks/codex_pico_hook.py`と`hooks/codex_pico_remote_hook.py`をremoteの
   `~/.codex/hooks/`へコピーする
3. [`examples/hooks.remote.json`](examples/hooks.remote.json)をremoteの
   `~/.codex/hooks.json`へ統合する
4. 常駐アプリを`--remote-host my-ssh-alias`付きで起動する

常駐アプリはremote loopback `127.0.0.1:48974`からWindows loopback
`127.0.0.1:48973`へのreverse SSH tunnelを維持します。LANには公開しません。

## ログオン時の常駐

タスクスケジューラで「ユーザーがログオンしているときのみ実行」を選びます。
shortcutとUI Automationには対話ユーザーセッションが必要です。

- プログラム：`C:\path\to\CodexPicoPanel\.venv\Scripts\pythonw.exe`
- 引数：
  `-m codex_pico_panel --port COM4 --remote-host my-ssh-alias --log-file "C:\path\to\CodexPicoPanel\.runtime\resident.log"`
- 開始場所：`C:\path\to\CodexPicoPanel`
- トリガー：ログオン時
- 二重起動時：新しいインスタンスを開始しない

remote不要なら`--remote-host`を省略するか`--no-remote`を追加します。

terminalまたはcommand fileのダブルクリックから常駐アプリを再起動できます。

```powershell
.\scripts\restart-resident.cmd
```

Windows loopback経由で正常終了を要求し、COMとSSHの終了を待ってから
`\Codex Pico Panel`タスクを起動し、状態APIの復帰まで確認します。
タスク名が異なる場合は`-TaskName`を指定してください。

## 状態ページと診断

[http://127.0.0.1:48973/](http://127.0.0.1:48973/)またはBキーで開きます。COM接続、
切断回数・理由、key mask、LED、登録タスク、表示中タスク、reasoning、Plan状態を
確認できます。

登録情報は`data/slots.json`へ保存されます。登録、venv、ログ、バックアップ、
probe、build生成物はGit対象外です。

- **0番が紫のまま：** CDC data portが開かれていないか初期同期が未完了
- **COMが数秒消える：** ケーブル、USB port、給電を確認。常駐は自動再接続する
- **remoteタスクが実行中でも白：** ログの`Starting SSH hook tunnel`とremoteの
  `127.0.0.1:48974`待受を確認する
- **hook失敗が表示されない：** Codexを止めないよう送信失敗は非fatal。常駐ログと
  状態ページで診断する
- **48973使用中：** 常駐アプリの二重起動を止める

## 開発

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m build
```

## Privacy・安全性

status/hook serverは`127.0.0.1`だけへbindします。hook eventにはsession ID、turn ID、
lifecycle、reasoning effort、collaboration modeが含まれますが、prompt/response
本文は常駐APIへ送りません。失敗やthread settingsを判定するため、hookがlocal
session transcriptを読むことがあります。

C/Dは長押しと表示中タスク状態で保護していますが、承認操作の自動化であることに
変わりはありません。誤承認を許容できない環境では使用しないでください。

## License

[MIT](LICENSE)
