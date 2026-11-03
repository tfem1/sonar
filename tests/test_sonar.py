#!/usr/bin/env python3
"""sonar tests.

Linux: end-to-end in a real pseudo-terminal (needs: pip install pyte).
Windows: backend tests against the real Win32 / NT APIs, plus --once rendering.

    python3 tests/test_sonar.py
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sonar  # noqa: E402

WINDOWS = os.name == "nt"
SONAR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sonar.py")
if not WINDOWS:
    from ptyharness import Session  # noqa: E402

linux_only = unittest.skipIf(WINDOWS, "pseudo-terminal / procfs test (Linux)")
windows_only = unittest.skipUnless(WINDOWS, "Windows backend test")


def lines_fit(sess):
    """Every rendered row must be exactly the terminal width (nothing wrapped)."""
    for row in sess.screen.display:
        assert len(row) == sess.cols, (len(row), row)


class Unit(unittest.TestCase):
    def test_theme_table(self):
        self.assertEqual(len(sonar.TABLE), 40)
        cats = dict(sonar.theme_categories())
        self.assertEqual(sorted(cats), ["gradient", "light", "mono", "sea"])
        self.assertTrue(all(len(v) == 10 for v in cats.values()))
        self.assertIn("tsunami", sonar.TABLE)

    def test_normalize_other_shapes(self):
        n = sonar.normalize_themes
        self.assertEqual(n({"a": ("sea", "#000000", "#ffffff", "#ff0000")})["a"][0], "sea")
        self.assertEqual(n({"a": {"category": "mono", "colors": ["#111", "#222", "#333"]}})["a"][0], "mono")
        self.assertEqual(n({"light": {"b": ((1, 2, 3), (4, 5, 6), (7, 8, 9))}})["b"], ("light", ((1, 2, 3), (4, 5, 6), (7, 8, 9))))
        self.assertIn("c", n([("c", "gradient", 0x112233, 0x445566, 0x778899)]))

    def test_theme_resolution(self):
        env = dict(os.environ)
        with tempfile.TemporaryDirectory() as d:
            try:
                os.environ["XDG_CONFIG_HOME"] = d
                for k in ("TSUNAMI", "TSUNAMI_THEME", "TSUNAMI_CONFIG", "TSUNAMI_THEME_PINNED"):
                    os.environ.pop(k, None)
                self.assertEqual(sonar.resolve_theme(), "tsunami")
                os.environ.update(TSUNAMI="1", TSUNAMI_THEME="aurora")
                self.assertEqual(sonar.resolve_theme(), "aurora")
                cfg = os.path.join(d, "tsunami.conf")
                with open(cfg, "w") as f:
                    f.write('font = "x"\ntheme = "ember"\n')
                os.environ["TSUNAMI_CONFIG"] = cfg
                self.assertEqual(sonar.resolve_theme(), "ember")      # config is fresher
                os.environ["TSUNAMI_THEME_PINNED"] = "1"
                self.assertEqual(sonar.resolve_theme(), "aurora")     # pinned: env wins
                sonar.save_theme("kelp")
                self.assertEqual(sonar.resolve_theme(), "kelp")       # explicit save wins
                self.assertEqual(sonar.resolve_theme("neon"), "neon")  # -t wins over all
            finally:
                os.environ.clear()
                os.environ.update(env)

    def test_keys(self):
        self.assertEqual(sonar.parse_keys(b"\x1b[A\x1b[6~jq\x1b\x1b[3~\x1b[Z\r"),
                         ["up", "pgdn", "j", "q", "esc", "del", "btab", "enter"])

    def test_cpu_percent_from_deltas(self):
        a, b = (1000, 800), (1100, 850)   # 100 jiffies elapsed, 50 idle
        self.assertAlmostEqual(sonar.CpuSampler._usage(a, b), 0.5)

    @linux_only
    def test_proc_cpu_and_vanishing(self):
        ps = sonar.ProcSampler()
        mem = sonar.read_meminfo()["total"]
        ps.sample(0, mem, 1000)
        busy = subprocess.Popen([sys.executable, "-c", "while True: pass"])
        try:
            time.sleep(0.3)
            ps.sample(0.3, mem, 1000)
            t0 = time.monotonic()
            time.sleep(1.0)
            ps.sample(time.monotonic() - t0, mem, 1001)
            p = next(p for p in ps.procs if p.pid == busy.pid)
            self.assertGreater(p.cpu, 60.0)
            self.assertLess(p.cpu, 110.0)
        finally:
            busy.kill()
            busy.wait()
        ps.sample(0.5, mem, 1002)
        self.assertNotIn(busy.pid, [p.pid for p in ps.procs])

    def test_layout_never_overflows(self):
        app = sonar.App("tsunami")
        app.sys.sample()
        app.sys.sample()
        for W, H in [(40, 10), (60, 16), (80, 24), (100, 30), (120, 40), (200, 60), (300, 90), (39, 9)]:
            cv = app.frame(W, H)
            self.assertEqual(len(cv.ch), H)
            self.assertTrue(all(len(r) == W for r in cv.ch))
            rects, prect, _ = app.layout(W, H)
            for _, x, y, w, h in rects + [("procs",) + prect]:
                self.assertLessEqual(x + w, W)
                self.assertLessEqual(y + h, H - 1)


@linux_only
class Live(unittest.TestCase):
    def run_size(self, cols, rows):
        s = Session(cols, rows, ["-t", "tsunami"])
        try:
            s.pump(1.6)
            txt = s.text()
            lines_fit(s)
            self.assertIn("sonar", txt.splitlines()[0])
            self.assertIn("processes", txt)
            self.assertIn("cpu", txt)
            self.assertIn("q quit", txt.splitlines()[-1] + "q quit" * (cols < 80))
            return s, txt
        finally:
            s.send("q", 0.2)
            s.wait_exit()
            s.close()

    def test_80x24(self):
        _, txt = self.run_size(80, 24)
        self.assertIn("╭─ cpu", txt)
        self.assertIn("╰", txt)

    def test_200x60(self):
        _, txt = self.run_size(200, 60)
        for panel in ("cpu", "mem", "net", "temps", "disks", "processes"):
            self.assertIn("╭─ " + panel, txt)

    def test_tiny_and_resize(self):
        s = Session(80, 24)
        try:
            s.pump(1.2)
            s.resize(50, 14)          # SIGWINCH
            os.kill(s.pid, 28)
            s.pump(0.8)
            lines_fit(s)
            self.assertIn("processes", s.text())
            self.assertIn("hidden", s.text().splitlines()[-1])
            s.resize(30, 8)
            os.kill(s.pid, 28)
            s.pump(0.8)
            self.assertIn("too small", s.text())
            s.resize(160, 48)
            os.kill(s.pid, 28)
            s.pump(0.8)
            lines_fit(s)
            self.assertIn("╭─ disks", s.text())
        finally:
            s.send("q", 0.2)
            s.wait_exit()
            s.close()

    def test_kill_sleep_and_restore(self):
        victim = subprocess.Popen(["sleep", "1000"])
        s = Session(100, 30)
        try:
            s.pump(1.5)
            s.send("/sleep")
            self.assertIn("filter › sleep", s.text())
            s.send("\r", 0.6)
            self.assertIn("sleep 1000", s.text())
            s.send("x", 0.4)
            last = s.text().splitlines()[-1]
            self.assertIn("kill sleep (%d)? SIGTERM" % victim.pid, last)
            self.assertIn("y/n", last)
            s.send("y", 0.6)
            self.assertIn("sent SIGTERM to sleep (%d)" % victim.pid, s.text())
            self.assertEqual(victim.wait(timeout=3), -15)
            s.send("q", 0.3)
            status = s.wait_exit()
            self.assertIsNotNone(status, "sonar did not exit")
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            raw = bytes(s.raw)
            # leaving: reset attrs, autowrap back on, cursor visible, main screen restored
            tail = raw[raw.rfind(b"\x1b[?1049h"):]
            for seq in (b"\x1b[?1049l", b"\x1b[?25h", b"\x1b[?7h", b"\x1b[0m"):
                self.assertIn(seq, tail)
            self.assertLess(tail.rfind(b"\x1b[?25l"), tail.rfind(b"\x1b[?25h"))
        finally:
            if victim.poll() is None:
                victim.kill()
            s.close()

    def test_sigkill_and_permission_denied(self):
        victim = subprocess.Popen(["sleep", "999"])
        s = Session(100, 30)
        try:
            s.pump(1.5)
            s.send("/sleep 999\r", 0.6)
            s.send("X", 0.3)
            self.assertIn("SIGKILL", s.text().splitlines()[-1])
            s.send("n", 0.3)
            self.assertIn("cancelled", s.text())
            self.assertIsNone(victim.poll())
            s.send("X", 0.3)
            s.send("y", 0.5)
            self.assertEqual(victim.wait(timeout=3), -9)
        finally:
            if victim.poll() is None:
                victim.kill()
            s.send("q", 0.2)
            s.wait_exit()
            s.close()

    def test_keys_tour(self):
        s = Session(120, 40)
        try:
            s.pump(1.5)
            s.send("s")
            self.assertIn("sort mem", s.text())
            s.send("r")
            self.assertIn("mem ▴", s.text())
            s.send("t")
            self.assertIn("tree", s.text())
            s.send("u")
            self.assertIn("mine", s.text())
            s.send("4")
            self.assertNotIn("╭─ temps", s.text())
            s.send("4")
            self.assertIn("╭─ temps", s.text())
            s.send("+")
            self.assertIn("0.75s", s.text())
            s.send("--")
            self.assertIn("1.5s", s.text())
            s.send("p")
            self.assertIn("paused", s.text())
            s.send("?")
            self.assertIn("theme picker", s.text())
            s.send(" ")
            self.assertNotIn("theme picker", s.text())
            s.send("jjj\x1b[B\x1b[5~\x1b[F\x1b[H")
            lines_fit(s)
        finally:
            s.send("q", 0.2)
            s.wait_exit()
            s.close()

    def test_theme_picker_saves(self):
        with tempfile.TemporaryDirectory() as d:
            s = Session(100, 30, ["-t", "tsunami"], env={"XDG_CONFIG_HOME": d})
            try:
                s.pump(1.2)
                s.send("c")
                self.assertIn("‹  tsunami  ›", s.text())
                s.send("\x1b[C")
                self.assertIn("‹  abyss  ›", s.text())
                s.send("\t")
                self.assertIn("‹  aurora  ›", s.text())
                s.send("\x1b", 0.3)          # cancel: back to tsunami, nothing saved
                self.assertFalse(os.path.exists(os.path.join(d, "sonar", "config")))
                s.send("c\t\t\x1b[C\r", 0.5)  # mono → 2nd theme, save
                self.assertIn("saved", s.text())
                self.assertEqual(sonar.theme_from_file(os.path.join(d, "sonar", "config")), "slate")
            finally:
                s.send("q", 0.2)
                s.wait_exit()
                s.close()

    def test_ctrl_c_restores(self):
        s = Session(80, 24)
        s.pump(1.0)
        s.send("\x03", 0.3)
        self.assertIsNotNone(s.wait_exit())
        self.assertTrue(bytes(s.raw).rstrip().endswith(b"\x1b[?1049l"))
        s.close()


class Cli(unittest.TestCase):
    def run_cli(self, *args, env=None):
        r = subprocess.run([sys.executable, SONAR, *args], capture_output=True,
                           env=dict(os.environ, **(env or {})), timeout=30)
        r.stdout = r.stdout.decode("utf-8", "replace")
        r.stderr = r.stderr.decode("utf-8", "replace")
        return r

    def test_once_and_flags(self):
        r = self.run_cli("--once", "--no-color", env={"COLUMNS": "80", "LINES": "24"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(";38;2;", r.stdout)
        self.assertEqual(len(r.stdout.splitlines()), 24)
        self.assertIn("sonar 1.0.0", self.run_cli("-V").stdout)
        self.assertIn("tsunami", self.run_cli("-l").stdout)
        self.assertEqual(self.run_cli("-t", "nope", "--once").returncode, 2)
        self.assertEqual(self.run_cli("-i", "9", "--once").returncode, 2)
        self.assertIn(";38;2;", self.run_cli("--once", "-t", "ember", env={"COLUMNS": "90", "LINES": "28"}).stdout)


@windows_only
class WindowsBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sys = sonar.System()
        cls.sys.sample()
        time.sleep(0.6)
        cls.sys.sample()

    def test_cpu(self):
        s = self.sys
        self.assertEqual(len(s.cpu.cores), os.cpu_count())
        self.assertTrue(0.0 <= s.cpu.total <= 1.0)
        self.assertTrue(all(0.0 <= c <= 1.0 for c in s.cpu.cores))
        self.assertIsNone(s.load)
        self.assertGreater(s.uptime, 0)

    def test_memory(self):
        m = self.sys.mem
        self.assertGreater(m["total"], 256 << 20)
        self.assertTrue(0 < m["used"] < m["total"])
        self.assertTrue(0 <= m["cache"] <= m["avail"] <= m["total"])
        self.assertLessEqual(m["swap_used"], m["swap_total"])

    def test_disks(self):
        parts = {p["mnt"]: p for p in self.sys.disk.parts}
        self.assertIn("C:", parts)
        c = parts["C:"]
        self.assertGreater(c["total"], 0)
        self.assertTrue(0 < c["used"] <= c["total"])

    def test_network(self):
        self.assertTrue(self.sys.net.iface, "no active interface detected")
        self.assertGreater(self.sys.net.rx_total + self.sys.net.tx_total, 0)

    def test_processes(self):
        procs = {p.pid: p for p in self.sys.procs.procs}
        me = procs.get(os.getpid())
        self.assertIsNotNone(me, "own process missing")
        self.assertTrue(me.name.lower().startswith("python"), me.name)
        self.assertIn("test_sonar", me.cmd)
        self.assertEqual(me.uid, 0, "own process should count as 'mine' (user %r)" % me.user)
        self.assertGreater(me.rss, 1 << 20)
        self.assertEqual(me.ppid, os.getppid())

    def test_cpu_percent_of_busy_child(self):
        ps = sonar.WinProcSampler()
        mem = self.sys.mem["total"]
        busy = subprocess.Popen([sys.executable, "-c", "while True: pass"])
        try:
            time.sleep(0.5)
            ps.sample(0, mem, 0)
            t0 = time.monotonic()
            time.sleep(1.5)
            ps.sample(time.monotonic() - t0, mem, 0)
            p = next(p for p in ps.procs if p.pid == busy.pid)
            self.assertGreater(p.cpu, 50.0)
            self.assertLess(p.cpu, 115.0)
        finally:
            busy.kill()
            busy.wait()
        ps.sample(0.5, mem, 0)
        self.assertNotIn(busy.pid, [p.pid for p in ps.procs])

    def test_kill_from_app(self):
        victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        try:
            app = sonar.App("tsunami")
            app.sys.sample()
            app.filter = str(victim.pid)  # no-op filter, but exercise the view
            app.filter = ""
            app.kill(victim.pid, "python", "terminate")
            self.assertIn("terminated", app.msg)
            self.assertEqual(victim.wait(timeout=5), 1)
            app.kill(victim.pid, "python", "terminate")
            self.assertTrue(app.msg_err)
        finally:
            if victim.poll() is None:
                victim.kill()

    def test_permission_denied_is_reported(self):
        app = sonar.App("tsunami")
        csrss = [p for p in app.sys.procs.procs if p.name.lower() == "csrss"] or \
            [p for p in (app.sys.sample() or app.sys.procs.procs) if p.name.lower() == "csrss"]
        self.assertTrue(csrss, "csrss.exe not listed")
        app.kill(csrss[0].pid, "csrss", "terminate")
        self.assertTrue(app.msg_err)
        self.assertIn("permission denied", app.msg)

    def test_frames_fit(self):
        app = sonar.App("tsunami")
        app.sys = self.sys
        for W, H in [(80, 24), (120, 40), (200, 60)]:
            cv = app.frame(W, H)
            self.assertTrue(all(len(r) == W for r in cv.ch))
        app.tree = True
        app.frame(120, 40)
        self.assertTrue(app.view)

    def test_key_parsing(self):
        self.assertEqual(sonar.parse_win_keys(["\xe0", "H", "\x00", "P", "x", "\r", "\x1b", "\x00", "\x0f"]),
                         ["up", "down", "x", "enter", "esc", "btab"])


def _ci_main():
    """On GitHub Actions, turn failures into annotations (readable without logs)."""
    res = unittest.main(verbosity=2, exit=False).result
    for test, tb in res.failures + res.errors:
        msg = tb.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print("::error title=%s::%s" % (test.id(), msg))
    sys.exit(not res.wasSuccessful())


if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS"):
        _ci_main()
    unittest.main(verbosity=2)
