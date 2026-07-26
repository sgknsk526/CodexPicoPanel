"""Windows foreground-window detection."""

import ctypes
from ctypes import wintypes
from pathlib import Path


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

kernel32.OpenProcess.argtypes = [
    wintypes.DWORD,
    wintypes.BOOL,
    wintypes.DWORD,
]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def foreground_process_path():
    """最前面ウィンドウを所有するexeのパスを返す。"""

    hwnd = user32.GetForegroundWindow()

    if not hwnd:
        return None

    process_id = wintypes.DWORD()

    user32.GetWindowThreadProcessId(
        hwnd,
        ctypes.byref(process_id),
    )

    if not process_id.value:
        return None

    process = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        process_id.value,
    )

    if not process:
        return None

    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))

        succeeded = kernel32.QueryFullProcessImageNameW(
            process,
            0,
            buffer,
            ctypes.byref(size),
        )

        if not succeeded:
            return None

        return buffer.value

    finally:
        kernel32.CloseHandle(process)


def is_codex_foreground():
    path = foreground_process_path()

    if path is None:
        return False

    executable_path = Path(path)
    executable = executable_path.name.casefold()

    # Codex.exeが直接ウィンドウを所有する場合
    if executable == "codex.exe":
        return True

    # Windows Store版CodexのウィンドウはChatGPT.exeが所有する
    if executable == "chatgpt.exe":
        return any(
            part.casefold().startswith("openai.codex_")
            for part in executable_path.parts
        )

    return False

def foreground_window_handle():
    hwnd = user32.GetForegroundWindow()
    return hwnd or None