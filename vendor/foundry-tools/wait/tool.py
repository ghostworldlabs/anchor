"""wait: block until something you started finishes - a process, a file, or a line in a log - with a time limit.

  ft.py wait --pid N [--max-min M]
  ft.py wait --file PATH [--stable-s S] [--max-min M]        until it exists and stops growing for S seconds
  ft.py wait --log PATH --line REGEX [--max-min M]           until a line matches

One command in the foreground instead of a hand-written sleep/poll loop; it costs no model turns while it waits.
Prints one line: what happened and how long it took. Exit 0 done, 1 the time limit passed, 2 bad arguments.
A steward never waits on its own Anchor jobs - it ends its turn and Anchor wakes it."""
import argparse
import os
import re
import sys
import time
from pathlib import Path


def alive(pid):
    """True while the process runs - and whenever its state cannot be read (access denied): only a CONFIRMED exit
    ends the wait (review r1 #4)."""
    if os.name == "nt":
        import ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() != 87         # ERROR_INVALID_PARAMETER: no such process
        try:
            code = ctypes.c_ulong()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == 259                     # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pid", type=int)
    g.add_argument("--file")
    g.add_argument("--log")
    ap.add_argument("--line", help="with --log: the regular expression to wait for")
    ap.add_argument("--stable-s", type=float, default=2.0)
    ap.add_argument("--max-min", type=float, default=30.0)
    a = ap.parse_args(argv)
    if a.log and not a.line:
        print("--log needs --line REGEX")
        return 2
    t0 = time.time()
    deadline = t0 + a.max_min * 60
    step = 0.25
    last_size, steady_since, pos = None, None, 0
    pat = re.compile(a.line) if a.line else None
    while True:
        now = time.time()
        if a.pid is not None and not alive(a.pid):
            print("process %d ended after %.1f s" % (a.pid, now - t0))
            return 0
        if a.file:
            p = Path(a.file)
            if p.exists():
                size = p.stat().st_size
                if size != last_size:
                    last_size, steady_since = size, now
                elif now - steady_since >= a.stable_s:
                    print("%s ready (%d bytes) after %.1f s" % (p, size, now - t0))
                    return 0
        if a.log:
            p = Path(a.log)
            if p.exists():
                with open(p, "rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                    nl = chunk.rfind(b"\n")
                    if nl >= 0:                           # only whole lines; a half-written line waits
                        for ln in chunk[:nl].decode("utf-8", "replace").splitlines():
                            if pat.search(ln):
                                print("matched after %.1f s: %s" % (now - t0, ln.strip()[:200]))
                                return 0
                        pos += nl + 1
        if now >= deadline:
            print("still waiting after %g min - the time limit; nothing was stopped" % a.max_min)
            return 1
        time.sleep(step)
        step = min(step * 1.5, 5.0)


if __name__ == "__main__":
    sys.exit(main())
