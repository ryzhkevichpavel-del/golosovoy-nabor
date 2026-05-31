from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import time

import pyperclip
from pynput.keyboard import Controller, Key


def copy_text(text: str) -> None:
    pyperclip.copy(text)


def paste_text(text: str, do_paste: bool = True) -> bool:
    copy_text(text)
    if not do_paste:
        return False

    time.sleep(0.08)
    if os.name == "nt" and _paste_with_windows():
        return True

    keyboard = Controller()
    try:
        with keyboard.pressed(Key.ctrl):
            keyboard.press("v")
            keyboard.release("v")
        return True
    except Exception:
        return False


def _paste_with_windows() -> bool:
    try:
        user32 = ctypes.windll.user32
        keybd_event = user32.keybd_event
        keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.wintypes.DWORD, ctypes.c_void_p]
        keybd_event.restype = None
        vk_control = 0x11
        vk_v = 0x56
        key_up = 0x0002
        keybd_event(vk_control, 0, 0, None)
        keybd_event(vk_v, 0, 0, None)
        keybd_event(vk_v, 0, key_up, None)
        keybd_event(vk_control, 0, key_up, None)
        return True
    except Exception:
        return False
