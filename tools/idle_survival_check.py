"""The app must survive an idle page, and still exit once the window is gone.

Regression: the first heartbeat implementation exited as soon as the launcher
process was gone (which happens immediately when Chromium hands the URL to an
already running browser) and the page had been quiet for a few seconds.
"""
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
IDLE_SILENCE = 75          # seconds of no traffic, like a user just reading

sys.stdout.reconfigure(encoding='utf-8')


def tail(n=4):
    try:
        return LOG.read_text(encoding='utf-8', errors='replace').strip().splitlines()[-n:]
    except Exception:
        return []


def port():
    for line in reversed(tail(50)):
        if 'serving http://127.0.0.1:' in line:
            return int(line.split(':')[-1].rstrip('/'))
    return None


def hit(p, path='/api/status'):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{p}{path}', timeout=4) as r:
            return json.loads(r.read())
    except Exception as exc:
        return {'__error__': str(exc)}


APPDATA.mkdir(parents=True, exist_ok=True)
PROFILE.mkdir(parents=True, exist_ok=True)
subprocess.run(['taskkill', '/F', '/IM', 'ETS2Garage.exe'], capture_output=True)
subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
time.sleep(2)
if LOG.exists():
    LOG.unlink()

# an Edge already holding the profile => the launcher will hand off and exit
bg = subprocess.Popen([str(EDGE), f'--user-data-dir={PROFILE}',
                       '--no-first-run', '--no-default-browser-check',
                       'about:blank'])
time.sleep(6)
app = subprocess.Popen([str(EXE)])

p = None
for _ in range(45):
    time.sleep(2)
    p = port()
    if p and '__error__' not in hit(p):
        break
print(f'port={p} | first probe: {"ok" if "__error__" not in hit(p) else hit(p)}')

print(f'--- staying quiet for {IDLE_SILENCE}s (user is just looking at the model) ---')
time.sleep(IDLE_SILENCE)
st = hit(p)
alive_after_idle = '__error__' not in st
print(f'after {IDLE_SILENCE}s idle: server alive = {alive_after_idle}')
if alive_after_idle:
    print('   status:', st.get('status'), '| requests seen:', st.get('hits', {}).get('__total__'))

print('--- clicking around again must still work ---')
for _ in range(3):
    time.sleep(3)
    v = hit(p, '/api/vehicle?category=truck&id=scania.s_2016')
    print('   vehicle request:', 'ok' if '__error__' not in v else v)

print('--- closing the browser; app should exit on its own ---')
subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
bg.kill()
t0 = time.time()
while time.time() - t0 < 190:
    if app.poll() is not None:
        break
    time.sleep(3)
print(f'app exited: {app.poll() is not None} after {time.time() - t0:.0f}s')
for line in tail(3):
    print('   log:', line)
if app.poll() is None:
    app.kill()
subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
print('RESULT:', 'PASS' if alive_after_idle else 'FAIL')