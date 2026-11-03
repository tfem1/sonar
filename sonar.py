#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
#  sonar — a minimal, beautiful system monitor for the terminal (Linux & Windows).
#  Part of the waves (fetch) / tsunami (terminal) family: same look, same themes.
#
#  Single file, Python 3 standard library only. On Linux it reads /proc and /sys
#  directly; on Windows it calls the Win32 / NT APIs through ctypes. Renders with
#  truecolor ANSI escapes. No curses, no psutil.
# ─────────────────────────────────────────────────────────────────────────────
"""sonar - a minimal, beautiful terminal system monitor for Linux and Windows."""

import argparse
import atexit
import json
import math
import os
import re
import select
import signal
import socket
import sys
import time
import unicodedata
from collections import deque

WINDOWS = os.name == "nt"
if WINDOWS:
    import ctypes
    import msvcrt
    from ctypes import wintypes
else:
    import pwd
    import termios
    import tty

VERSION = "1.0.0"

# ── themes:begin ──
# Shared theme table (waves / tsunami / sonar).
# name: (category, low, mid, high) — three accent colors used for gradients,
# from "calm" (low values) to "intense" (high values).
THEMES = {
    # sea
    "tsunami":  ("sea", "#1e6fd9", "#00b4d8", "#7df9ff"),
    "abyss":    ("sea", "#283593", "#3f51b5", "#8c9eff"),
    "lagoon":   ("sea", "#00897b", "#26c6da", "#b2ebf2"),
    "reef":     ("sea", "#0077b6", "#48cae4", "#ff8fab"),
    "tide":     ("sea", "#2563eb", "#38bdf8", "#e0f2fe"),
    "coral":    ("sea", "#ef476f", "#ff8c69", "#ffd6a5"),
    "kelp":     ("sea", "#2d6a4f", "#52b788", "#b7e4c7"),
    "storm":    ("sea", "#4a5568", "#7a8aa3", "#cbd5e0"),
    "harbor":   ("sea", "#2a6f97", "#2a9d8f", "#e9c46a"),
    "riptide":  ("sea", "#0b7285", "#14b8a6", "#99f6e4"),
    # gradient
    "aurora":   ("gradient", "#7c3aed", "#22d3ee", "#4ade80"),
    "sunset":   ("gradient", "#f72585", "#ff7b00", "#ffd60a"),
    "ember":    ("gradient", "#c1121f", "#e85d04", "#ffba08"),
    "neon":     ("gradient", "#ff00c8", "#7b2ff7", "#00f0ff"),
    "vapor":    ("gradient", "#ff71ce", "#b967ff", "#01cdfe"),
    "citrus":   ("gradient", "#a3e635", "#facc15", "#fb923c"),
    "berry":    ("gradient", "#7b2cbf", "#c77dff", "#ff6fae"),
    "nebula":   ("gradient", "#4361ee", "#7209b7", "#f72585"),
    "dusk":     ("gradient", "#5c7aa8", "#b56576", "#eaac8b"),
    "peach":    ("gradient", "#ff6a88", "#ff9a8b", "#ffd3a5"),
    # mono
    "ink":      ("mono", "#5c6370", "#9aa0aa", "#e6e6e6"),
    "slate":    ("mono", "#475569", "#94a3b8", "#e2e8f0"),
    "mint":     ("mono", "#047857", "#10b981", "#6ee7b7"),
    "amber":    ("mono", "#b45309", "#f59e0b", "#fcd34d"),
    "rose":     ("mono", "#be123c", "#f43f5e", "#fda4af"),
    "ice":      ("mono", "#0369a1", "#38bdf8", "#bae6fd"),
    "lime":     ("mono", "#4d7c0f", "#84cc16", "#d9f99d"),
    "violet":   ("mono", "#6d28d9", "#8b5cf6", "#c4b5fd"),
    "copper":   ("mono", "#9a3412", "#ea580c", "#fdba74"),
    "cobalt":   ("mono", "#1e40af", "#3b82f6", "#bfdbfe"),
    # light
    "paper":    ("light", "#94a3b8", "#475569", "#0f172a"),
    "foam":     ("light", "#67e8f9", "#0891b2", "#164e63"),
    "shell":    ("light", "#fda4af", "#e11d48", "#881337"),
    "linen":    ("light", "#d6b98c", "#a47148", "#5c3d2e"),
    "mist":     ("light", "#a5b4fc", "#6366f1", "#312e81"),
    "blossom":  ("light", "#f9a8d4", "#db2777", "#831843"),
    "meadow":   ("light", "#86efac", "#16a34a", "#14532d"),
    "sky":      ("light", "#93c5fd", "#2563eb", "#1e3a8a"),
    "lavender": ("light", "#c4b5fd", "#7c3aed", "#4c1d95"),
    "dune":     ("light", "#fcd34d", "#d97706", "#78350f"),
}
# ── themes:end ──

DEFAULT_THEME = "tsunami"
CATEGORY_ORDER = ("sea", "gradient", "mono", "light")


# ═════════════════════════════════════════════════════════════════════════════
#  Colors & themes
# ═════════════════════════════════════════════════════════════════════════════

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def to_rgb(c):
    """Accept '#rrggbb', 'rrggbb', '#rgb', (r, g, b) or 0xRRGGBB."""
    if isinstance(c, (tuple, list)) and len(c) == 3 and all(isinstance(v, (int, float)) for v in c):
        return tuple(max(0, min(255, int(v))) for v in c)
    if isinstance(c, int):
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255)
    if isinstance(c, str) and _HEX_RE.match(c.strip()):
        s = c.strip().lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    raise ValueError("not a color: %r" % (c,))


def _is_color(c):
    try:
        to_rgb(c)
        return True
    except (ValueError, TypeError):
        return False


def normalize_themes(raw):
    """Turn a theme table into {name: (category, (rgb, rgb, rgb))}.

    Tolerates the common shapes a shared table may have, so the block from
    tsunami.py can be pasted between the markers unchanged:
      {name: (cat, c1, c2, c3)}            {name: (c1, c2, c3)}
      {name: (cat, [c1, c2, c3])}          {name: {"category": .., "colors": [..]}}
      {category: {name: colors}}           [(name, cat, c1, c2, c3), ...]
    """
    out = {}

    def add(name, cat, cols):
        cols = [to_rgb(c) for c in cols if _is_color(c)][:3]
        if not cols:
            return
        while len(cols) < 3:
            cols.append(cols[-1])
        out[str(name)] = (str(cat or "sea").lower(), tuple(cols))

    def flat_colors(v):
        res = []
        for item in v:
            if _is_color(item):
                res.append(item)
            elif isinstance(item, (list, tuple)):
                res.extend(flat_colors(item))
        return res

    def from_value(name, v, cat=None):
        if isinstance(v, dict):
            c = v.get("category") or v.get("cat") or v.get("group") or v.get("kind") or cat
            cols = None
            for k in ("colors", "accents", "accent", "gradient", "grad", "palette", "colours"):
                if k in v:
                    cols = v[k]
                    break
            if cols is None:
                cols = [v[k] for k in ("c1", "c2", "c3", "a1", "a2", "a3") if k in v]
            if isinstance(cols, (list, tuple)) and cols:
                add(name, c, flat_colors(cols))
                return True
            if all(isinstance(x, (dict, list, tuple)) for x in v.values()):  # {cat: {name: ..}}
                for n2, v2 in v.items():
                    from_value(n2, v2, name)
                return True
            return False
        if isinstance(v, (list, tuple)):
            cats = [i for i in v if isinstance(i, str) and not _is_color(i)]
            add(name, cats[0] if cats else cat, flat_colors(v))
            return True
        return False

    if isinstance(raw, dict):
        for name, v in raw.items():
            from_value(name, v)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict) and "name" in item:
                from_value(item["name"], item)
            elif isinstance(item, (list, tuple)) and item and isinstance(item[0], str):
                from_value(item[0], list(item[1:]))
    return out


def _theme_table():
    g = globals()
    for var in ("THEMES", "THEME_TABLE", "TSUNAMI_THEMES", "themes"):
        if var in g:
            table = normalize_themes(g[var])
            if table:
                return table
    return {DEFAULT_THEME: ("sea", (to_rgb("#1e6fd9"), to_rgb("#00b4d8"), to_rgb("#7df9ff")))}


TABLE = _theme_table()


def theme_categories():
    cats = {}
    for name, (cat, _) in TABLE.items():
        cats.setdefault(cat, []).append(name)
    order = [c for c in CATEGORY_ORDER if c in cats] + [c for c in cats if c not in CATEGORY_ORDER]
    return [(c, cats[c]) for c in order]


def mix(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


# style = (fg, bg, attrs);  attrs: bit 1 bold, 2 dim, 4 reverse, 8 underline
BOLD, DIM, REV, ULINE = 1, 2, 4, 8
PLAIN = (None, None, 0)


class Theme:
    def __init__(self, name):
        if name not in TABLE:
            name = DEFAULT_THEME if DEFAULT_THEME in TABLE else next(iter(TABLE))
        self.name = name
        self.cat, self.c = TABLE[name]
        self.light = self.cat == "light"
        self.bg = (248, 248, 246) if self.light else (16, 18, 24)
        c1, c2, c3 = self.c
        self.border = mix(c2, self.bg, 0.55)
        self.title = c2
        self.track = mix(c2, self.bg, 0.78)
        self.sel = mix(c2, self.bg, 0.72)
        self.warm = (205, 140, 0) if self.light else (245, 195, 75)
        self.hot = (205, 35, 35) if self.light else (245, 80, 80)
        self._grad = [self.grad(i / 63.0) for i in range(64)]

    def grad(self, t):
        t = 0.0 if t < 0 else 1.0 if t > 1 else t
        c1, c2, c3 = self.c
        return mix(c1, c2, t * 2) if t < 0.5 else mix(c2, c3, (t - 0.5) * 2)

    def g(self, t):
        """Cached gradient lookup (64 steps)."""
        t = 0.0 if t < 0 else 1.0 if t > 1 else t
        return self._grad[int(t * 63)]

    def heat(self, t):
        """Cool accent → warm → hot red."""
        t = 0.0 if t < 0 else 1.0 if t > 1 else t
        if t < 0.55:
            return mix(self.c[1], self.warm, t / 0.55)
        return mix(self.warm, self.hot, (t - 0.55) / 0.45)


# ═════════════════════════════════════════════════════════════════════════════
#  Config & default theme resolution
# ═════════════════════════════════════════════════════════════════════════════

def config_path():
    base = os.environ.get("XDG_CONFIG_HOME")
    if not base and WINDOWS:
        base = os.environ.get("APPDATA")
    base = base or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "sonar", "config")


_THEME_LINE = re.compile(r"""^\s*["']?theme["']?\s*[=:]\s*["']?([\w.+-]+)""", re.I | re.M)


def theme_from_file(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("theme"), str):
            return data["theme"]
    except ValueError:
        pass
    m = _THEME_LINE.search(text)
    return m.group(1) if m else None


def resolve_theme(cli_theme=None):
    """-t  >  ~/.config/sonar/config  >  tsunami's theme (inside tsunami)  >  'tsunami'."""
    if cli_theme:
        return cli_theme
    saved = theme_from_file(config_path())
    if saved and saved in TABLE:
        return saved
    if "TSUNAMI" in os.environ:
        cand = None
        if "TSUNAMI_THEME_PINNED" not in os.environ and os.environ.get("TSUNAMI_CONFIG"):
            cand = theme_from_file(os.path.expanduser(os.environ["TSUNAMI_CONFIG"]))
        cand = cand or os.environ.get("TSUNAMI_THEME")
        if cand and cand in TABLE:
            return cand
    return DEFAULT_THEME


def save_theme(name):
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if not _THEME_LINE.match(l)]
    except OSError:
        pass
    lines.insert(0, "theme = %s" % name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    return path


# ═════════════════════════════════════════════════════════════════════════════
#  Data: readers for /proc and /sys
# ═════════════════════════════════════════════════════════════════════════════

CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def current_user():
    if WINDOWS:
        return os.environ.get("USERNAME") or "me"
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return str(os.getuid())


def my_uid():
    """Owner id used by the 'mine' filter (on Windows the backend marks own processes 0)."""
    return 0 if WINDOWS else os.getuid()
HIST = 1024
PF_KTHREAD = 0x00200000


def read(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return None


def read_int(path):
    s = read(path)
    try:
        return int(s.strip()) if s else None
    except ValueError:
        return None


def natural_key(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def read_cpu_times():
    """{'cpu': (total, idle), 'cpu0': ...} from /proc/stat."""
    out = {}
    text = read("/proc/stat") or ""
    for line in text.splitlines():
        if not line.startswith("cpu"):
            break
        parts = line.split()
        vals = [int(v) for v in parts[1:9]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        out[parts[0]] = (sum(vals), idle)
    return out


class CpuSampler:
    def __init__(self):
        self.prev = read_cpu_times()
        self.total = 0.0
        self.cores = [0.0] * max(1, len(self.prev) - 1)
        self.freq_paths = sorted(
            (p for p in (f"/sys/devices/system/cpu/{d}/cpufreq/scaling_cur_freq"
                         for d in os.listdir("/sys/devices/system/cpu") if re.fullmatch(r"cpu\d+", d))
             if os.path.exists(p)), key=natural_key) if os.path.isdir("/sys/devices/system/cpu") else []
        self.freq = None

    @staticmethod
    def _usage(a, b):
        dt, di = b[0] - a[0], b[1] - a[1]
        return 0.0 if dt <= 0 else max(0.0, min(1.0, 1.0 - di / dt))

    def sample(self):
        cur = read_cpu_times()
        if "cpu" in cur and "cpu" in self.prev:
            self.total = self._usage(self.prev["cpu"], cur["cpu"])
        names = sorted((k for k in cur if k != "cpu"), key=natural_key)
        self.cores = [self._usage(self.prev[k], cur[k]) if k in self.prev else 0.0 for k in names] or [self.total]
        self.prev = cur
        self.freq = self._read_freq()

    def _read_freq(self):
        vals = [v for v in (read_int(p) for p in self.freq_paths) if v]
        if vals:
            return sum(vals) / len(vals) / 1000.0  # MHz
        text = read("/proc/cpuinfo") or ""
        mhz = [float(m) for m in re.findall(r"^cpu MHz\s*:\s*([\d.]+)", text, re.M)]
        return sum(mhz) / len(mhz) if mhz else None


def read_meminfo():
    m = {}
    for line in (read("/proc/meminfo") or "").splitlines():
        k, _, v = line.partition(":")
        try:
            m[k] = int(v.split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    total = m.get("MemTotal", 0)
    free = m.get("MemFree", 0)
    cache = m.get("Buffers", 0) + m.get("Cached", 0) + m.get("SReclaimable", 0) - m.get("Shmem", 0)
    cache = max(0, cache)
    avail = m.get("MemAvailable", free + cache)
    used = max(0, total - free - cache)
    stotal = m.get("SwapTotal", 0)
    sused = max(0, stotal - m.get("SwapFree", 0) - m.get("SwapCached", 0))
    return {"total": total, "used": used, "cache": cache, "avail": avail, "free": free,
            "swap_total": stotal, "swap_used": sused}


CHIPS = [  # (regex on hwmon name, group, readable name)
    (r"coretemp|k10temp|zenpower|cpu[_-]?thermal|x86_pkg_temp|soc[_-]?thermal", "cpu", "CPU"),
    (r"amdgpu|radeon|nouveau|nvidia", "gpu", "GPU"),
    (r"i915|xe$", "gpu", "iGPU"),
    (r"nvme", "disk", "NVMe"),
    (r"drivetemp|sata|ata", "disk", "Disk"),
    (r"spd5118|jc42", "ram", "RAM"),
    (r"iwlwifi|ath\d+k|mt79|rtw|brcm", "net", "Wi-Fi"),
    (r"acpitz", "board", "ACPI"),
    (r"pch_", "board", "PCH"),
    (r"thinkpad", "board", "ThinkPad"),
    (r"dell_smm", "board", "Dell"),
    (r"nct\d+|it8\d+|f71|asus|gigabyte", "board", "Board"),
    (r"BAT|battery", "battery", "Battery"),
]
GROUP_ORDER = {"cpu": 0, "gpu": 1, "disk": 2, "ram": 3, "net": 4, "board": 5, "battery": 6, "other": 7}


def pretty_chip(name):
    for rx, group, pretty in CHIPS:
        if re.match(rx, name, re.I):
            return group, pretty
    return "other", name


def pretty_label(group, label):
    l = label.strip()
    if not l or l.lower() in ("composite", "temp1"):
        return ""
    if re.match(r"package id \d+", l, re.I):
        return "package"
    return l.lower() if re.match(r"(core|sensor|edge|junction|mem)\b", l, re.I) else l


class Sensors:
    """All temperature sensors under /sys/class/hwmon (thermal zones as fallback)."""

    def __init__(self):
        self.items = []  # dicts: name, group, path, high
        self.scan()

    def scan(self):
        items = []
        base = "/sys/class/hwmon"
        try:
            entries = sorted(os.listdir(base), key=natural_key)
        except OSError:
            entries = []
        for e in entries:
            d = os.path.join(base, e)
            chip = (read(d + "/name") or e).strip()
            group, pretty = pretty_chip(chip)
            try:
                files = os.listdir(d)
            except OSError:
                continue
            for f in sorted((f for f in files if re.fullmatch(r"temp\d+_input", f)), key=natural_key):
                idx = f[4:-6]
                label = pretty_label(group, read(f"{d}/temp{idx}_label") or "")
                high = read_int(f"{d}/temp{idx}_max") or read_int(f"{d}/temp{idx}_crit")
                if high is not None and not (30000 <= high <= 150000):
                    high = None
                items.append({"name": (pretty + " " + label).strip(), "group": group,
                              "path": f"{d}/{f}", "high": high / 1000 if high else None})
        if not items:
            tbase = "/sys/class/thermal"
            try:
                zones = sorted((z for z in os.listdir(tbase) if z.startswith("thermal_zone")), key=natural_key)
            except OSError:
                zones = []
            for z in zones:
                typ = (read(f"{tbase}/{z}/type") or z).strip()
                group, pretty = pretty_chip(typ)
                items.append({"name": pretty if group != "other" else typ, "group": group,
                              "path": f"{tbase}/{z}/temp", "high": None})
        items.sort(key=lambda it: GROUP_ORDER.get(it["group"], 9))
        seen = {}
        for it in items:  # make names unique: "NVMe", "NVMe 2", ...
            n = seen.get(it["name"], 0) + 1
            seen[it["name"]] = n
            if n > 1:
                it["name"] = "%s %d" % (it["name"], n)
        self.items = items

    def read(self):
        out = []
        for it in self.items:
            v = read_int(it["path"])
            if v is None or v <= -40000 or v >= 200000:
                continue
            out.append((it["name"], it["group"], v / 1000.0, it["high"]))
        return out


def cpu_temperature(temps):
    cpu = [t for t in temps if t[1] == "cpu"]
    for name, _, val, _ in cpu:
        if re.search(r"package|tctl|tdie", name, re.I):
            return val
    return max((t[2] for t in cpu), default=None)


def read_netdev():
    out = {}
    for line in (read("/proc/net/dev") or "").splitlines()[2:]:
        iface, _, rest = line.partition(":")
        f = rest.split()
        if len(f) >= 9:
            out[iface.strip()] = (int(f[0]), int(f[8]))
    return out


def default_route_iface():
    for line in (read("/proc/net/route") or "").splitlines()[1:]:
        f = line.split()
        if len(f) > 7 and f[1] == "00000000" and f[7] == "00000000":
            return f[0]
    return None


class NetSampler:
    def __init__(self):
        self.iface = None
        self.prev = None
        self.up = self.down = 0.0
        self.tx_total = self.rx_total = 0
        self.n = 0

    def detect(self, stats):
        iface = default_route_iface()
        if iface in stats:
            return iface
        cands = [(rx + tx, i) for i, (rx, tx) in stats.items() if i != "lo"]
        return max(cands)[1] if cands else None

    def sample(self, dt):
        stats = read_netdev()
        if self.n % 10 == 0 or self.iface not in stats:
            iface = self.detect(stats)
            if iface != self.iface:
                self.iface, self.prev = iface, None
        self.n += 1
        if not self.iface:
            self.up = self.down = 0.0
            return
        rx, tx = stats[self.iface]
        self.rx_total, self.tx_total = rx, tx
        if self.prev and dt > 0:
            self.down = max(0.0, (rx - self.prev[0]) / dt)
            self.up = max(0.0, (tx - self.prev[1]) / dt)
        self.prev = (rx, tx)


REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "vfat", "exfat", "ntfs", "ntfs3",
           "fuseblk", "bcachefs", "jfs", "reiserfs", "hfsplus", "apfs", "overlay", "nilfs2"}
SKIP_MNT = ("/proc", "/sys", "/dev", "/snap", "/var/lib/docker", "/var/lib/containers", "/run/user")


def _unescape_mount(s):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def read_mounts():
    parts, seen = [], set()
    for line in (read("/proc/mounts") or "").splitlines():
        f = line.split()
        if len(f) < 3:
            continue
        dev, mnt, fs = f[0], _unescape_mount(f[1]), f[2]
        if fs not in REAL_FS or (fs == "overlay" and mnt != "/"):
            continue
        if mnt != "/" and any(mnt == p or mnt.startswith(p + "/") for p in SKIP_MNT):
            continue
        key = dev if dev.startswith("/dev/") else (dev, mnt)
        if key in seen or not os.path.isdir(mnt):
            continue
        seen.add(key)
        kname = os.path.basename(os.path.realpath(dev)) if dev.startswith("/dev/") else None
        parts.append({"dev": dev, "mnt": mnt, "fs": fs, "kname": kname})
    parts.sort(key=lambda p: (p["mnt"] != "/", p["mnt"]))
    return parts


def read_diskstats():
    out = {}
    for line in (read("/proc/diskstats") or "").splitlines():
        f = line.split()
        if len(f) >= 10:
            out[f[2]] = (int(f[5]) * 512, int(f[9]) * 512)
    return out


def physical_disks():
    try:
        names = os.listdir("/sys/block")
    except OSError:
        return []
    phys = [n for n in names if os.path.exists(f"/sys/block/{n}/device")
            and not re.match(r"(loop|ram|zram|dm-|md|sr)", n)]
    return phys or [n for n in names if not re.match(r"(loop|ram|zram|dm-|md|sr)", n)]


class DiskSampler:
    def __init__(self):
        self.parts = []
        self.disks = physical_disks()
        self.prev = None
        self.read_rate = self.write_rate = None
        self.part_rates = {}
        self.n = 0

    def sample(self, dt):
        if self.n % 5 == 0:
            self.parts = read_mounts()
        self.n += 1
        for p in self.parts:
            try:
                st = os.statvfs(p["mnt"])
                p["total"] = st.f_blocks * st.f_frsize
                p["avail"] = st.f_bavail * st.f_frsize
                p["used"] = (st.f_blocks - st.f_bfree) * st.f_frsize
            except OSError:
                p["total"] = 0
        stats = read_diskstats()
        if not stats:
            self.read_rate = self.write_rate = None
            return
        if self.prev is not None and dt > 0:
            def rate(name):
                if name in stats and name in self.prev:
                    return (max(0, stats[name][0] - self.prev[name][0]) / dt,
                            max(0, stats[name][1] - self.prev[name][1]) / dt)
                return None
            rs = [r for r in (rate(d) for d in self.disks) if r]
            self.read_rate = sum(r[0] for r in rs) if rs else None
            self.write_rate = sum(r[1] for r in rs) if rs else None
            self.part_rates = {p["kname"]: rate(p["kname"]) for p in self.parts if p["kname"]}
        self.prev = stats


class Proc:
    __slots__ = ("pid", "ppid", "name", "cmd", "user", "uid", "state", "ticks", "cpu", "rss", "mem",
                 "start", "threads")


class ProcSampler:
    """Process table with CPU% from deltas of utime+stime between two reads."""

    def __init__(self):
        self.prev = {}   # pid -> (starttime, ticks)
        self.cache = {}  # pid -> (starttime, comm, name, cmd, uid)
        self.users = {}
        self.procs = []
        self.kthreads = 0

    def user(self, uid):
        u = self.users.get(uid)
        if u is None:
            try:
                u = pwd.getpwuid(uid).pw_name
            except KeyError:
                u = str(uid)
            self.users[uid] = u
        return u

    def sample(self, dt, memtotal, uptime):
        procs, prev, cache = [], {}, {}
        kthreads = 0
        try:
            pids = [int(p) for p in os.listdir("/proc") if p.isdigit()]
        except OSError:
            pids = []
        for pid in pids:
            try:
                with open("/proc/%d/stat" % pid, "rb") as f:
                    data = f.read()
            except OSError:
                continue  # vanished between listdir and open
            lp, rp = data.find(b"("), data.rfind(b")")
            f = data[rp + 2:].split()
            if lp < 0 or rp < 0 or len(f) < 22:
                continue
            if int(f[6]) & PF_KTHREAD:
                kthreads += 1
                continue
            comm = data[lp + 1:rp].decode("utf-8", "replace")
            start, ticks = int(f[19]), int(f[11]) + int(f[12])
            p = Proc()
            p.pid, p.ppid, p.state = pid, int(f[1]), f[0].decode()
            p.threads, p.start, p.ticks = int(f[17]), start, ticks
            p.rss = max(0, int(f[21])) * PAGE
            p.mem = 100.0 * p.rss / memtotal if memtotal else 0.0
            old = self.prev.get(pid)
            if old and old[0] == start and dt > 0:
                p.cpu = max(0.0, (ticks - old[1]) / CLK_TCK / dt * 100.0)
            else:  # new process (or pid reuse): use its lifetime average
                age = uptime - start / CLK_TCK
                p.cpu = ticks / CLK_TCK / age * 100.0 if age > 1 else 0.0
            prev[pid] = (start, ticks)
            c = self.cache.get(pid)
            if not c or c[0] != start or c[1] != comm:
                c = self._describe(pid, start, comm)
                if c is None:
                    continue
            cache[pid] = c
            p.name, p.cmd, p.uid = c[2], c[3], c[4]
            p.user = self.user(p.uid)
            procs.append(p)
        self.prev, self.cache, self.procs, self.kthreads = prev, cache, procs, kthreads

    @staticmethod
    def _describe(pid, start, comm):
        try:
            uid = os.stat("/proc/%d" % pid).st_uid
        except OSError:
            return None
        raw = read("/proc/%d/cmdline" % pid) or ""
        args = [a for a in raw.split("\0") if a]
        cmd = " ".join(args) if args else "[%s]" % comm
        name = comm
        if args and len(comm) >= 15:  # comm is truncated to 15 chars by the kernel
            base = os.path.basename(args[0].split(" ")[0])
            if base.startswith(comm):
                name = base
        return (start, comm, name, cmd, uid)


# ═════════════════════════════════════════════════════════════════════════════
#  Data: Windows backend (Win32 / NT APIs through ctypes, no admin rights needed)
# ═════════════════════════════════════════════════════════════════════════════

if WINDOWS:
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)
    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _iphlp = ctypes.WinDLL("iphlpapi")
    try:
        _powrprof = ctypes.WinDLL("powrprof")
    except OSError:
        _powrprof = None

    HANDLE, DWORD, ULONG = ctypes.c_void_p, wintypes.DWORD, wintypes.ULONG
    STATUS_INFO_LENGTH_MISMATCH = -1073741820  # 0xC0000004 as NTSTATUS
    PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_TERMINATE, TOKEN_QUERY = 0x1000, 0x0001, 0x0008

    class FILETIME(ctypes.Structure):
        _fields_ = [("lo", DWORD), ("hi", DWORD)]

        def value(self):
            return (self.hi << 32) | self.lo

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", DWORD), ("dwMemoryLoad", DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    class PERFORMANCE_INFORMATION(ctypes.Structure):
        _fields_ = [("cb", DWORD)] + [(n, ctypes.c_size_t) for n in (
            "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal", "PhysicalAvailable", "SystemCache",
            "KernelTotal", "KernelPaged", "KernelNonpaged", "PageSize")] + [
            ("HandleCount", DWORD), ("ProcessCount", DWORD), ("ThreadCount", DWORD)]

    class SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION(ctypes.Structure):
        _fields_ = [("IdleTime", ctypes.c_longlong), ("KernelTime", ctypes.c_longlong),
                    ("UserTime", ctypes.c_longlong), ("DpcTime", ctypes.c_longlong),
                    ("InterruptTime", ctypes.c_longlong), ("InterruptCount", ULONG)]

    class PROCESSOR_POWER_INFORMATION(ctypes.Structure):
        _fields_ = [(n, ULONG) for n in ("Number", "MaxMhz", "CurrentMhz", "MhzLimit", "MaxIdleState",
                                         "CurrentIdleState")]

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]

    class SYSTEM_PROCESS_INFORMATION(ctypes.Structure):  # documented leading part of the record
        _fields_ = [("NextEntryOffset", ULONG), ("NumberOfThreads", ULONG), ("WorkingSetPrivateSize", ctypes.c_longlong),
                    ("HardFaultCount", ULONG), ("NumberOfThreadsHighWatermark", ULONG),
                    ("CycleTime", ctypes.c_ulonglong), ("CreateTime", ctypes.c_longlong),
                    ("UserTime", ctypes.c_longlong), ("KernelTime", ctypes.c_longlong),
                    ("ImageName", UNICODE_STRING), ("BasePriority", wintypes.LONG),
                    ("UniqueProcessId", ctypes.c_void_p), ("InheritedFromUniqueProcessId", ctypes.c_void_p),
                    ("HandleCount", ULONG), ("SessionId", ULONG), ("UniqueProcessKey", ctypes.c_void_p),
                    ("PeakVirtualSize", ctypes.c_size_t), ("VirtualSize", ctypes.c_size_t),
                    ("PageFaultCount", ULONG), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t)]

    _U64 = ctypes.c_ulonglong

    class MIB_IF_ROW2(ctypes.Structure):
        _fields_ = [("InterfaceLuid", _U64), ("InterfaceIndex", ULONG), ("InterfaceGuid", ctypes.c_ubyte * 16),
                    ("Alias", ctypes.c_wchar * 257), ("Description", ctypes.c_wchar * 257),
                    ("PhysicalAddressLength", ULONG), ("PhysicalAddress", ctypes.c_ubyte * 32),
                    ("PermanentPhysicalAddress", ctypes.c_ubyte * 32), ("Mtu", ULONG), ("Type", ULONG),
                    ("TunnelType", ctypes.c_int), ("MediaType", ctypes.c_int), ("PhysicalMediumType", ctypes.c_int),
                    ("AccessType", ctypes.c_int), ("DirectionType", ctypes.c_int),
                    ("InterfaceAndOperStatusFlags", ctypes.c_ubyte), ("OperStatus", ctypes.c_int),
                    ("AdminStatus", ctypes.c_int), ("MediaConnectState", ctypes.c_int),
                    ("NetworkGuid", ctypes.c_ubyte * 16), ("ConnectionType", ctypes.c_int),
                    ("TransmitLinkSpeed", _U64), ("ReceiveLinkSpeed", _U64)] + [(n, _U64) for n in (
                        "InOctets", "InUcastPkts", "InNUcastPkts", "InDiscards", "InErrors", "InUnknownProtos",
                        "InUcastOctets", "InMulticastOctets", "InBroadcastOctets", "OutOctets", "OutUcastPkts",
                        "OutNUcastPkts", "OutDiscards", "OutErrors", "OutUcastOctets", "OutMulticastOctets",
                        "OutBroadcastOctets", "OutQLen")]

    class DISK_PERFORMANCE(ctypes.Structure):
        _fields_ = [("BytesRead", ctypes.c_longlong), ("BytesWritten", ctypes.c_longlong),
                    ("ReadTime", ctypes.c_longlong), ("WriteTime", ctypes.c_longlong),
                    ("IdleTime", ctypes.c_longlong), ("ReadCount", DWORD), ("WriteCount", DWORD),
                    ("QueueDepth", DWORD), ("SplitCount", DWORD), ("QueryTime", ctypes.c_longlong),
                    ("StorageDeviceNumber", DWORD), ("StorageManagerName", ctypes.c_wchar * 8)]

    def _proto(fn, restype, *argtypes):
        fn.restype, fn.argtypes = restype, list(argtypes)
        return fn

    _P = ctypes.POINTER
    _proto(_k32.OpenProcess, HANDLE, DWORD, wintypes.BOOL, DWORD)
    _proto(_k32.CloseHandle, wintypes.BOOL, HANDLE)
    _proto(_k32.TerminateProcess, wintypes.BOOL, HANDLE, wintypes.UINT)
    _proto(_k32.GetSystemTimes, wintypes.BOOL, _P(FILETIME), _P(FILETIME), _P(FILETIME))
    _proto(_k32.GetSystemTimeAsFileTime, None, _P(FILETIME))
    _proto(_k32.GetTickCount64, ctypes.c_ulonglong)
    _proto(_k32.GlobalMemoryStatusEx, wintypes.BOOL, _P(MEMORYSTATUSEX))
    _proto(_k32.QueryFullProcessImageNameW, wintypes.BOOL, HANDLE, DWORD, wintypes.LPWSTR, _P(DWORD))
    _proto(_k32.GetLogicalDrives, DWORD)
    _proto(_k32.GetDriveTypeW, wintypes.UINT, wintypes.LPCWSTR)
    _proto(_k32.GetDiskFreeSpaceExW, wintypes.BOOL, wintypes.LPCWSTR, _P(_U64), _P(_U64), _P(_U64))
    _proto(_k32.CreateFileW, HANDLE, wintypes.LPCWSTR, DWORD, DWORD, ctypes.c_void_p, DWORD, DWORD, HANDLE)
    _proto(_k32.DeviceIoControl, wintypes.BOOL, HANDLE, DWORD, ctypes.c_void_p, DWORD, ctypes.c_void_p, DWORD,
           _P(DWORD), ctypes.c_void_p)
    _proto(_k32.SetErrorMode, wintypes.UINT, wintypes.UINT)
    _proto(_k32.GetStdHandle, HANDLE, DWORD)
    _proto(_k32.GetConsoleMode, wintypes.BOOL, HANDLE, _P(DWORD))
    _proto(_k32.SetConsoleMode, wintypes.BOOL, HANDLE, DWORD)
    _proto(_k32.GetConsoleOutputCP, wintypes.UINT)
    _proto(_k32.SetConsoleOutputCP, wintypes.BOOL, wintypes.UINT)
    _proto(_ntdll.NtQuerySystemInformation, ctypes.c_long, ULONG, ctypes.c_void_p, ULONG, _P(ULONG))
    _proto(_ntdll.NtQueryInformationProcess, ctypes.c_long, HANDLE, ULONG, ctypes.c_void_p, ULONG, _P(ULONG))
    _proto(_psapi.GetPerformanceInfo, wintypes.BOOL, _P(PERFORMANCE_INFORMATION), DWORD)
    _proto(_advapi.OpenProcessToken, wintypes.BOOL, HANDLE, DWORD, _P(HANDLE))
    _proto(_advapi.GetTokenInformation, wintypes.BOOL, HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD, _P(DWORD))
    _proto(_advapi.LookupAccountSidW, wintypes.BOOL, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.LPWSTR, _P(DWORD),
           wintypes.LPWSTR, _P(DWORD), _P(DWORD))
    _proto(_advapi.GetLengthSid, DWORD, ctypes.c_void_p)
    _proto(_iphlp.GetBestInterface, DWORD, DWORD, _P(DWORD))
    _proto(_iphlp.GetIfEntry2, DWORD, _P(MIB_IF_ROW2))
    _k32.SetErrorMode(0x0001 | 0x8000)  # no "insert a disk" popups for empty card readers

    def _nt_query(cls, size):
        """NtQuerySystemInformation with a buffer that grows until it fits."""
        while True:
            buf = ctypes.create_string_buffer(size)
            ret = ULONG()
            st = _ntdll.NtQuerySystemInformation(cls, buf, size, ctypes.byref(ret))
            if st == STATUS_INFO_LENGTH_MISMATCH:
                size = max(size * 2, ret.value + 65536)
                continue
            return (buf, ret.value, size) if st == 0 else (None, 0, size)


class WinCpuSampler:
    def __init__(self):
        self.prev = self._read()
        self.total, self.freq = 0.0, None
        self.cores = [0.0] * max(1, len(self.prev[1]))

    @staticmethod
    def _read():
        idle, kern, user = FILETIME(), FILETIME(), FILETIME()
        tot = None
        if _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
            tot = (kern.value() + user.value(), idle.value())  # kernel time includes idle time
        n = os.cpu_count() or 1
        arr = (SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION * n)()
        ret = ULONG()
        cores = []
        if _ntdll.NtQuerySystemInformation(8, arr, ctypes.sizeof(arr), ctypes.byref(ret)) == 0:
            cnt = ret.value // ctypes.sizeof(SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION)
            cores = [(c.KernelTime + c.UserTime, c.IdleTime) for c in arr[:cnt]]
        return tot, cores

    def sample(self):
        tot, cores = self._read()
        if tot and self.prev[0]:
            self.total = CpuSampler._usage(self.prev[0], tot)
        if cores and len(cores) == len(self.prev[1]):
            self.cores = [CpuSampler._usage(a, b) for a, b in zip(self.prev[1], cores)]
        else:
            self.cores = [self.total] * max(1, len(cores))
        self.prev = (tot, cores)
        self.freq = self._read_freq()

    @staticmethod
    def _read_freq():
        if not _powrprof:
            return None
        n = os.cpu_count() or 1
        arr = (PROCESSOR_POWER_INFORMATION * n)()
        if _powrprof.CallNtPowerInformation(11, None, 0, arr, ctypes.sizeof(arr)) != 0:
            return None
        vals = [p.CurrentMhz for p in arr if p.CurrentMhz]
        return sum(vals) / len(vals) if vals else None


def win_meminfo():
    ms = MEMORYSTATUSEX()
    ms.dwLength = ctypes.sizeof(ms)
    _k32.GlobalMemoryStatusEx(ctypes.byref(ms))
    total, avail = ms.ullTotalPhys, ms.ullAvailPhys
    cache = 0
    pi = PERFORMANCE_INFORMATION()
    pi.cb = ctypes.sizeof(pi)
    if _psapi.GetPerformanceInfo(ctypes.byref(pi), pi.cb):
        cache = min(avail, pi.SystemCache * pi.PageSize)
    # page file = commit limit − physical memory
    swap_total = max(0, ms.ullTotalPageFile - total)
    commit_used = ms.ullTotalPageFile - ms.ullAvailPageFile
    swap_used = min(swap_total, max(0, commit_used - (total - avail)))
    return {"total": total, "used": total - avail, "cache": cache, "avail": avail, "free": avail - cache,
            "swap_total": swap_total, "swap_used": swap_used}


class WinNetSampler(NetSampler):
    def __init__(self):
        super().__init__()
        self.index = None

    def sample(self, dt):
        if self.n % 10 == 0 or self.index is None:
            idx = DWORD()
            dest = int.from_bytes(socket.inet_aton("8.8.8.8"), "little")
            new = idx.value if _iphlp.GetBestInterface(dest, ctypes.byref(idx)) == 0 else None
            if new != self.index:
                self.index, self.prev = new, None
        self.n += 1
        row = MIB_IF_ROW2()
        if self.index is None:
            self.iface, self.up, self.down = None, 0.0, 0.0
            return
        row.InterfaceIndex = self.index
        if _iphlp.GetIfEntry2(ctypes.byref(row)) != 0:
            self.iface, self.index = None, None
            return
        self.iface = row.Alias or row.Description or "if%d" % self.index
        rx, tx = row.InOctets, row.OutOctets
        self.rx_total, self.tx_total = rx, tx
        if self.prev and dt > 0:
            self.down = max(0.0, (rx - self.prev[0]) / dt)
            self.up = max(0.0, (tx - self.prev[1]) / dt)
        self.prev = (rx, tx)


class WinDiskSampler(DiskSampler):
    def __init__(self):
        self.parts, self.prev, self.part_rates, self.n = [], None, {}, 0
        self.read_rate = self.write_rate = None
        self.handles = {}

    def _volume_io(self, letter):
        h = self.handles.get(letter)
        if h is None:
            h = _k32.CreateFileW("\\\\.\\" + letter, 0, 3, None, 3, 0, None)  # no access rights needed
            if not h or h == ctypes.c_void_p(-1).value:
                h = 0
            self.handles[letter] = h
        if not h:
            return None
        dp, ret = DISK_PERFORMANCE(), DWORD()
        if not _k32.DeviceIoControl(h, 0x70020, None, 0, ctypes.byref(dp), ctypes.sizeof(dp), ctypes.byref(ret), None):
            return None  # IOCTL_DISK_PERFORMANCE unavailable (counters disabled)
        return (dp.BytesRead, dp.BytesWritten)

    def sample(self, dt):
        if self.n % 5 == 0:
            mask, parts = _k32.GetLogicalDrives(), []
            for i in range(26):
                if mask & (1 << i):
                    letter = chr(65 + i) + ":"
                    if _k32.GetDriveTypeW(letter + "\\") in (2, 3):  # removable, fixed
                        parts.append({"dev": letter, "mnt": letter, "fs": "", "kname": letter})
            self.parts = parts
        self.n += 1
        stats = {}
        for p in self.parts:
            free_user, total, free = _U64(), _U64(), _U64()
            if _k32.GetDiskFreeSpaceExW(p["mnt"] + "\\", ctypes.byref(free_user), ctypes.byref(total),
                                        ctypes.byref(free)):
                p["total"], p["avail"], p["used"] = total.value, free_user.value, total.value - free.value
            else:
                p["total"] = 0
                continue
            io = self._volume_io(p["mnt"])
            if io:
                stats[p["kname"]] = io
        if self.prev is not None and dt > 0:
            rates = {k: (max(0, v[0] - self.prev[k][0]) / dt, max(0, v[1] - self.prev[k][1]) / dt)
                     for k, v in stats.items() if k in self.prev}
            self.part_rates = rates
            self.read_rate = sum(r[0] for r in rates.values()) if rates else None
            self.write_rate = sum(r[1] for r in rates.values()) if rates else None
        self.prev = stats


class WinProcSampler(ProcSampler):
    """Whole process table in one NtQuerySystemInformation call (like Task Manager)."""

    def __init__(self):
        super().__init__()
        self.bufsize = 1 << 20
        self.me = current_user().lower()

    def sample(self, dt, memtotal, uptime):
        buf, _, self.bufsize = _nt_query(5, self.bufsize)
        if buf is None:
            return
        now = FILETIME()
        _k32.GetSystemTimeAsFileTime(ctypes.byref(now))
        now = now.value()
        base, off = ctypes.addressof(buf), 0
        procs, prev, cache = [], {}, {}
        while True:
            e = SYSTEM_PROCESS_INFORMATION.from_address(base + off)
            pid = e.UniqueProcessId or 0
            if pid:  # skip the "System Idle Process"
                img = ctypes.wstring_at(e.ImageName.Buffer, e.ImageName.Length // 2) if e.ImageName.Buffer else "System"
                start, t100 = e.CreateTime, e.UserTime + e.KernelTime
                p = Proc()
                p.pid, p.ppid, p.state = pid, e.InheritedFromUniqueProcessId or 0, "S"
                p.threads, p.start = e.NumberOfThreads, start
                p.ticks = t100 * CLK_TCK // 10000000
                p.rss = e.WorkingSetSize
                p.mem = 100.0 * p.rss / memtotal if memtotal else 0.0
                old = self.prev.get(pid)
                if old and old[0] == start and dt > 0:
                    p.cpu = max(0.0, (t100 - old[1]) / 1e7 / dt * 100.0)
                else:
                    age = (now - start) / 1e7 if start else 0
                    p.cpu = t100 / 1e7 / age * 100.0 if age > 1 else 0.0
                if p.cpu >= 1.0:
                    p.state = "R"
                prev[pid] = (start, t100)
                c = self.cache.get(pid)
                if not c or c[0] != start or c[1] != img:
                    c = self._describe_win(pid, start, img)
                cache[pid] = c
                p.name, p.cmd, p.user, p.uid = c[2], c[3], c[4], c[5]
                procs.append(p)
            if not e.NextEntryOffset:
                break
            off += e.NextEntryOffset
        self.prev, self.cache, self.procs = prev, cache, procs

    def _describe_win(self, pid, start, img):
        name = img[:-4] if img.lower().endswith(".exe") else img
        cmd, user = img, ""
        h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if h:
            try:
                cmd = self._cmdline(h) or self._image_path(h) or img
                user = self._owner(h)
            finally:
                _k32.CloseHandle(h)
        if not user:
            user = "SYSTEM" if pid in (4,) or img.lower() in ("registry", "smss.exe", "csrss.exe", "wininit.exe",
                                                             "services.exe", "lsass.exe", "memcompression") else "-"
        return (start, img, name, cmd, user, 0 if user.lower() == self.me else 1)

    @staticmethod
    def _cmdline(h):
        ret = ULONG()
        _ntdll.NtQueryInformationProcess(h, 60, None, 0, ctypes.byref(ret))  # ProcessCommandLineInformation
        if not ret.value:
            return None
        buf = ctypes.create_string_buffer(ret.value)
        if _ntdll.NtQueryInformationProcess(h, 60, buf, ret.value, ctypes.byref(ret)) != 0:
            return None
        us = UNICODE_STRING.from_buffer(buf)
        return ctypes.wstring_at(us.Buffer, us.Length // 2).strip() if us.Buffer and us.Length else None

    @staticmethod
    def _image_path(h):
        buf, size = ctypes.create_unicode_buffer(1024), DWORD(1024)
        return buf.value if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None

    def _owner(self, h):
        tok = HANDLE()
        if not _advapi.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return ""
        try:
            size = DWORD()
            _advapi.GetTokenInformation(tok, 1, None, 0, ctypes.byref(size))  # TokenUser
            if not size.value:
                return ""
            buf = ctypes.create_string_buffer(size.value)
            if not _advapi.GetTokenInformation(tok, 1, buf, size, ctypes.byref(size)):
                return ""
            sid = ctypes.c_void_p.from_buffer(buf).value
            key = ctypes.string_at(sid, _advapi.GetLengthSid(sid))
            if key in self.users:
                return self.users[key]
            name, dom = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
            nlen, dlen, use = DWORD(256), DWORD(256), DWORD()
            user = name.value if _advapi.LookupAccountSidW(None, sid, name, ctypes.byref(nlen), dom,
                                                           ctypes.byref(dlen), ctypes.byref(use)) else ""
            self.users[key] = user
            return user
        finally:
            _k32.CloseHandle(tok)


class NullSensors:
    """Windows exposes temperatures only through WMI with admin rights: show n/a."""

    def scan(self):
        pass

    def read(self):
        return []


def win_kill(pid):
    h = _k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        err = ctypes.get_last_error()
        raise ProcessLookupError() if err == 87 else PermissionError()
    try:
        if not _k32.TerminateProcess(h, 1):
            raise PermissionError()
    finally:
        _k32.CloseHandle(h)


class System:
    """Everything sonar shows, refreshed by sample()."""

    def __init__(self):
        if WINDOWS:
            self.cpu, self.net, self.disk = WinCpuSampler(), WinNetSampler(), WinDiskSampler()
            self.procs, self.sensors, self.read_mem = WinProcSampler(), NullSensors(), win_meminfo
        else:
            self.cpu, self.net, self.disk = CpuSampler(), NetSampler(), DiskSampler()
            self.procs, self.sensors, self.read_mem = ProcSampler(), Sensors(), read_meminfo
        self.cpu_hist = deque(maxlen=HIST)
        self.mem_hist = deque(maxlen=HIST)
        self.up_hist = deque(maxlen=HIST)
        self.down_hist = deque(maxlen=HIST)
        self.hostname = socket.gethostname()
        self.last = None
        self.n = 0
        self.temps = []
        self.mem = self.read_mem()
        self.cpu_temp = None
        self.uptime, self.load = 0.0, (0.0, 0.0, 0.0)  # load is None on Windows (no such metric)

    def sample(self):
        now = time.monotonic()
        dt = now - self.last if self.last else 0.0
        self.last = now
        if WINDOWS:
            self.uptime, self.load = _k32.GetTickCount64() / 1000.0, None
        else:
            up = (read("/proc/uptime") or "0").split()
            self.uptime = float(up[0]) if up else 0.0
            la = (read("/proc/loadavg") or "0 0 0").split()
            self.load = tuple(float(x) for x in la[:3])
        self.cpu.sample()
        self.mem = self.read_mem()
        self.net.sample(dt)
        self.disk.sample(dt)
        self.procs.sample(dt, self.mem["total"], self.uptime)
        if self.n and self.n % 30 == 0:
            self.sensors.scan()
        self.temps = self.sensors.read()
        self.cpu_temp = cpu_temperature(self.temps)
        if dt > 0:  # first call only primes the counters
            self.cpu_hist.append(self.cpu.total)
            self.mem_hist.append(self.mem["used"] / self.mem["total"] if self.mem["total"] else 0)
            self.up_hist.append(self.net.up)
            self.down_hist.append(self.net.down)
        self.n += 1


# ═════════════════════════════════════════════════════════════════════════════
#  Formatting helpers
# ═════════════════════════════════════════════════════════════════════════════

def fmt_rate(n):
    return fmt_bytes(n) + "/s"


def fmt_bytes(n):
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    n, i = float(n or 0), 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        return "%d B" % n
    return ("%.1f %s" if n < 100 else "%.0f %s") % (n, units[i])


def fmt_short(n):
    units = ("B", "K", "M", "G", "T", "P")
    n, i = float(n or 0), 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return ("%d%s" % (n, units[i])) if i == 0 or n >= 100 else ("%.1f%s" % (n, units[i]))


def fmt_uptime(s):
    s = int(s)
    d, h, m = s // 86400, (s % 86400) // 3600, (s % 3600) // 60
    if d:
        return "%dd %dh %02dm" % (d, h, m)
    return "%dh %02dm" % (h, m) if h else "%dm" % m


def fmt_ptime(ticks):
    s = ticks / CLK_TCK
    if s < 3600:
        return "%d:%05.2f" % (s // 60, s % 60)
    h = int(s // 3600)
    if h < 100:
        return "%d:%02d:%02d" % (h, (s % 3600) // 60, s % 60)
    return "%dh" % h


def fmt_freq(mhz):
    if not mhz:
        return "n/a"
    return "%.2f GHz" % (mhz / 1000) if mhz >= 1000 else "%d MHz" % mhz


def clean(s):
    """Printable, single-width text only (command lines can contain anything)."""
    if s.isascii() and s.isprintable():
        return s
    out = []
    for ch in s:
        o = ord(ch)
        if o < 32 or 127 <= o < 160:
            out.append(" ")
        elif o > 0x2e7f and unicodedata.east_asian_width(ch) in "WF":
            out.append("?")
        elif unicodedata.combining(ch):
            continue
        else:
            out.append(ch)
    return "".join(out)


def split_command(cmd):
    """('program', ' arguments') for display: program name without its directory.

    Handles POSIX paths and Windows paths, quoted or not ("C:\\Program Files\\x.exe" --flag).
    """
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        first, rest = (cmd[1:end], cmd[end + 1:]) if end > 0 else (cmd[1:], "")
    else:
        m = re.match(r"([A-Za-z]:\\.*?\.(?:exe|com|bat|cmd))(?=\s|$)", cmd, re.I) if WINDOWS else None
        if m:
            first, rest = m.group(1), cmd[m.end():]
        else:
            first, sp, rest = cmd.partition(" ")
            rest = sp + rest
    head = re.split(r"[\\/]", first)[-1] if ("/" in first or "\\" in first) and not first.startswith("[") else first
    return head or first, rest.rstrip() and (rest if rest.startswith(" ") else " " + rest)


def fit(s, w):
    if w <= 0:
        return ""
    return s if len(s) <= w else (s[:w - 1] + "…" if w > 1 else s[:w])


# ═════════════════════════════════════════════════════════════════════════════
#  Rendering primitives: canvas, boxes, bars, braille graphs
# ═════════════════════════════════════════════════════════════════════════════

_SGR = {}


def sgr(style, color):
    key = (style, color)
    s = _SGR.get(key)
    if s is None:
        fg, bg, a = style
        p = ["0"]
        if a & BOLD:
            p.append("1")
        if a & DIM:
            p.append("2")
        if a & ULINE:
            p.append("4")
        if a & REV:
            p.append("7")
        if color:
            if fg:
                p.append("38;2;%d;%d;%d" % fg)
            if bg:
                p.append("48;2;%d;%d;%d" % bg)
        s = _SGR[key] = "\x1b[" + ";".join(p) + "m"
    return s


class Canvas:
    """A full frame in memory: one char and one style per cell."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.ch = [[" "] * w for _ in range(h)]
        self.st = [[PLAIN] * w for _ in range(h)]

    def put(self, x, y, s, st=PLAIN):
        if not 0 <= y < self.h or x >= self.w:
            return x + len(s)
        row, srow = self.ch[y], self.st[y]
        for c in s:
            if x >= self.w:
                break
            if x >= 0:
                row[x] = c
                srow[x] = st
            x += 1
        return x

    def fill(self, x, y, w, h, st=PLAIN):
        for yy in range(max(0, y), min(self.h, y + h)):
            for xx in range(max(0, x), min(self.w, x + w)):
                self.ch[yy][xx] = " "
                self.st[yy][xx] = st

    def style_row(self, x, y, w, st):
        """Re-style a span, keeping its characters (fg kept if set)."""
        if not 0 <= y < self.h:
            return
        srow = self.st[y]
        for xx in range(max(0, x), min(self.w, x + w)):
            fg, _, a = srow[xx]
            srow[xx] = (fg or st[0], st[1], a | st[2])

    def line(self, y, color=True):
        out, cur = [], None
        for c, s in zip(self.ch[y], self.st[y]):
            if s != cur:
                out.append(sgr(s, color))
                cur = s
            out.append(c)
        out.append("\x1b[0m")
        return "".join(out)


BAR_FULL, BAR_HALF, BAR_TRACK = "━", "╸", "─"
VBLOCKS = "▁▂▃▄▅▆▇█"
# braille dots: bits per (column, row-from-top)
_BR_UP = ((0x40, 0x04, 0x02, 0x01), (0x80, 0x20, 0x10, 0x08))     # filled from the bottom
_BR_DOWN = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))   # filled from the top
_BR_CUM_UP = [[sum(col[:k]) for k in range(5)] for col in _BR_UP]
_BR_CUM_DOWN = [[sum(col[:k]) for k in range(5)] for col in _BR_DOWN]


def braille_graph(cv, x, y, w, h, values, theme, up=True, baseline=None):
    """Draw a history (values in 0..1, newest last) as a braille area graph.

    Each character holds 2 samples × 4 vertical dots. The color follows the
    height of the row (theme gradient), so peaks glow with the 'high' accent.
    """
    if w <= 0 or h <= 0:
        return
    n = 2 * w
    vals = list(values)[-n:]
    vals = [None] * (n - len(vals)) + vals
    dots = 4 * h
    levels = []
    for v in vals:
        if v is None:
            levels.append(0)
        else:
            lv = int(round(max(0.0, min(1.0, v)) * dots))
            levels.append(1 if lv == 0 and v > 0.004 else lv)
    cum = _BR_CUM_UP if up else _BR_CUM_DOWN
    for r in range(h):
        base = (h - 1 - r) * 4 if up else r * 4
        t = (h - r - 0.5) / h if up else (r + 0.5) / h
        st = (theme.g(t), None, 0)
        edge = (r == h - 1) if up else (r == 0)
        chars = []
        for c in range(w):
            a = levels[2 * c] - base
            b = levels[2 * c + 1] - base
            code = cum[0][4 if a > 4 else a if a > 0 else 0] | cum[1][4 if b > 4 else b if b > 0 else 0]
            chars.append(chr(0x2800 + code) if code else None)
        row_ch, row_st = cv.ch[y + r] if 0 <= y + r < cv.h else None, cv.st[y + r] if 0 <= y + r < cv.h else None
        if row_ch is None:
            continue
        for c, ch in enumerate(chars):
            xx = x + c
            if not 0 <= xx < cv.w:
                continue
            if ch:
                row_ch[xx], row_st[xx] = ch, st
            elif edge and baseline:
                row_ch[xx], row_st[xx] = ("⣀" if up else "⠉"), baseline


# ═════════════════════════════════════════════════════════════════════════════
#  Keyboard
# ═════════════════════════════════════════════════════════════════════════════

ESC_SEQ = {
    "\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left",
    "\x1bOA": "up", "\x1bOB": "down", "\x1bOC": "right", "\x1bOD": "left",
    "\x1b[5~": "pgup", "\x1b[6~": "pgdn", "\x1b[3~": "del", "\x1b[Z": "btab",
    "\x1b[H": "home", "\x1b[F": "end", "\x1bOH": "home", "\x1bOF": "end",
    "\x1b[1~": "home", "\x1b[4~": "end", "\x1b[7~": "home", "\x1b[8~": "end",
}


def parse_keys(data):
    s = data.decode("utf-8", "replace")
    keys, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\x1b":
            if i + 1 < len(s) and s[i + 1] in "[O":
                j = i + 2
                while j < len(s) and not ("@" <= s[j] <= "~"):
                    j += 1
                keys.append(ESC_SEQ.get(s[i:j + 1], "unknown"))
                i = j + 1
            else:
                keys.append("esc")
                i += 1
            continue
        keys.append({"\r": "enter", "\n": "enter", "\t": "tab", "\x7f": "backspace", "\x08": "backspace",
                     "\x03": "ctrl-c", "\x04": "ctrl-d", "\x15": "ctrl-u"}.get(c, c))
        i += 1
    return keys


# ═════════════════════════════════════════════════════════════════════════════
#  The application: state, layout, panels
# ═════════════════════════════════════════════════════════════════════════════

PANELS = ("cpu", "mem", "net", "temps", "disks")      # toggled with 1..5
DROP_ORDER = ("temps", "disks", "net", "mem", "cpu")  # hidden first when space runs out
WEIGHTS = {"cpu": 6, "mem": 4, "net": 4, "temps": 3, "disks": 3}
SORTS = ("cpu", "mem", "pid", "name", "time")
INTERVALS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)
PROC_MIN = 6
LOGO = "∿∿∿"

HELP = [
    ("navigation", None),
    ("↑ ↓  j k", "select a process"),
    ("PgUp PgDn", "page up / down"),
    ("Home End  g G", "first / last process"),
    ("processes", None),
    ("x  Del", "kill selected (SIGTERM), asks y/n"),
    ("X", "kill selected (SIGKILL), asks y/n"),
] if not WINDOWS else [
    ("navigation", None),
    ("↑ ↓  j k", "select a process"),
    ("PgUp PgDn", "page up / down"),
    ("Home End  g G", "first / last process"),
    ("processes", None),
    ("x  X  Del", "end selected process, asks y/n"),
]
HELP += [
    ("/", "filter by name or command · Esc clears"),
    ("s  r", "cycle sort cpu→mem→pid→name→time · reverse"),
    ("t", "tree view (parents / children)"),
    ("u", "only my processes"),
    ("view", None),
    ("1 … 5", "toggle cpu · mem · net · temps · disks"),
    ("+  -", "refresh faster / slower (0.25 s – 5 s)"),
    ("p", "pause updates"),
    ("c", "theme picker"),
    ("?", "this help"),
    ("q  Ctrl+C", "quit"),
]


class App:
    def __init__(self, theme, interval=1.0, color=True):
        self.theme = Theme(theme)
        self.color = color
        self.interval = interval
        self.sys = System()
        self.visible = {p: True for p in PANELS}
        self.sort, self.reverse = "cpu", False
        self.tree = self.mine = False
        self.filter = ""
        self.mode = "normal"   # normal | filter | confirm | help | picker
        self.paused = False
        self.sel_idx, self.sel_pid, self.scroll = 0, None, 0
        self.view = []         # [(proc, tree_prefix)] as last rendered
        self.page = 10
        self.confirm = None    # (pid, name, sig)
        self.msg, self.msg_until, self.msg_err = "", 0.0, False
        self.picker = None
        self.cats = theme_categories()
        self.running = True
        self.uid = my_uid()

    # ── styles ───────────────────────────────────────────────────────────────
    def st(self, fg=None, bg=None, a=0):
        return (fg, bg, a)

    @property
    def s_dim(self):
        return (None, None, DIM)

    @property
    def s_border(self):
        return (self.theme.border, None, 0) if self.color else (None, None, DIM)

    @property
    def s_title(self):
        return (self.theme.title, None, BOLD)

    @property
    def s_track(self):
        return (self.theme.track, None, 0) if self.color else (None, None, DIM)

    def flash(self, msg, err=False, secs=3.0):
        self.msg, self.msg_err, self.msg_until = msg, err, time.monotonic() + secs

    # ── process list (filter / sort / tree) ─────────────────────────────────
    def build_view(self):
        procs = self.sys.procs.procs
        if self.mine:
            procs = [p for p in procs if p.uid == self.uid]
        if self.filter:
            f = self.filter.lower()
            procs = [p for p in procs if f in p.name.lower() or f in p.cmd.lower()]
        key = {"cpu": lambda p: (p.cpu, p.ticks), "mem": lambda p: (p.rss, p.pid), "pid": lambda p: p.pid,
               "name": lambda p: (p.name.lower(), p.pid), "time": lambda p: (p.ticks, p.pid)}[self.sort]
        desc = self.sort in ("cpu", "mem", "time")
        if self.reverse:
            desc = not desc
        if not self.tree:
            return [(p, "") for p in sorted(procs, key=key, reverse=desc)]
        by_pid = {p.pid: p for p in procs}
        kids, roots = {}, []
        for p in procs:
            parent = by_pid.get(p.ppid)
            # a parent must be older than its child (PIDs get reused, notably on Windows)
            if parent is not None and p.ppid != p.pid and parent.start <= p.start:
                kids.setdefault(p.ppid, []).append(p)
            else:
                roots.append(p)
        out = []
        stack = [(p, "", True, 0) for p in reversed(sorted(roots, key=key, reverse=desc))]
        while stack:
            p, prefix, last, depth = stack.pop()
            glyph = "" if depth == 0 else prefix + ("└─ " if last else "├─ ")
            out.append((p, glyph))
            ch = sorted(kids.get(p.pid, ()), key=key, reverse=desc)
            sub = "" if depth == 0 else prefix + ("   " if last else "│  ")
            for i in range(len(ch) - 1, -1, -1):
                stack.append((ch[i], sub, i == len(ch) - 1, depth + 1))
        return out

    def selected(self):
        if self.view and 0 <= self.sel_idx < len(self.view):
            return self.view[self.sel_idx][0]
        return None

    def move(self, d):
        if not self.view:
            return
        self.sel_idx = max(0, min(len(self.view) - 1, self.sel_idx + d))
        self.sel_pid = self.view[self.sel_idx][0].pid

    # ── layout ──────────────────────────────────────────────────────────────
    def core_layout(self, iw):
        n = len(self.sys.cpu.cores)
        lw = len(str(n - 1))
        gap = 2
        cols = max(1, (iw + gap) // (lw + 1 + 6 + 5 + gap))
        cols = min(cols, n)
        bw = max(4, min(24, (iw + gap) // cols - gap - (lw + 1 + 5)))
        bar_rows = -(-n // cols)
        per = max(1, (iw + 1) // 2)
        return lw, cols, bw, bar_rows, -(-n // per), per

    def min_h(self, p, w):
        iw = w - 4
        if p == "cpu":
            return 2 + 2 + self.core_layout(iw)[4]
        if p == "mem":
            return 5
        if p == "net":
            return 6
        if p == "temps":
            return 3
        if p == "disks":
            return 4
        return 3

    def pref_h(self, p, w):
        iw = w - 4
        if p == "cpu":
            br = self.core_layout(iw)[3]
            return 2 + 5 + 1 + (br if br <= 8 else self.core_layout(iw)[4])
        if p == "mem":
            return 10
        if p == "net":
            return 10
        if p == "temps":
            return 2 + max(1, min(12, len(self.sys.temps)))
        if p == "disks":
            return 2 + 1 + max(1, min(10, len(self.sys.disk.parts)))
        return 3

    def layout(self, W, H):
        avail = H - 2
        if W >= 120:
            groups = [["cpu", "mem"], ["net", "temps", "disks"]]
        elif W >= 70:
            groups = [["cpu"], ["mem", "net"], ["temps", "disks"]]
        else:
            groups = [["cpu"], ["mem"], ["net"], ["disks"], ["temps"]]
        shown = [p for p in PANELS if self.visible[p]]
        auto_hidden = []
        while True:
            rows = []
            for g in groups:
                r = [p for p in g if p in shown]
                if r:
                    tot = sum(WEIGHTS[p] for p in r)
                    x, cells = 0, []
                    for i, p in enumerate(r):
                        w = W - x if i == len(r) - 1 else int(round(W * WEIGHTS[p] / tot))
                        cells.append((p, x, w))
                        x += w
                    rows.append(cells)
            mins = [max(self.min_h(p, w) for p, _, w in r) for r in rows]
            if sum(mins) + PROC_MIN <= avail or not shown:
                break
            victim = next(p for p in DROP_ORDER if p in shown)
            shown.remove(victim)
            auto_hidden.append(victim)
        prefs = [max(max(self.pref_h(p, w) for p, _, w in r), m) for r, m in zip(rows, mins)]
        heights = list(mins)
        # the process list is the main content: keep ~35% of the screen for it
        procs_want = max(PROC_MIN, int(avail * 0.35))
        extra = avail - sum(heights) - procs_want
        grew = True
        while extra > 0 and grew:  # grow rows towards their preferred height, fairly
            grew = False
            for i in range(len(rows)):
                if extra > 0 and heights[i] < prefs[i]:
                    heights[i] += 1
                    extra -= 1
                    grew = True
        procs_h = avail - sum(heights)
        growable = [i for i, r in enumerate(rows) if any(p in ("cpu", "mem", "net") for p, _, _ in r)]
        if growable and procs_h > 22:  # big screens: let the graphs breathe too
            share = (procs_h - 22) // 2
            for k in range(share):
                heights[growable[k % len(growable)]] += 1
            procs_h -= share
        rects, y = [], 1
        for r, h in zip(rows, heights):
            for p, x, w in r:
                rects.append((p, x, y, w, h))
            y += h
        return rects, (0, y, W, procs_h), auto_hidden

    # ── frame ───────────────────────────────────────────────────────────────
    def frame(self, W, H):
        cv = Canvas(W, H)
        if W < 40 or H < 10:
            msg = "terminal too small (%dx%d)" % (W, H)
            cv.put(max(0, (W - len(msg)) // 2), H // 2, fit(msg, W), self.s_dim)
            return cv
        rects, prect, hidden = self.layout(W, H)
        self.draw_header(cv, W)
        for p, x, y, w, h in rects:
            getattr(self, "draw_" + p)(cv, x, y, w, h)
        self.draw_procs(cv, *prect)
        self.draw_footer(cv, W, H - 1, hidden)
        if self.mode == "help":
            self.draw_help(cv, W, H)
        elif self.mode == "picker":
            self.draw_picker(cv, W, H)
        return cv

    def box(self, cv, x, y, w, h, title, right=None):
        """Rounded panel: ╭─ title ───── right ─╮ … ╰────╯."""
        b = self.s_border
        cv.put(x, y, "╭" + "─" * (w - 2) + "╮", b)
        for yy in range(y + 1, y + h - 1):
            cv.put(x, yy, "│", b)
            cv.put(x + w - 1, yy, "│", b)
        cv.put(x, y + h - 1, "╰" + "─" * (w - 2) + "╯", b)
        xx = x + 2
        room = w - 4
        if title:
            xx = cv.put(xx, y, " ", b)
            for text, st in title:
                take = fit(text, x + w - 3 - xx)
                xx = cv.put(xx, y, take, st)
            xx = cv.put(xx, y, " ", b)
        if right:
            rlen = sum(len(t) for t, _ in right) + 2
            rx = x + w - 2 - rlen
            if rx > xx + 1:
                rx = cv.put(rx, y, " ", b)
                for text, st in right:
                    rx = cv.put(rx, y, text, st)
                cv.put(rx, y, " ", b)
        return room

    def bar(self, cv, x, y, w, frac, color_fn, seg2=0.0, seg2_st=None):
        """Thin gradient bar ━━━━╸─── with optional second segment (e.g. cache)."""
        if w <= 0:
            return
        frac = max(0.0, min(1.0, frac))
        halves = int(round(frac * w * 2))
        full, half = halves // 2, halves % 2
        seg2_end = min(w, int(round((frac + max(0.0, seg2)) * w)))
        for i in range(w):
            t = i / max(1, w - 1)
            if i < full:
                cv.put(x + i, y, BAR_FULL, (color_fn(t), None, 0) if self.color else PLAIN)
            elif i == full and half:
                cv.put(x + i, y, BAR_HALF, (color_fn(t), None, 0) if self.color else PLAIN)
            elif seg2_st and i < seg2_end:
                cv.put(x + i, y, BAR_FULL, seg2_st)
            else:
                cv.put(x + i, y, BAR_TRACK, self.s_track)

    def gstyle(self, t, a=0):
        return (self.theme.g(t), None, a) if self.color else (None, None, a)

    # ── header & footer ─────────────────────────────────────────────────────
    def draw_header(self, cv, W):
        s, th = self.sys, self.theme
        x = 1
        for i, ch in enumerate(LOGO):
            x = cv.put(x, 0, ch, self.gstyle(i / max(1, len(LOGO) - 1), BOLD))
        x = cv.put(x + 1, 0, "sonar", self.s_title if self.color else (None, None, BOLD))
        clock = time.strftime("%H:%M:%S")
        date = time.strftime("%a %d %b").lower()
        right = [(date + "  ", self.s_dim), (clock, (None, None, BOLD))]
        rlen = sum(len(t) for t, _ in right)
        if W - rlen - 2 < 40:
            right = right[1:]
            rlen = len(clock)
        parts = [
            [("   ", PLAIN), (s.hostname, (None, None, BOLD))],
            [("   up ", self.s_dim), (fmt_uptime(s.uptime), PLAIN)],
        ]
        if s.load is not None:  # Windows has no load average
            parts.append([("   load ", self.s_dim)] + [
                (("%.2f" % v) + ("  " if i < 2 else ""),
                 (th.heat(v / max(1, len(s.cpu.cores))), None, 0) if self.color else PLAIN)
                for i, v in enumerate(s.load)])
        limit = W - rlen - 2
        for seg in parts:
            if x + sum(len(t) for t, _ in seg) > limit:
                break
            for t, st in seg:
                x = cv.put(x, 0, t, st)
        if self.paused:
            tag = "  ❚❚ paused"
            if x + len(tag) <= limit:
                cv.put(x, 0, tag, (th.warm, None, BOLD) if self.color else (None, None, BOLD))
        xx = W - 1 - rlen
        for t, st in right:
            xx = cv.put(xx, 0, t, st)

    def draw_footer(self, cv, W, y, hidden):
        th = self.theme
        acc = (th.c[1], None, BOLD) if self.color else (None, None, BOLD)
        if self.mode == "confirm" and self.confirm:
            pid, name, sig = self.confirm
            red = (th.hot, None, BOLD) if self.color else (None, None, BOLD)
            x = cv.put(1, y, "kill ", red)
            x = cv.put(x, y, "%s (%d)" % (fit(clean(name), 30), pid), (None, None, BOLD))
            x = cv.put(x, y, "? ", red)
            x = cv.put(x, y, sig, red)
            cv.put(x, y, "  y/n", self.s_dim)
            return
        if self.mode == "filter":
            x = cv.put(1, y, "filter › ", acc)
            x = cv.put(x, y, fit(self.filter, W - 40), (None, None, BOLD))
            x = cv.put(x, y, "▏", acc)
            cv.put(x + 2, y, "enter keep · esc clear", self.s_dim)
            return
        if self.msg and time.monotonic() < self.msg_until:
            st = (th.hot, None, BOLD) if self.msg_err and self.color else (None, None, BOLD) if self.msg_err else acc
            cv.put(1, y, fit(self.msg, W - 2), st)
            return
        rate = ("%gs" % self.interval) + ("  paused" if self.paused else "")
        hints = [("x", "kill"), ("/", "filter"), ("s", "sort"), ("t", "tree"), ("u", "mine"), ("c", "theme"),
                 ("?", "help"), ("q", "quit")]
        x, limit = 1, W - len(rate) - 3
        if hidden:
            limit -= len(" hidden: " + " ".join(hidden))
        for k, label in hints:
            if x + len(k) + len(label) + 3 > limit:
                break
            x = cv.put(x, y, k, acc)
            x = cv.put(x + 1, y, label, self.s_dim) + 2
        if hidden:
            x = cv.put(x, y, " hidden: " + " ".join(hidden), self.s_dim)
        cv.put(W - 1 - len(rate), y, rate, self.s_dim)

    # ── panels ──────────────────────────────────────────────────────────────
    def draw_cpu(self, cv, x, y, w, h):
        s, th = self.sys, self.theme
        cores = s.cpu.cores
        tot = s.cpu.total
        temp = "n/a" if s.cpu_temp is None else "%d°C" % round(s.cpu_temp)
        tst = self.s_dim if s.cpu_temp is None else (
            (th.heat((s.cpu_temp - 40) / 50), None, 0) if self.color else PLAIN)
        right = [("%d cores · " % len(cores), self.s_dim), (fmt_freq(s.cpu.freq), self.s_dim),
                 (" · ", self.s_dim), (temp, tst)]
        self.box(cv, x, y, w, h, [("cpu", self.s_title), ("  %d%%" % round(tot * 100), self.gstyle(tot, BOLD))],
                 right)
        ix, iy, iw, ih = x + 2, y + 1, w - 4, h - 2
        lw, cols, bw, bar_rows, cmp_rows, per = self.core_layout(iw)
        if ih - bar_rows >= 3 and bar_rows <= 8:
            mode, crow = "bars", bar_rows
        elif ih - cmp_rows >= 1:
            mode, crow = "compact", cmp_rows
        else:
            mode, crow = None, 0
        spacer = 1 if ih - crow >= 5 else 0
        gh = ih - crow - spacer
        braille_graph(cv, ix, iy, iw, gh, s.cpu_hist, th, up=True, baseline=self.s_track)
        cy = iy + gh + spacer
        if mode == "bars":
            cellw = (iw + 2) // cols
            for i, u in enumerate(cores):
                r, c = i % crow, i // crow
                cx = ix + c * cellw
                cv.put(cx, cy + r, str(i).rjust(lw), self.s_dim)
                self.bar(cv, cx + lw + 1, cy + r, bw, u, th.g)
                cv.put(cx + lw + 1 + bw, cy + r, ("%d%%" % round(u * 100)).rjust(5),
                       self.gstyle(u) if u >= 0.05 else self.s_dim)
        elif mode == "compact":
            for i, u in enumerate(cores):
                r, c = i // per, i % per
                ch = VBLOCKS[min(7, int(u * 8))] if u >= 0.02 else "▁"
                cv.put(ix + c * 2, cy + r, ch, self.gstyle(u) if u >= 0.02 else self.s_track)

    def draw_mem(self, cv, x, y, w, h):
        s, th, m = self.sys, self.theme, self.sys.mem
        total = m["total"] or 1
        self.box(cv, x, y, w, h, [("mem", self.s_title)],
                 [(fmt_short(m["used"]), PLAIN), (" / " + fmt_short(m["total"]), self.s_dim)])
        ix, iy, iw, ih = x + 2, y + 1, w - 4, h - 2
        cache_st = (mix(th.c[0], th.bg, 0.45), None, 0) if self.color else (None, None, DIM)
        pct_w = 5
        bw = max(4, iw - 5 - pct_w)
        uf = m["used"] / total
        cv.put(ix, iy, "ram", self.s_dim)
        self.bar(cv, ix + 5, iy, bw, uf, th.g, m["cache"] / total, cache_st)
        cv.put(ix + 5 + bw, iy, ("%d%%" % round(uf * 100)).rjust(pct_w), self.gstyle(uf, BOLD))
        if ih >= 2:
            cv.put(ix, iy + 1, "swap", self.s_dim)
            if m["swap_total"]:
                sf = m["swap_used"] / m["swap_total"]
                self.bar(cv, ix + 5, iy + 1, bw, sf, th.heat)
                cv.put(ix + 5 + bw, iy + 1, ("%d%%" % round(sf * 100)).rjust(pct_w), self.s_dim)
            else:
                self.bar(cv, ix + 5, iy + 1, bw, 0, th.g)
                cv.put(ix + 5 + bw, iy + 1, "none".rjust(pct_w), self.s_dim)
        if ih >= 3:
            items = [("●", (th.c[1], None, 0) if self.color else PLAIN, "used", m["used"]),
                     ("●", cache_st, "cache", m["cache"]),
                     ("○", self.s_dim, "avail", m["avail"])]
            if m["swap_total"]:
                items.append(("", PLAIN, "swap", m["swap_used"]))
            xx = ix
            for dot, dst, label, val in items:
                need = len(dot) + len(label) + len(fmt_short(val)) + 4
                if xx + need > ix + iw:
                    break
                if dot:
                    xx = cv.put(xx, iy + 2, dot + " ", dst)
                xx = cv.put(xx, iy + 2, label + " ", self.s_dim)
                xx = cv.put(xx, iy + 2, fmt_short(val), PLAIN) + 2
        if ih >= 6:
            braille_graph(cv, ix, iy + 4, iw, ih - 4, s.mem_hist, th, up=True, baseline=self.s_track)

    def draw_net(self, cv, x, y, w, h):
        s, th, n = self.sys, self.theme, self.sys.net
        title = [("net", self.s_title)]
        if n.iface:
            title.append(("  " + n.iface, self.s_dim))
        self.box(cv, x, y, w, h, title)
        ix, iy, iw, ih = x + 2, y + 1, w - 4, h - 2
        if not n.iface:
            cv.put(ix, iy, "n/a — no network interface", self.s_dim)
            return
        gh = ih - 2
        uph, dnh = (gh + 1) // 2, gh // 2
        win = 2 * iw
        up_hist, dn_hist = list(s.up_hist)[-win:], list(s.down_hist)[-win:]
        up_max = max(max(up_hist, default=0), 1024.0)
        dn_max = max(max(dn_hist, default=0), 1024.0)

        def info(yy, arrow, rate, peak, total, t):
            xx = cv.put(ix, yy, arrow + " ", self.gstyle(t, BOLD))
            xx = cv.put(xx, yy, fmt_rate(rate), (None, None, BOLD))
            tail = [("peak ", self.s_dim), (fmt_rate(peak), PLAIN), ("  total ", self.s_dim), (fmt_bytes(total), PLAIN)]
            if xx + 2 + sum(len(a) for a, _ in tail) > ix + iw:
                tail = tail[2:]
                tail[0] = ("total ", self.s_dim)
            if xx + 2 + sum(len(a) for a, _ in tail) <= ix + iw:
                rx = ix + iw - sum(len(a) for a, _ in tail)
                for a, st in tail:
                    rx = cv.put(rx, yy, a, st)

        info(iy, "↑", n.up, max(up_hist, default=0), n.tx_total, 1.0)
        if uph > 0:
            braille_graph(cv, ix, iy + 1, iw, uph, [v / up_max for v in up_hist], th, up=True, baseline=self.s_track)
        if dnh > 0:
            braille_graph(cv, ix, iy + 1 + uph, iw, dnh, [v / dn_max for v in dn_hist], th, up=False,
                          baseline=self.s_track)
        info(iy + ih - 1, "↓", n.down, max(dn_hist, default=0), n.rx_total, 0.5)

    def draw_temps(self, cv, x, y, w, h):
        temps, th = self.sys.temps, self.theme
        self.box(cv, x, y, w, h, [("temps", self.s_title)], [(str(len(temps)), self.s_dim)] if temps else None)
        ix, iy, iw, ih = x + 2, y + 1, w - 4, h - 2
        if not temps:
            cv.put(ix, iy, fit("n/a — no readable sensors", iw), self.s_dim)
            return
        rows = temps if len(temps) <= ih else temps[:ih - 1]
        bw = 8 if iw >= 30 else 0
        nw = iw - 6 - (bw + 1 if bw else 0)
        for i, (name, _, val, high) in enumerate(rows):
            hi = high or 90.0
            t = (val - 35) / max(10.0, hi - 35)
            st = (th.heat(t), None, 0) if self.color else PLAIN
            cv.put(ix, iy + i, fit(name, nw), PLAIN)
            if bw:
                self.bar(cv, ix + nw + 1, iy + i, bw, val / max(hi, 1), lambda u, t=t: th.heat(t * (0.4 + 0.6 * u)))
            cv.put(ix + iw - 6, iy + i, ("%d°C" % round(val)).rjust(6), st)
        if len(rows) < len(temps):
            cv.put(ix, iy + ih - 1, "+%d more" % (len(temps) - len(rows)), self.s_dim)

    def draw_disks(self, cv, x, y, w, h):
        d, th = self.sys.disk, self.theme
        if d.read_rate is None:
            right = [("io n/a", self.s_dim)]
        else:
            right = [("r ", self.s_dim), (fmt_rate(d.read_rate), PLAIN), ("  w ", self.s_dim),
                     (fmt_rate(d.write_rate), PLAIN)]
        self.box(cv, x, y, w, h, [("disks", self.s_title)], right)
        ix, iy, iw, ih = x + 2, y + 1, w - 4, h - 2
        parts = [p for p in d.parts if p.get("total")]
        if not parts:
            cv.put(ix, iy, "n/a — no mounted filesystems", self.s_dim)
            return
        rows = parts if len(parts) <= ih else parts[:ih - 1]
        mw = max(4, min(16, max(len(p["mnt"]) for p in rows), iw // 3))
        show_size = iw >= 34
        show_io = iw >= 64
        tail = 5 + (12 if show_size else 0) + (20 if show_io else 0)
        bw = max(3, iw - mw - 1 - tail)
        for i, p in enumerate(rows):
            yy = iy + i
            frac = p["used"] / p["total"] if p["total"] else 0
            cv.put(ix, yy, fit(p["mnt"], mw), PLAIN)
            self.bar(cv, ix + mw + 1, yy, bw, frac, lambda t, f=frac: th.heat(max(0, (f - 0.6) / 0.4) * t)
                     if f > 0.85 else th.g(t))
            xx = ix + mw + 1 + bw
            hot = frac > 0.9
            xx = cv.put(xx, yy, ("%d%%" % round(frac * 100)).rjust(5),
                        (th.hot, None, BOLD) if hot and self.color else self.gstyle(frac))
            if show_size:
                xx = cv.put(xx, yy, ("%s/%s" % (fmt_short(p["used"]), fmt_short(p["total"]))).rjust(12), self.s_dim)
            if show_io:
                r = d.part_rates.get(p["kname"])
                io = ("r %s w %s" % (fmt_short(r[0]), fmt_short(r[1]))) if r else ""
                cv.put(xx, yy, io.rjust(20), self.s_dim)
        if len(rows) < len(parts):
            cv.put(ix, iy + ih - 1, "+%d more" % (len(parts) - len(rows)), self.s_dim)

    def draw_procs(self, cv, x, y, w, h):
        th = self.theme
        view = self.build_view()
        self.view = view
        # keep the selection on the same process across refreshes / re-sorts
        if self.sel_pid is not None:
            for i, (p, _) in enumerate(view):
                if p.pid == self.sel_pid:
                    self.sel_idx = i
                    break
        self.sel_idx = max(0, min(self.sel_idx, len(view) - 1))
        self.sel_pid = view[self.sel_idx][0].pid if view else None

        title = [("processes", self.s_title), ("  %d" % len(view), self.s_dim)]
        acc = (th.c[1], None, 0) if self.color else (None, None, BOLD)
        if self.tree:
            title.append(("  tree", acc))
        if self.mine:
            title.append(("  mine", acc))
        if self.filter:
            title.append(("  /" + self.filter, acc))
        arrow = "▴" if (self.sort in ("cpu", "mem", "time")) == self.reverse else "▾"
        self.box(cv, x, y, w, h, title, [("sort ", self.s_dim), (self.sort + " " + arrow, acc)])
        ix, iy, iw, ih = x + 2, y + 1, w - 4, h - 2
        cols = [("pid", 7, "r", "pid"), ("user", 10, "l", None), ("cpu%", 6, "r", "cpu"), ("mem%", 6, "r", "mem"),
                ("time", 10, "r", "time")]
        if iw < 70:
            cols = [c for c in cols if c[0] != "time"]
        if iw < 56:
            cols = [c for c in cols if c[0] != "user"]
        xx = ix
        for name, cw, al, key in cols:
            label = name.rjust(cw) if al == "r" else name.ljust(cw)
            cv.put(xx, iy, label, (th.c[1], None, BOLD) if key == self.sort and self.color else
                   (None, None, BOLD | ULINE) if key == self.sort else self.s_dim)
            xx += cw + 1
        cmd_x = xx + 1
        cv.put(cmd_x, iy, "command", (th.c[1], None, BOLD) if self.sort == "name" and self.color else self.s_dim)
        rows = ih - 1
        self.page = max(1, rows)
        if self.sel_idx < self.scroll:
            self.scroll = self.sel_idx
        elif self.sel_idx >= self.scroll + rows:
            self.scroll = self.sel_idx - rows + 1
        self.scroll = max(0, min(self.scroll, max(0, len(view) - rows)))
        if not view:
            cv.put(ix, iy + 2, "no matching processes" if self.filter or self.mine else "no processes", self.s_dim)
        ncpu = max(1, len(self.sys.cpu.cores))
        for r in range(rows):
            i = self.scroll + r
            if i >= len(view):
                break
            p, prefix = view[i]
            yy = iy + 1 + r
            xx = ix
            for name, cw, al, _ in cols:
                if name == "pid":
                    cv.put(xx, yy, str(p.pid).rjust(cw), self.s_dim)
                elif name == "user":
                    mine = p.uid == self.uid
                    cv.put(xx, yy, fit(p.user, cw).ljust(cw), PLAIN if mine else self.s_dim)
                elif name == "cpu%":
                    t = min(1.0, p.cpu / 100.0)
                    st = self.gstyle(0.35 + 0.65 * t, BOLD if p.cpu >= 50 else 0) if p.cpu >= 0.5 else self.s_dim
                    cv.put(xx, yy, ("%.1f" % min(p.cpu, 100.0 * ncpu)).rjust(cw), st)
                elif name == "mem%":
                    st = self.gstyle(0.35 + 0.65 * min(1.0, p.mem / 50)) if p.mem >= 1 else self.s_dim
                    cv.put(xx, yy, ("%.1f" % p.mem).rjust(cw), st)
                elif name == "time":
                    cv.put(xx, yy, fmt_ptime(p.ticks).rjust(cw), self.s_dim)
                xx += cw + 1
            cx = cmd_x
            avail = ix + iw - cx
            if prefix:
                cx = cv.put(cx, yy, fit(prefix, avail), self.s_track)
            cmd = clean(p.cmd[:iw + 1])
            # highlight the program name, dim the arguments
            head, rest = split_command(cmd)
            nm_st = (None, None, BOLD) if p.state in "RD" else PLAIN
            cx = cv.put(cx, yy, fit(head, ix + iw - cx), nm_st)
            if rest and cx < ix + iw - 1:
                cv.put(cx, yy, fit(rest, ix + iw - cx), self.s_dim)
            if i == self.sel_idx:
                if self.color:
                    cv.style_row(ix - 1, yy, iw + 2, (None, th.sel, 0))
                    # undo dim on the selected row for legibility
                    srow = cv.st[yy]
                    for k in range(ix - 1, ix + iw + 1):
                        fg, bg, a = srow[k]
                        srow[k] = (fg, bg, (a & ~DIM) | (BOLD if k < cmd_x else a & BOLD))
                else:
                    cv.style_row(ix - 1, yy, iw + 2, (None, None, REV))
        if len(view) > rows > 0:  # scroll indicator on the right border
            pos = int(self.scroll / max(1, len(view) - rows) * (rows - 1))
            cv.put(x + w - 1, iy + 1 + pos, "┃", self.gstyle(0.6))

    # ── overlays ────────────────────────────────────────────────────────────
    def overlay_box(self, cv, W, H, bw, bh, title):
        bw, bh = min(bw, W - 2), min(bh, H - 2)
        x, y = (W - bw) // 2, max(1, (H - bh) // 2)
        cv.fill(x, y, bw, bh)
        self.box(cv, x, y, bw, bh, [(title, self.s_title)])
        return x, y, bw, bh

    def draw_help(self, cv, W, H):
        th = self.theme
        x, y, bw, bh = self.overlay_box(cv, W, H, 64, len(HELP) + 4, "help")
        acc = (th.c[1], None, BOLD) if self.color else (None, None, BOLD)
        for i, (k, desc) in enumerate(HELP):
            yy = y + 1 + i
            if yy >= y + bh - 2:
                break
            if desc is None:
                cv.put(x + 2, yy, k, self.gstyle(0.9, BOLD) if self.color else (None, None, BOLD | ULINE))
            else:
                cv.put(x + 4, yy, k, acc)
                cv.put(x + 20, yy, fit(desc, bw - 22), PLAIN)
        cv.put(x + 2, y + bh - 2, fit("press any key to close  ·  sonar %s" % VERSION, bw - 4), self.s_dim)

    def open_picker(self):
        ci = next((i for i, (c, names) in enumerate(self.cats) if self.theme.name in names), 0)
        names = self.cats[ci][1]
        self.picker = {"orig": self.theme.name, "cat": ci,
                       "pos": names.index(self.theme.name) if self.theme.name in names else 0}
        self.mode = "picker"

    def picker_key(self, k):
        pk = self.picker
        if k in ("left", "h", "right", "l"):
            n = len(self.cats[pk["cat"]][1])
            pk["pos"] = (pk["pos"] + (1 if k in ("right", "l") else -1)) % n
        elif k in ("tab", "btab", "up", "down", "k", "j"):
            step = -1 if k in ("btab", "up", "k") else 1
            pk["cat"] = (pk["cat"] + step) % len(self.cats)
            pk["pos"] = 0
        elif k == "enter":
            try:
                path = save_theme(self.theme.name)
                self.flash("theme '%s' saved to %s" % (self.theme.name, path.replace(os.path.expanduser("~"), "~")))
            except OSError as e:
                self.flash("could not save theme: %s" % e.strerror, err=True)
            self.mode, self.picker = "normal", None
            return
        elif k in ("esc", "q", "c"):
            self.theme = Theme(pk["orig"])
            self.mode, self.picker = "normal", None
            return
        self.theme = Theme(self.cats[pk["cat"]][1][pk["pos"]])

    def draw_picker(self, cv, W, H):
        th, pk = self.theme, self.picker
        x, y, bw, bh = self.overlay_box(cv, W, H, 58, 11, "theme")
        ix, iw = x + 2, bw - 4
        # category tabs
        xx = ix
        for i, (cat, _) in enumerate(self.cats):
            active = i == pk["cat"]
            st = (th.c[1], None, BOLD | ULINE) if active and self.color else \
                (None, None, BOLD | ULINE) if active else self.s_dim
            xx = cv.put(xx, y + 1, cat, st) + 3
        names = self.cats[pk["cat"]][1]
        label = "‹  %s  ›" % th.name
        cv.put(x + (bw - len(label)) // 2, y + 3, label, (th.c[2], None, BOLD) if self.color else (None, None, BOLD))
        sw = iw - 4
        for i in range(sw):
            cv.put(ix + 2 + i, y + 4, "█", (th.grad(i / max(1, sw - 1)), None, 0) if self.color else PLAIN)
        wave = [0.5 + 0.45 * math.sin(i / 5.0) * math.cos(i / 17.0) for i in range(2 * sw)]
        braille_graph(cv, ix + 2, y + 5, sw, 2, wave, th, up=True)
        dots = " ".join("●" if i == pk["pos"] else "·" for i in range(len(names)))
        cv.put(x + (bw - len(dots)) // 2, y + 7, fit(dots, iw), self.gstyle(0.6))
        hint = "←/→ theme · tab category · enter save · esc cancel"
        cv.put(x + max(2, (bw - len(hint)) // 2), y + 9, fit(hint, iw), self.s_dim)

    # ── input ───────────────────────────────────────────────────────────────
    def key(self, k):
        if k == "ctrl-c":
            self.running = False
            return
        if self.mode == "help":
            self.mode = "normal"
            return
        if self.mode == "picker":
            self.picker_key(k)
            return
        if self.mode == "confirm":
            pid, name, sig = self.confirm
            self.mode, self.confirm = "normal", None
            if k in ("y", "Y"):
                self.kill(pid, name, sig)
            else:
                self.flash("kill cancelled")
            return
        if self.mode == "filter":
            if k == "esc":
                self.filter, self.mode = "", "normal"
            elif k == "enter":
                self.mode = "normal"
            elif k == "backspace":
                self.filter = self.filter[:-1]
            elif k == "ctrl-u":
                self.filter = ""
            elif k in ("up", "down", "pgup", "pgdn"):
                self.move({"up": -1, "down": 1, "pgup": -self.page, "pgdn": self.page}[k])
                return
            elif len(k) == 1 and k.isprintable():
                self.filter += k
            else:
                return
            self.sel_idx, self.sel_pid, self.scroll = 0, None, 0
            return
        # normal mode
        if k in ("q", "ctrl-d"):
            self.running = False
        elif k in ("up", "k"):
            self.move(-1)
        elif k in ("down", "j"):
            self.move(1)
        elif k == "pgup":
            self.move(-self.page)
        elif k == "pgdn":
            self.move(self.page)
        elif k in ("home", "g"):
            self.move(-len(self.view))
        elif k in ("end", "G"):
            self.move(len(self.view))
        elif k in ("x", "del", "X"):
            p = self.selected()
            if p:
                if WINDOWS:  # Windows has a single way to end a process
                    sig = "terminate"
                else:
                    sig = "SIGKILL" if k == "X" else "SIGTERM"
                self.confirm = (p.pid, p.name, sig)
                self.mode = "confirm"
        elif k == "/":
            self.mode = "filter"
        elif k == "esc":
            if self.filter:
                self.filter = ""
                self.sel_idx, self.sel_pid = 0, None
        elif k == "s":
            self.sort = SORTS[(SORTS.index(self.sort) + 1) % len(SORTS)]
            self.flash("sort by " + self.sort, secs=1.5)
        elif k == "r":
            self.reverse = not self.reverse
        elif k == "t":
            self.tree = not self.tree
            self.flash("tree view " + ("on" if self.tree else "off"), secs=1.5)
        elif k == "u":
            self.mine = not self.mine
            self.sel_idx = 0
            self.flash(("only processes of " + current_user()) if self.mine else "all users", secs=1.5)
        elif k in "12345" and len(k) == 1:
            p = PANELS[int(k) - 1]
            self.visible[p] = not self.visible[p]
            self.flash("%s panel %s" % (p, "shown" if self.visible[p] else "hidden"), secs=1.5)
        elif k in ("+", "="):
            self.set_interval(-1)
        elif k in ("-", "_"):
            self.set_interval(1)
        elif k in ("p", " "):
            self.paused = not self.paused
        elif k == "c":
            self.open_picker()
        elif k == "?":
            self.mode = "help"

    def set_interval(self, step):
        i = min(range(len(INTERVALS)), key=lambda j: abs(INTERVALS[j] - self.interval))
        self.interval = INTERVALS[max(0, min(len(INTERVALS) - 1, i + step))]
        self.flash("refresh every %gs" % self.interval, secs=1.5)

    def kill(self, pid, name, sig):
        try:
            if WINDOWS:
                win_kill(pid)
                self.flash("terminated %s (%d)" % (name, pid))
            else:
                os.kill(pid, getattr(signal, sig))
                self.flash("sent %s to %s (%d)" % (sig, name, pid))
        except ProcessLookupError:
            self.flash("%s (%d) has already exited" % (name, pid), err=True)
        except PermissionError:
            owner = next((p.user for p in self.sys.procs.procs if p.pid == pid), "another user")
            hint = "run sonar as administrator" if WINDOWS else "run sonar as that user or root"
            self.flash("permission denied: %s (%d) belongs to %s — %s" % (name, pid, owner, hint), err=True, secs=5)
        except OSError as e:
            self.flash("kill failed: %s" % e.strerror, err=True)


# ═════════════════════════════════════════════════════════════════════════════
#  Terminal & main loop
# ═════════════════════════════════════════════════════════════════════════════

ENTER_SEQ = "\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[2J\x1b[H"   # alt screen, hide cursor, no autowrap
LEAVE_SEQ = "\x1b[0m\x1b[2J\x1b[?7h\x1b[?25h\x1b[?1049l"


def _exit_on_signal(*_):
    raise SystemExit(0)


class Terminal:
    """POSIX: alternate screen, hidden cursor, raw keyboard; always restored."""

    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.out = sys.stdout.fileno()
        self.saved = None
        self.rpipe = self.wpipe = None
        self.old_wakeup = -1

    def write(self, s):
        data = s.encode("utf-8")
        while data:
            try:
                n = os.write(self.out, data)
            except InterruptedError:
                continue
            except BlockingIOError:
                select.select([], [self.out], [], 0.5)
                continue
            data = data[n:]

    def enter(self):
        self.saved = termios.tcgetattr(self.fd)
        atexit.register(self.restore)
        # SIGWINCH needs a Python handler so the wakeup fd interrupts select()
        self.rpipe, self.wpipe = os.pipe()
        os.set_blocking(self.rpipe, False)
        os.set_blocking(self.wpipe, False)
        signal.signal(signal.SIGWINCH, lambda *_: None)
        signal.signal(signal.SIGTERM, _exit_on_signal)
        signal.signal(signal.SIGHUP, _exit_on_signal)
        self.old_wakeup = signal.set_wakeup_fd(self.wpipe)
        tty.setraw(self.fd)
        self.write(ENTER_SEQ)

    def restore(self):
        if self.saved is None:
            return
        try:
            self.write(LEAVE_SEQ)
        except OSError:
            pass
        try:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        except termios.error:
            pass
        self.saved = None
        signal.set_wakeup_fd(self.old_wakeup)
        for fd in (self.rpipe, self.wpipe):
            try:
                os.close(fd)
            except (OSError, TypeError):
                pass

    def size(self):
        try:
            sz = os.get_terminal_size(self.out)
            return sz.columns, sz.lines
        except OSError:
            return 80, 24

    def read_keys(self, timeout):
        """Wait up to `timeout` for keys (or a resize). Returns a list, None on EOF."""
        try:
            ready, _, _ = select.select([self.fd, self.rpipe], [], [], timeout)
        except InterruptedError:
            return []
        if self.rpipe in ready:
            try:
                os.read(self.rpipe, 512)
            except BlockingIOError:
                pass
        if self.fd in ready:
            data = os.read(self.fd, 4096)
            return parse_keys(data) if data else None
        return []


WIN_SCAN = {"H": "up", "P": "down", "K": "left", "M": "right", "I": "pgup", "Q": "pgdn",
            "G": "home", "O": "end", "S": "del", "\x0f": "btab"}
WIN_CHARS = {"\r": "enter", "\n": "enter", "\t": "tab", "\x08": "backspace", "\x7f": "backspace",
             "\x1b": "esc", "\x03": "ctrl-c", "\x04": "ctrl-d", "\x15": "ctrl-u"}


def parse_win_keys(chars):
    """msvcrt.getwch() stream → key names (special keys come as '\\xe0'/'\\x00' + scan code)."""
    keys, i = [], 0
    while i < len(chars):
        c = chars[i]
        if c in ("\x00", "\xe0") and i + 1 < len(chars):
            k = WIN_SCAN.get(chars[i + 1])
            if k:
                keys.append(k)
            i += 2
            continue
        keys.append(WIN_CHARS.get(c, c))
        i += 1
    return keys


class WinTerminal:
    """Windows console: VT processing on, line input/echo off, UTF-8 output; always restored."""

    ENABLE_PROCESSED_OUTPUT, ENABLE_VT = 0x0001, 0x0004
    ENABLE_LINE_INPUT, ENABLE_ECHO_INPUT, ENABLE_QUICK_EDIT, ENABLE_EXTENDED_FLAGS = 0x2, 0x4, 0x40, 0x80

    def __init__(self):
        self.hout = _k32.GetStdHandle(DWORD(-11 & 0xFFFFFFFF))
        self.hin = _k32.GetStdHandle(DWORD(-10 & 0xFFFFFFFF))
        self.saved = None
        self.out = sys.stdout.buffer

    def write(self, s):
        self.out.write(s.encode("utf-8"))
        self.out.flush()

    def enter(self):
        om, im = DWORD(), DWORD()
        if not (_k32.GetConsoleMode(self.hout, ctypes.byref(om)) and _k32.GetConsoleMode(self.hin, ctypes.byref(im))):
            raise OSError("not a Windows console")
        self.saved = (om.value, im.value, _k32.GetConsoleOutputCP())
        atexit.register(self.restore)
        if not _k32.SetConsoleMode(self.hout, om.value | self.ENABLE_PROCESSED_OUTPUT | self.ENABLE_VT):
            self.saved = None
            raise OSError("this console has no ANSI/VT support (Windows 10 1809+ or Windows Terminal needed)")
        new_in = (im.value & ~(self.ENABLE_LINE_INPUT | self.ENABLE_ECHO_INPUT | self.ENABLE_QUICK_EDIT)) \
            | self.ENABLE_EXTENDED_FLAGS
        _k32.SetConsoleMode(self.hin, new_in)
        _k32.SetConsoleOutputCP(65001)
        signal.signal(signal.SIGTERM, _exit_on_signal)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _exit_on_signal)
        self.write(ENTER_SEQ)

    def restore(self):
        if self.saved is None:
            return
        try:
            self.write(LEAVE_SEQ)
        except OSError:
            pass
        om, im, cp = self.saved
        _k32.SetConsoleMode(self.hout, om)
        _k32.SetConsoleMode(self.hin, im)
        _k32.SetConsoleOutputCP(cp)
        self.saved = None

    def size(self):
        try:
            sz = os.get_terminal_size()
            return sz.columns, sz.lines
        except OSError:
            return 80, 24

    def read_keys(self, timeout):
        """Poll the console (no select() on Windows); returns early on a key or a resize."""
        end = time.monotonic() + timeout
        start_size = self.size()
        while True:
            if msvcrt.kbhit():
                chars = []
                while msvcrt.kbhit():
                    chars.append(msvcrt.getwch())
                return parse_win_keys(chars)
            if time.monotonic() >= end or self.size() != start_size:
                return []
            time.sleep(0.025)


def run(app):
    term = WinTerminal() if WINDOWS else Terminal()
    term.enter()
    try:
        prev_lines, size = [], None
        app.sys.sample()
        next_sample = time.monotonic() + min(0.3, app.interval)
        while app.running:
            now = time.monotonic()
            if now >= next_sample:
                if not app.paused:
                    app.sys.sample()
                next_sample = now + app.interval
            if term.size() != size:  # first frame, or the terminal was resized
                size = term.size()
                prev_lines = []
                term.write("\x1b[0m\x1b[2J")
            W, H = size
            # build the whole frame in memory, then write only the lines that changed
            cv = app.frame(W, H)
            lines = [cv.line(y, app.color) for y in range(H)]
            out = ["\x1b[%d;1H%s" % (y + 1, line) for y, line in enumerate(lines)
                   if y >= len(prev_lines) or prev_lines[y] != line]
            if out:
                term.write("".join(out))
            prev_lines = lines
            # sleep until the next sample, the next clock second, or input
            now = time.monotonic()
            tick = 1.0 - (time.time() % 1.0)
            try:
                keys = term.read_keys(max(0.0, min(next_sample - now, tick + 0.002)))
            except KeyboardInterrupt:  # Ctrl+C delivered as a signal (Windows)
                keys = ["ctrl-c"]
            if keys is None:
                break
            for k in keys:
                app.key(k)
                if not app.running:
                    break
    finally:
        term.restore()


def snapshot(app):
    """--once: sample twice, print one frame to stdout, exit."""
    app.sys.sample()
    time.sleep(0.5)
    app.sys.sample()
    try:
        sz = os.get_terminal_size(sys.stdout.fileno())
        W, H = sz.columns, sz.lines
    except OSError:
        W, H = 100, 32
    W = int(os.environ.get("COLUMNS", W))
    H = int(os.environ.get("LINES", H))
    cv = app.frame(W, H)
    lines = [cv.line(y, app.color) if app.color else "".join(cv.ch[y]).rstrip() for y in range(H)]
    if not app.color:  # keep reverse/bold out of plain dumps
        pass
    sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))
    sys.stdout.flush()


def list_themes(current, color):
    out = []
    for cat, names in theme_categories():
        out.append(cat)
        for n in names:
            cols = TABLE[n][1]
            if color:
                th = Theme(n)
                sw = "".join("\x1b[38;2;%d;%d;%dm█" % th.grad(i / 15) for i in range(16)) + "\x1b[0m"
            else:
                sw = ""
            mark = "  ← current" if n == current else ""
            out.append("  %-10s %s  %s%s" % (n, sw, " ".join("#%02x%02x%02x" % c for c in cols), mark))
    print("\n".join(out))


def parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="sonar",
        description="sonar - a minimal, beautiful system monitor for the terminal.",
        epilog="keys: arrows/j k select · x kill · / filter · s sort · t tree · c theme · ? help · q quit")
    ap.add_argument("-t", "--theme", metavar="THEME", help="color theme (see -l)")
    ap.add_argument("-l", "--list", action="store_true", help="list available themes and exit")
    ap.add_argument("-c", "--choose", action="store_true", help="start with the theme picker open")
    ap.add_argument("-i", "--interval", metavar="SECONDS", type=float, default=1.0,
                    help="refresh interval, 0.25 to 5 (default: 1)")
    ap.add_argument("--no-color", action="store_true", help="disable colors (also honors NO_COLOR)")
    ap.add_argument("--once", action="store_true", help="print a single snapshot and exit")
    ap.add_argument("-V", "--version", action="version", version="sonar " + VERSION)
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    color = not args.no_color and not os.environ.get("NO_COLOR")
    theme = resolve_theme(args.theme)
    if args.theme and args.theme not in TABLE:
        sys.stderr.write("sonar: unknown theme '%s' (use -l to list themes)\n" % args.theme)
        return 2
    if args.list:
        list_themes(theme, color and sys.stdout.isatty())
        return 0
    if not 0.25 <= args.interval <= 5:
        sys.stderr.write("sonar: interval must be between 0.25 and 5 seconds\n")
        return 2
    if not WINDOWS and not os.path.isdir("/proc/self"):
        sys.stderr.write("sonar: /proc is not available (sonar supports Linux and Windows)\n")
        return 1
    app = App(theme, args.interval, color)
    if args.once:
        snapshot(app)
        return 0
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.stderr.write("sonar: needs an interactive terminal (try --once)\n")
        return 1
    if args.choose:
        app.open_picker()
    try:
        run(app)
    except KeyboardInterrupt:
        pass
    except OSError as e:
        if not WINDOWS:
            raise
        sys.stderr.write("sonar: %s\n" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
