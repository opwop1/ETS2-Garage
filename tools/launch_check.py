"""Reproduce the 'ERR_CONNECTION_REFUSED' startup failure and check the fix.

Chromium `--app` hands the URL to an already running browser process for the
same profile and exits immediately; the launcher must therefore not treat that
process as the application's lifetime.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

EXE = Path(r'F:\code\car-share\dist\ETS2Garage.exe')
APPDATA = Path(os.environ['LOCALAPPDATA']) / 'ETS2Garage'
LOG = APPDATA / 'app.log'
EDGE = Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
PROFILE = APPDATA / 'window-profile'

sys.stdout.reconfigure(encoding='utf-8')


def log_tail(n=6):
    try:
        return LOG.read_text(encoding='utf-8', errors='replace').strip().splitlines()[-n:]
    except Exception:
        return []


def port_from_log():
    for line in reversed(log_tail(40)):
        if 'serving http://127.0.0.1:' in line:
            return int(line.split(':')[-1].rstrip('/'))
    return None


def probe(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


def running():
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ETS2Garage.exe'],
                         capture_output=True, text=True).stdout
    return 'ETS2Garage.exe' in out


print('--- scenario: a browser for this profile is already running ---')
APPDATA.mkdir(parents=True, exist_ok=True)
PROFILE.mkdir(parents=True, exist_ok=True)
subprocess.run(['taskkill', '/F', '/IM', 'ETS2Garage.exe'], capture_output=True)
subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
time.sleep(2)
if LOG.exists():
    LOG.unlink()

# keep an Edge holding this profile alive, so the launcher will hand off
bg = subprocess.Popen([str(EDGE), f'--user-data-dir={PROFILE}',
                       '--no-first-run', '--no-default-browser-check',
                       'about:blank'])
time.sleep(6)
print('background Edge running:', bg.poll() is None)

app = subprocess.Popen([str(EXE)])
port = None
for _ in range(45):
    time.sleep(2)
    port = port_from_log()
    if port and probe(port):
        break
print('port from log:', port)
time.sleep(4)
st = probe(port) if port else None
print('served:', bool(st), '| window hits:', (st or {}).get('hits', {}).get('__total__'))
print('launcher process alive:', app.poll() is None)
for line in log_tail(5):
    print('   log:', line)

print('--- closing the browser window; the app should shut itself down ---')
subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
bg.kill()
t0 = time.time()
while time.time() - t0 < 140:
    if app.poll() is not None:
        break
    time.sleep(3)
print(f'app exited: {app.poll() is not None} after {time.time() - t0:.0f}s')
for line in log_tail(3):
    print('   log:', line)
if app.poll() is None:
    app.kill()
subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)