# look

**When:** you need to see a page or an HTML deliverable the way John will - at phone and desktop size - or to prove
an element is (or is not) actually on screen. Never build your own screenshot script.

**Command:** `python C:/dev/foundry-tools/ft.py look <file.html|url> [--check "<css>"]... [--click "<css>"]... [--size phone|tablet|desktop|WxH]... [--out <folder>] [--full] [--json]`

**Time:** 2-5 seconds. **Needs:** Python Playwright with Chromium (installed on PUTER).

Prints one line per size with the screenshot path and page errors, and for each `--check` whether it is PAINTED
(visible, non-zero size, not hidden by display/visibility/opacity). It flags an element that is shown despite its
`hidden` attribute. Screenshots go to a temp folder unless `--out` is given - keep them out of the repository.
Look at one or two screenshots, not dozens.

Pages open with WebSockets, workers and event streams turned off (a screenshot needs no live connection), and
look never reaches Anchor itself: port 8777 however written, redirects included (a redirected image or script is left
out and said). A form redirect that would resend its data is not followed.

A page that never finishes is given up after 120 s (`LOOK_MAX_S`), exit 3. Known limit: after a `--click`, a redirect
does not carry the click's own `#part` (the browser never shows it to look).
