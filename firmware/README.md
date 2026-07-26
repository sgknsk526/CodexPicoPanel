# Pico firmware

Tested with CircuitPython 10.2.1 on a Raspberry Pi Pico (RP2040) connected to a
Pimoroni Pico RGB Keypad Base.

Install the following on `CIRCUITPY`:

```text
/boot.py
/code.py
/lib/pmk/
/lib/adafruit_dotstar.mpy
```

Copy `boot.py` and `code.py` from this directory. Install PMK and the matching
DotStar library by following Pimoroni's
[CircuitPython guide](https://learn.pimoroni.com/circuitpython-and-keybow-2040).
Power-cycle the Pico after changing `boot.py`.

`boot.py` disables filesystem autoreload, USB HID, and MIDI, then enables the
CircuitPython CDC console and CDC data interfaces. The panel is not exposed as
a keyboard.

`code.py` exchanges a fixed binary protocol with the Windows resident process:

- Windows to Pico: one-byte statecode `0xXY` (`LED X <- state Y`)
- Pico to Windows: two-byte little-endian 16-bit physical-key mask

At boot all LEDs briefly show white. Until the Windows process has opened the
CDC data port and sent the initial state for all 16 LEDs, key 0 pulses purple
and key input is not sent. After synchronization, only changed key masks and
changed LED states are transferred.
