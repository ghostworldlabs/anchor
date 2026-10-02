"""Anchor as a program on PUTER: one WebView2 window around static/app.html (PLAN v2.2 section 3.3,
Skill Foundry/planning/anchor-app-shell-2026-09-29).

Not product code: it runs from its own venv (%LOCALAPPDATA%/anchor-shell/.venv, pywebview + pywin32) and is
not on the ship list. The service is unchanged; this only opens a window onto it.

  - its own taskbar identity (AppUserModelID) and the new anchor as its icon, so it is not "Python";
  - a persistent WebView2 profile, so the token is pasted once and the 30-day cookie is kept;
  - downloads allowed; app links (ms-word:, mailto:) and other sites go to Windows / the default browser;
  - one instance: a second launch brings the open window forward.

Usage:  pythonw shell/anchor_shell.py [--url URL]
"""
import argparse
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

APP_ID = "GhostWorldLabs.Anchor"
TITLE = "Anchor"
DEFAULT_URL = "http://127.0.0.1:8777/static/app.html"
ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "vendor" / "brand" / "anchor-icon.ico"
PROFILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "anchor-shell" / "profile"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.SendMessageW.restype = wintypes.LPARAM
user32.LoadImageW.restype = wintypes.HANDLE
user32.FindWindowW.restype = wintypes.HWND
ERROR_ALREADY_EXISTS = 183


def bring_forward_existing():
    """A second launch: find the open Anchor window, restore it and bring it to the front."""
    hwnd = user32.FindWindowW(None, TITLE)
    if hwnd:
        if user32.IsIconic(hwnd):                       # restore only a minimised window; a maximised one stays
            user32.ShowWindow(hwnd, 9)                  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return bool(hwnd)


def set_window_icon(hwnd, path):
    """WM_SETICON with the anchor (the window frame and Alt+Tab); the taskbar uses the shortcut's icon."""
    LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x0080
    for which, size in ((1, 256), (0, 32)):             # ICON_BIG, ICON_SMALL
        h = user32.LoadImageW(None, str(path), IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if h:
            user32.SendMessageW(hwnd, WM_SETICON, which, h)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    args = ap.parse_args(argv)

    mutex = kernel32.CreateMutexW(None, False, "Local\\" + APP_ID)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        bring_forward_existing()
        return 0

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

    import webview                                      # the venv's; imported after the single-instance check
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True   # ms-word:, mailto:, other sites -> Windows
    PROFILE.mkdir(parents=True, exist_ok=True)

    win = webview.create_window(TITLE, args.url, width=1500, height=950, min_size=(420, 500),
                                background_color="#0f141c")

    def on_shown():
        try:
            set_window_icon(int(str(win.native.Handle)), ICON)
        except Exception as exc:                         # the window still works with the default icon
            print("icon:", exc, file=sys.stderr)

    win.events.shown += on_shown
    webview.start(private_mode=False, storage_path=str(PROFILE))
    kernel32.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
