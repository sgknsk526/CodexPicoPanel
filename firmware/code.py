"""Minimal Codex Pico Panel firmware.

Win -> Pico:
    1 byte statecode: 0xXY
    X = LED index 0..F
    Y = LED state 0..F

Pico -> Win:
    2 byte little-endian key mask

Connection:
    Windows sends all LED indices 0..F after opening the port.
    Communication is established after all 16 states are received.
"""

import math
import time
import usb_cdc

from pmk import PMK
from pmk.platform.rgbkeypadbase import RGBKeypadBase as Hardware


KEY_COUNT = 16
FULL_SYNC_MASK = 0xFFFF

LOOP_SECONDS = 0.004
STARTUP_SECONDS = 0.6
WAIT_PULSE_SECONDS = 2.0

STARTUP_WHITE = (48, 48, 48)
WAIT_PURPLE_MIN = 4
WAIT_PURPLE_MAX = 64

# 状態0～Fに対応する通常表示色
LED_COLORS = (
    (0, 0, 0),       # 0: 消灯
    (0, 0, 64),      # 1: 青
    (0, 48, 64),     # 2: 水色
    (0, 64, 0),      # 3: 緑
    (32, 64, 0),     # 4: 黄緑
    (64, 64, 0),     # 5: 黄
    (64, 32, 0),     # 6: オレンジ
    (64, 0, 0),      # 7: 赤
    (64, 0, 32),     # 8: ピンク
    (48, 20, 0),     # 9: 茶
    (32, 0, 64),     # A: 紫
    (16, 16, 64),    # B: 青紫
    (16, 16, 16),    # C: 暗い白
    (32, 32, 32),    # D: 白
    (64, 64, 64),    # E: 明るい白
    (64, 0, 0),      # F: エラー用
)


# キーパッド初期化
pmk = PMK(Hardware())
pmk.rotate(90)

keys = [None] * KEY_COUNT

for key in pmk.keys:
    if 0 <= key.number < KEY_COUNT:
        keys[key.number] = key

if any(key is None for key in keys):
    raise RuntimeError("Could not map all 16 keys")


# Windows常駐との通信用CDC
serial = usb_cdc.data

if serial is None:
    raise RuntimeError("usb_cdc.data is disabled")

serial.timeout = 0
serial.write_timeout = 0


# Windowsから指示された通常状態
led_states = bytearray(KEY_COUNT)

# 実際に現在表示している色
displayed_colors = [None] * KEY_COUNT

# 接続状態
received_led_mask = 0
previous_key_mask = -1
was_connected = False

boot_started_at = time.monotonic()


def normal_color(index):
    """保持状態に対応する通常表示色を返す。"""

    return LED_COLORS[led_states[index]]


def display_color(index, color):
    """変更があるLEDだけハードウェアへ反映する。"""

    if displayed_colors[index] == color:
        return

    red, green, blue = color
    keys[index].set_led(red, green, blue)
    displayed_colors[index] = color


def apply_statecode(statecode):
    """0xXYをLED Xの状態をYにする命令として適用する。"""

    global received_led_mask

    led_index = (statecode >> 4) & 0x0F
    new_state = statecode & 0x0F

    led_states[led_index] = new_state

    # このLEDの初期状態を受け取ったことを記録
    received_led_mask |= 1 << led_index


def receive_statecodes():
    """届いているstatecodeをすべて処理する。"""

    waiting = serial.in_waiting

    if waiting <= 0:
        return

    data = serial.read(waiting)

    if not data:
        return

    for statecode in data:
        apply_statecode(statecode)


def read_key_mask():
    """現在押されているキーを16bit整数にする。"""

    key_mask = 0

    for index, key in enumerate(keys):
        if key.pressed:
            key_mask |= 1 << index

    return key_mask


def render_startup():
    """起動時はすべて白。"""

    for index in range(KEY_COUNT):
        display_color(index, STARTUP_WHITE)


def render_waiting(now):
    """LED 0を紫色で2秒周期に明滅させる。"""

    elapsed = now - boot_started_at

    wave = 0.5 - 0.5 * math.cos(
        2.0 * math.pi * elapsed / WAIT_PULSE_SECONDS
    )

    brightness = int(
        WAIT_PURPLE_MIN
        + (WAIT_PURPLE_MAX - WAIT_PURPLE_MIN) * wave
    )

    display_color(
        0,
        (brightness, 0, brightness),
    )

    for index in range(1, KEY_COUNT):
        display_color(index, (0, 0, 0))


def render_normal():
    """Windowsから指示された現在状態を表示する。"""

    for index in range(KEY_COUNT):
        display_color(
            index,
            normal_color(index),
        )


while True:
    now = time.monotonic()
    pmk.update()

    connected = serial.connected

    # 接続・切断の変化
    if connected != was_connected:
        received_led_mask = 0
        previous_key_mask = -1
        was_connected = connected

    # 起動中は通信を処理しない
    if now - boot_started_at < STARTUP_SECONDS:
        render_startup()

    # Windows未接続
    elif not connected:
        render_waiting(now)

    else:
        # Windows接続後は、同期中でもstatecodeを受信する
        receive_statecodes()

        # 16個の初期状態を同期中
        if received_led_mask != FULL_SYNC_MASK:
            render_waiting(now)

        # 同期完了
        else:
            # Pico -> Windows
            key_mask = read_key_mask()

            # 状態が変化したときだけ2バイト送信
            if key_mask != previous_key_mask:
                payload = key_mask.to_bytes(2, "little")
                written = serial.write(payload)

                if written == len(payload):
                    previous_key_mask = key_mask

            render_normal()

    time.sleep(LOOP_SECONDS)
