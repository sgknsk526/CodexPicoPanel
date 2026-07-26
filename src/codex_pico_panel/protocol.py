"""Binary protocol shared with the Pico firmware."""

KEY_COUNT = 16
KEY_MASK_BYTES = 2
MAX_LED_STATE = 0x0F
FULL_KEY_MASK = 0xFFFF


def encode_statecode(led_index: int, state: int) -> bytes:
    """Encode `LED X <- state Y` as one byte, 0xXY."""

    if not 0 <= led_index < KEY_COUNT:
        raise ValueError("led_index must be 0..15")
    if not 0 <= state <= MAX_LED_STATE:
        raise ValueError("state must be 0..15")
    return bytes([(led_index << 4) | state])


def encode_full_state(states: bytes | bytearray) -> bytes:
    """Encode all 16 LED states for the Pico's initial synchronization."""

    if len(states) != KEY_COUNT:
        raise ValueError("states must contain exactly 16 values")

    payload = bytearray(KEY_COUNT)
    for index, state in enumerate(states):
        payload[index] = encode_statecode(index, state)[0]
    return bytes(payload)


def decode_key_mask(data: bytes) -> int:
    """Decode a two-byte little-endian physical-key state."""

    if len(data) != KEY_MASK_BYTES:
        raise ValueError("key mask must be exactly 2 bytes")
    return int.from_bytes(data, "little") & FULL_KEY_MASK
