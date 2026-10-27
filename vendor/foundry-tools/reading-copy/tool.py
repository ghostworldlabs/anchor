"""reading-copy: the same-version PDF (and HTML) of a Markdown document, in about a second.

The renderer is Anchor's own Markdown page, so the code stays with it (C:/dev/Anchor/tools/reading_copy.py); this
Foundry entry runs the installed copy. ANCHOR_HOME points at another Anchor folder (tests)."""
import os
import subprocess
import sys
from pathlib import Path

anchor = Path(os.environ.get("ANCHOR_HOME") or "C:/dev/Anchor")
script = anchor / "tools" / "reading_copy.py"
if not script.is_file():
    print("reading-copy needs Anchor installed: %s is missing" % script)
    sys.exit(1)
sys.exit(subprocess.call([sys.executable, str(script)] + sys.argv[1:]))
