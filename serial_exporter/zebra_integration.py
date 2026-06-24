"""
zebra_integration
==================================
ZebraDesigner Pro 2 launcher, keyboard automation, and process cleanup.
"""

from __future__ import annotations

import subprocess
import time

import pyautogui

from config import ZEBRA_LABEL_FILE


def zebra_keyboard_sequence() -> None:
    """
    Automate ZebraDesigner Pro 2 UI keystrokes after the label opens:
    1. Dismiss the demo modal
    2. Press OK
    3. Ctrl+R to trigger print
    4. Confrim preview
    """
    try:
        time.sleep(3)
        pyautogui.press("enter")  # dismiss demo modal
        time.sleep(2)
        pyautogui.press("enter")  # press OK
        time.sleep(2)
        pyautogui.hotkey("ctrl", "r")  # trigger print
        time.sleep(2)
        pyautogui.press("enter")  # confirm preview
    except Exception:
        pass


def open_zebra_label(label_path: str) -> subprocess.Popen | None:
    """
    Open the `.lbl` file in ZebraDesigner Pro 2 via Windows file association.
    """
    try:
        return subprocess.Popen(
            ["cmd", "/c", "start", "", label_path],
            shell=True,
        )
    except Exception:
        return None


def close_zebra() -> None:
    """
    Best-effort termination of known ZebraDesigner Pro 2 process names.
    """
    for name in [
        "ZDesigner.exe",
        "ZDesignerPro.exe",
        "ZebraDesigner.exe",
        "ZebraDesignerPro.exe",
        "ZDPro2.exe",
    ]:
        try:
            subprocess.run(
                ["taskkill", "/f", "/im", name],
                capture_output=True,
                timeout=3,
            )
        except Exception:
            pass