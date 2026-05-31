from __future__ import annotations

import time

import pyperclip
from pynput.keyboard import Controller, Key


def copy_text(text: str) -> None:
    pyperclip.copy(text)


def paste_text(text: str, do_paste: bool = True) -> bool:
    copy_text(text)
    if not do_paste:
        return False

    keyboard = Controller()
    time.sleep(0.08)
    try:
        with keyboard.pressed(Key.ctrl):
            keyboard.press("v")
            keyboard.release("v")
        return True
    except Exception:
        return False
