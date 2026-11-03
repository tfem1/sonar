"""Drive sonar inside a real pseudo-terminal and inspect the screen.

Test-only helper: needs `pyte` (pip install pyte). sonar itself has no dependencies.
"""
import fcntl
import html
import os
import pty
import select
import struct
import termios
import time

import pyte
import pyte.graphics

# pyte ignores SGR 2 (dim); sonar never blinks, so map dim onto the blink flag
pyte.graphics.TEXT[2] = "+blink"

HERE = os.path.dirname(os.path.abspath(__file__))
SONAR = os.path.join(os.path.dirname(HERE), "sonar.py")


class Session:
    def __init__(self, cols=80, rows=24, args=(), env=None):
        self.cols, self.rows = cols, rows
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.raw = bytearray()
        pid, fd = pty.fork()
        if pid == 0:
            e = dict(os.environ, TERM="xterm-256color", **(env or {}))
            e.pop("COLUMNS", None)
            e.pop("LINES", None)
            os.execvpe("python3", ["python3", SONAR, *args], e)
        self.pid, self.fd = pid, fd
        self.resize(cols, rows)
        self.exit_status = None

    def resize(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.screen.resize(rows, cols)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def pump(self, secs=0.3):
        end = time.time() + secs
        while True:
            left = end - time.time()
            if left <= 0:
                break
            r, _, _ = select.select([self.fd], [], [], left)
            if not r:
                continue
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                break
            if not data:
                break
            self.raw += data
            self.stream.feed(data)

    def send(self, keys, wait=0.35):
        os.write(self.fd, keys.encode() if isinstance(keys, str) else keys)
        self.pump(wait)

    def text(self):
        return "\n".join(self.screen.display)

    def wait_exit(self, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.1)
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.exit_status = status
                return status
        return None

    def html(self, title="sonar", light=False):
        """Render the emulated screen (with truecolor) as an HTML <pre>."""
        default_fg, default_bg = ("#1f2328", "#f8f8f6") if light else ("#d8dee9", "#10121a")

        def col(c, fallback):
            if c in ("default", None):
                return fallback
            if isinstance(c, str) and len(c) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in c):
                return "#" + c
            named = {"black": "#1b1d24", "red": "#e06c75", "green": "#98c379", "brown": "#e5c07b",
                     "blue": "#61afef", "magenta": "#c678dd", "cyan": "#56b6c2", "white": "#d8dee9"}
            return named.get(c, fallback)

        out = []
        for y in range(self.rows):
            row = self.screen.buffer[y]
            spans, cur, buf = [], None, []
            for x in range(self.cols):
                ch = row[x]
                fg, bg = col(ch.fg, default_fg), col(ch.bg, default_bg)
                if ch.reverse:
                    fg, bg = bg, fg
                style = "color:%s;background:%s" % (fg, bg)
                if ch.bold:
                    style += ";font-weight:700"
                if ch.underscore:
                    style += ";text-decoration:underline"
                if ch.blink:  # = dim, see the mapping at the top
                    style += ";opacity:.55"
                if style != cur:
                    if buf:
                        spans.append('<span style="%s">%s</span>' % (cur, "".join(buf)))
                    cur, buf = style, []
                c = ch.data or " "
                # fallback fonts for box/braille glyphs have other widths: pin each to one cell
                buf.append(html.escape(c) if c.isascii() else '<i>%s</i>' % html.escape(c))
            if buf:
                spans.append('<span style="%s">%s</span>' % (cur, "".join(buf)))
            out.append('<div class="r">' + "".join(spans) + "</div>")
        return ("<!doctype html><meta charset=utf-8><title>%s</title><style>body{margin:0;background:%s}"
                "pre{margin:0;padding:18px 22px;font:14px 'JetBrains Mono','DejaVu Sans Mono','DejaVu Sans',monospace;color:%s;width:max-content}"
                ".r{height:18px;line-height:18px;white-space:pre}"
                "i{font-style:normal;display:inline-block;width:1ch;overflow:visible;text-align:center}</style>"
                "<pre>%s</pre>" % (title, default_bg, default_fg, "".join(out)))

    def close(self):
        try:
            os.kill(self.pid, 9)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass
