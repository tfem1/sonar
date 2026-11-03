"""CI (Windows): an older sonar.exe must update itself to the freshly built one.

    python tests/exe_update_test.py dist/sonar.exe       (needs: pip install pyinstaller)

Builds a copy of sonar.exe that says it is version 0.0.1, points it at a fake
"latest release" (local file:// URLs), runs `sonar.exe --update`, and checks the
replacement, the cleanup of sonar.exe.old, and that a broken download changes nothing.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

new_exe = pathlib.Path(sys.argv[1]).resolve()
root = pathlib.Path(__file__).resolve().parent.parent
work = pathlib.Path(tempfile.mkdtemp())

src = (root / "sonar.py").read_text(encoding="utf-8")
(work / "sonar.py").write_text(re.sub(r'^VERSION = "[^"]+"', 'VERSION = "0.0.1"', src, count=1, flags=re.M),
                               encoding="utf-8")
subprocess.run([sys.executable, "-m", "PyInstaller", "--onefile", "--console", "--name", "sonar", "--log-level",
                "WARN", "--distpath", str(work / "dist"), "--workpath", str(work / "build"), "--specpath", str(work),
                str(work / "sonar.py")], check=True)

app = work / "app"
app.mkdir()
installed = app / "sonar.exe"
shutil.copy(work / "dist" / "sonar.exe", installed)

new_version = subprocess.run([str(new_exe), "-V"], capture_output=True, text=True, check=True).stdout.split()[-1]
release = {"tag_name": "v" + new_version,
           "assets": [{"name": "sonar.exe", "browser_download_url": new_exe.as_uri()}]}
(work / "release.json").write_text(json.dumps(release))
env = dict(os.environ, SONAR_RELEASE_API=(work / "release.json").as_uri())


def run(*args):
    r = subprocess.run([str(installed), *args], capture_output=True, text=True, env=env, timeout=300)
    print("$ sonar.exe", *args, "->", r.returncode, "\n", r.stdout, r.stderr, sep="")
    return r


assert run("-V").stdout.strip() == "sonar 0.0.1"
r = run("--update")
assert r.returncode == 0 and ("0.0.1 -> " + new_version) in r.stdout, "update failed"
assert (app / "sonar.exe.old").exists(), "previous exe should be kept as sonar.exe.old until next start"
assert run("-V").stdout.strip() == "sonar " + new_version, "new exe not in place"
assert not (app / "sonar.exe.old").exists(), "sonar.exe.old not cleaned up on next start"
assert "already up to date" in run("--update").stdout

# a newer release whose sonar.exe is broken must leave the installed exe untouched
(work / "bad.exe").write_bytes(b"MZ" + b"\0" * 2000000)
release = {"tag_name": "v99.0.0", "assets": [{"name": "sonar.exe", "browser_download_url": (work / "bad.exe").as_uri()}]}
(work / "release.json").write_text(json.dumps(release))
r = run("--update")
assert r.returncode == 1 and "nothing was changed" in r.stderr, "broken download not refused"
assert run("-V").stdout.strip() == "sonar " + new_version
assert not (app / "sonar.exe.new").exists()

print("self-update OK")
