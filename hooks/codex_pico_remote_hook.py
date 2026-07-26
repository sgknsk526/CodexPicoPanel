"""Remote Codex hook entry point for the reverse SSH tunnel."""

from __future__ import annotations

import os
from importlib import import_module


os.environ.setdefault(
    "CODEX_PICO_HOOK_PORT",
    "48974",
)

main = import_module("codex_pico_hook").main


if __name__ == "__main__":
    main()
