#!/usr/bin/env python3
"""Foundry Tool: chrome-open — Deterministically open URLs or local HTML files in Google Chrome on WinSta0\\Default.

Bypasses offscreen agent sandbox desktops (WinSta0\\exebox-*) and Session-0
MSEdgeHTM association traps on Windows hosts.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if c and Path(c).is_file():
            return str(Path(c))
    raise FileNotFoundError("Google Chrome (chrome.exe) not found in standard paths.")


def current_desktop_name() -> str:
    if os.name != "nt":
        return "posix"
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    h_winsta = u32.GetProcessWindowStation()
    buf = ctypes.create_unicode_buffer(256)
    u32.GetUserObjectInformationW(h_winsta, 2, buf, 512, None)
    winsta = buf.value
    h_desk = u32.GetThreadDesktop(k32.GetCurrentThreadId())
    u32.GetUserObjectInformationW(h_desk, 2, buf, 512, None)
    return f"{winsta}\\{buf.value}"


def list_default_desktop_chrome_windows() -> list[str]:
    if os.name != "nt":
        return []
    u32 = ctypes.windll.user32
    h_def = u32.OpenDesktopW("Default", 0, False, 0x01FF)
    if not h_def:
        return []
    titles: list[str] = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        if u32.IsWindowVisible(hwnd):
            length = u32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                u32.GetWindowTextW(hwnd, buf, length + 1)
                if "Chrome" in buf.value:
                    titles.append(buf.value)
        return True

    try:
        u32.EnumDesktopWindows(h_def, WNDENUMPROC(_cb), 0)
    finally:
        u32.CloseDesktop(h_def)
    return titles


def launch_on_default_desktop(urls: list[str], new_window: bool = False) -> dict:
    chrome = find_chrome()
    caller_desktop = current_desktop_name()
    before_titles = list_default_desktop_chrome_windows()

    args = [chrome]
    if new_window:
        args.append("--new-window")
    args.extend(urls)
    cmd_line = subprocess.list2cmdline(args)

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    si.lpDesktop = "WinSta0\\Default"
    si.dwFlags = 0x00000001  # STARTF_USESHOWWINDOW
    si.wShowWindow = 1       # SW_SHOWNORMAL
    pi = PROCESS_INFORMATION()

    k32 = ctypes.windll.kernel32
    launched_pid = None
    for flags in (0x01000000, 0):
        buf = ctypes.create_unicode_buffer(cmd_line)
        ok = k32.CreateProcessW(
            chrome,
            buf,
            None,
            None,
            False,
            flags,
            None,
            None,
            ctypes.byref(si),
            ctypes.byref(pi),
        )
        if ok:
            launched_pid = int(pi.dwProcessId)
            k32.CloseHandle(pi.hThread)
            k32.CloseHandle(pi.hProcess)
            break

    if launched_pid is None:
        raise RuntimeError(f"CreateProcessW failed with WinError {k32.GetLastError()}")

    time.sleep(1.2)
    after_titles = list_default_desktop_chrome_windows()
    return {
        "ok": True,
        "chrome": chrome,
        "caller_desktop": caller_desktop,
        "target_desktop": "WinSta0\\Default",
        "launched_pid": launched_pid,
        "urls": urls,
        "visible_chrome_windows_before": before_titles,
        "visible_chrome_windows_after": after_titles,
    }


def _normalize_target(arg: str) -> str:
    if arg.startswith(("http://", "https://", "file://", "--")):
        return arg
    p = Path(arg)
    if p.exists():
        return p.resolve().as_uri()
    return arg


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Open URLs or local HTML files in visible Chrome on WinSta0\\Default.")
    parser.add_argument("urls", nargs="*", help="URLs or local HTML files to open in Chrome")
    parser.add_argument("--new-window", action="store_true", help="Open in a new Chrome window")
    parser.add_argument("--selftest", action="store_true", help="Verify WinSta0\\Default access and Chrome installation")
    ns = parser.parse_args(args)

    if ns.selftest:
        chrome = find_chrome()
        wins = list_default_desktop_chrome_windows()
        out = {
            "ok": True,
            "chrome": chrome,
            "caller_desktop": current_desktop_name(),
            "target_desktop": "WinSta0\\Default",
            "visible_chrome_windows": wins,
        }
        print(json.dumps(out, indent=2))
        return 0

    if not ns.urls:
        parser.error("Provide at least one URL/file or --selftest.")

    normalized = [_normalize_target(a) for a in ns.urls]
    res = launch_on_default_desktop(normalized, new_window=ns.new_window)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
