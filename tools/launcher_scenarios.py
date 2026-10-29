"""Both launcher scenarios: URL hand-off and a window we own ourselves."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

EXE = Path(r'F:\code\car-share\dist\ETS2Garage.exe')
APPDATA = Path(os.environ['LOCALAPPDATA']) / 'ETS2Garage'
LOG = APPDATA / 'app.log'
EDGE = Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
PROFILE = APPDATA / 'window-profile'

sys.stdout.reconfigure(encoding='utf-8')


def tail(n=6):
    try:
        return LOG.read_text(encoding='utf-8', errors='replace').strip().splitlines()[-n:]
    except Exception:
        return []


def port():
    for line in reversed(tail(60)):
        if 'serving http://127.0.0.1:' in line:
            return int(line.split(':')[-1].rstrip('/'))
    return None


def alive(p):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{p}/api/status', timeout=4) as r:
            return json.loads(r.read())
    except Exception:
        return None


def run(handoff, quiet, label):
    subprocess.run(['taskkill', '/F', '/IM', 'ETS2Garage.exe'], capture_output=True)
    subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
    time.sleep(2)
    if LOG.exists():
        LOG.unlink()
    bg = None
    if handoff:
        PROFILE.mkdir(parents=True, exist_ok=True)
        bg = subprocess.Popen([str(EDGE), f'--user-data-dir={PROFILE}',
                               '--no-first-run', '--no-default-browser-check',
                               'about:blank'])
        time.sleep(6)
    app = subprocess.Popen([str(EXE)])
    p = None
    for _ in range(45):
        time.sleep(2)
        p = port()
        if p and alive(p):
            break
    ok_start = bool(p and alive(p))
    print(f'[{label}] served on {p}: {ok_start}')
    if quiet:
        time.sleep(quiet)
        ok_idle = alive(p) is not None
        print(f'[{label}] after {quiet}s of silence the server is '
              f'{"STILL ALIVE" if ok_idle else "DEAD <-- PROBLEM"}')
    subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
    if bg:
        bg.kill()
    t0 = time.time()
    while time.time() - t0 < 200:
        if app.poll() is not None:
            break
        time.sleep(2)
    dt = time.time() - t0
    print(f'[{label}] exit after closing the window: {app.poll() is not None} in {dt:.0f}s')
    for line in tail(2):
        print('     log:', line)
    if app.poll() is None:
        app.kill()
    subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
    return ok_start, dt


print('=== scenario A: browser already running (URL hand-off) ===')
run(True, 80, 'A')

print('=== scenario B: we own the window ===')
ok, dt = run(False, 80, 'B')
print()
print('RESULT: A idle-survival checked above; B exits in %.0fs' % dt)