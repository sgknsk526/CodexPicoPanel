"""USB setup for Codex Pico Panel."""

import usb_cdc
import usb_hid
import usb_midi
import supervisor


supervisor.runtime.autoreload = False
usb_hid.disable()
usb_midi.disable()
usb_cdc.enable(console=True, data=True)
