"""Desktop entry point: local server + native window (WebView2 via pywebview)."""
import json
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
# PyInstaller onefile: modules live next to this file inside _MEIPASS
if getattr(sys, 'frozen', False):
    BASE = sys._MEIPASS
    if BASE not in sys.path:
        sys.path.insert(0, BASE)
    os.environ.setdefault('ETS2GARAGE_WEB', os.path.join(BASE, 'web'))

import server as garage_server                     # noqa: E402

CONFIG_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
                          'ETS2Garage')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.json')

# how long the UI may stay silent before we assume its window is gone. Must be
# comfortably longer than the page heartbeat, and longer than the ~60 s timer
# throttling Chrome applies to a minimized (hidden) window.
IDLE_EXIT = 120.0
# how long to wait for a browser that is still starting up
FIRST_UI_GRACE = 150.0
# A launcher that lives at least this long owned a real window; one that exits
# sooner merely handed the URL to an already running browser, and its exit must
# never be read as "the window closed" -- doing that killed the running app.
OWNERSHIP_MIN = 10.0


def load_config():
    try:
        with open(CONFIG_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:                                  # noqa: BLE001
        return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=1)
    except Exception:                                  # noqa: BLE001
        pass


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Api:
    """Exposed to JavaScript as window.pywebview.api."""

    def __init__(self, window=None):
        self.window = window
        self.config = load_config()

    def pick_directory(self):
        import webview
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            path = result[0] if isinstance(result, (list, tuple)) else result
            self.config['game_dir'] = path
            save_config(self.config)
            return path
        return None

    def pick_file(self):
        import webview
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=('SCS archives (*.scs)', 'All files (*.*)'))
        return result[0] if result else None

    def remember(self, key, value):
        self.config[key] = value
        save_config(self.config)
        return True

    def recall(self):
        return self.config


def log(msg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(os.path.join(CONFIG_DIR, 'app.log'), 'a', encoding='utf-8') as fh:
            fh.write(f'{time.strftime("%H:%M:%S")} {msg}\n')
    except Exception:                                  # noqa: BLE001
        pass
    try:
        print(msg)
    except Exception:                                  # noqa: BLE001
        pass


def _auto_scan(cfg):
    game = cfg.get('game_dir')
    if game and os.path.isdir(game):
        garage_server.garage.scan(game, cfg.get('mod_dir'))


def find_chromium():
    """Locate an installed Chromium-based browser for --app window mode."""
    import shutil
    names = ['msedge.exe', 'chrome.exe', 'brave.exe', 'msedge']
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    roots = [
        os.environ.get('ProgramFiles', r'C:\Program Files'),
        os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
        os.environ.get('LOCALAPPDATA', ''),
    ]
    rels = [
        r'Microsoft\Edge\Application\msedge.exe',
        r'Google\Chrome\Application\chrome.exe',
        r'BraveSoftware\Brave-Browser\Application\brave.exe',
    ]
    for r in roots:
        if not r:
            continue
        for rel in rels:
            p = os.path.join(r, rel)
            if os.path.isfile(p):
                return p
    return None


def open_app_window(url, cfg):
    """Open the UI in a dedicated Chromium app window (no tabs, own profile).

    Returns the launcher process, or None when no browser was found. The
    launcher must *not* be treated as the window: when an Edge/Chrome instance
    for this profile is already running (Edge keeps a background process after
    its windows close), the new launcher hands the URL over and exits at once.
    """
    import subprocess
    exe = find_chromium()
    if not exe:
        return None
    profile = os.path.join(CONFIG_DIR, 'window-profile')
    os.makedirs(profile, exist_ok=True)
    args = [
        exe,
        f'--app={url}',
        '--window-size=1600,980',
        '--window-position=60,40',
        f'--user-data-dir={profile}',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-features=Translate,MediaRouter',
        '--allow-file-access-from-files',
    ]
    log(f'[ets2garage] app window: {exe} {url}')
    try:
        return subprocess.Popen(args)
    except Exception as exc:                            # noqa: BLE001
        log(f'[ets2garage] could not launch {exe}: {exc}')
        return None


def wait_for_ui(proc=None):
    """Keep serving until the UI stops talking to us.

    The page polls ``/api/ping``; once those calls stop (or the browser process
    we started exits) this returns and the app shuts down. Relying on the
    heartbeat instead of the process handle is what makes an ``--app`` hand-off
    to an already running browser work.
    """
    started = time.time()
    exited_at = None
    while True:
        time.sleep(2)
        now = time.time()
        idle = garage_server.idle_seconds()
        seen = garage_server.requests_seen()
        if proc is not None and proc.poll() is not None and exited_at is None:
            exited_at = now
            log(f'[ets2garage] browser launcher exited after '
                f'{exited_at - started:.1f}s')
        # Only a launcher that lived long enough to own a real window tells us
        # the window is closed. A quick exit is a URL hand-off to an already
        # running browser: the page keeps being served either way, and exiting
        # on it while the user is simply not clicking is what killed the app.
        if (exited_at is not None and exited_at - started >= OWNERSHIP_MIN
                and now - exited_at >= 2):
            log('[ets2garage] window closed, exiting')
            return
        if idle < IDLE_EXIT:
            continue
        if seen == 0 and now - started < FIRST_UI_GRACE:
            continue                     # browser may still be starting up
        log(f'[ets2garage] shutting down (idle {idle:.0f}s, requests {seen})')
        return


def main():
    port = int(os.environ.get('ETS2GARAGE_PORT') or 0) or free_port()
    httpd = None
    for attempt in range(20):
        try:
            httpd = garage_server.serve(port)
            break
        except OSError as exc:
            log(f'[ets2garage] port {port} unavailable ({exc}); trying another')
            port = free_port()
    if httpd is None:
        log('[ets2garage] could not bind any port')
        return 1
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    url = f'http://127.0.0.1:{port}/'
    log(f'[ets2garage] serving {url}')

    cfg = load_config()
    shell = (os.environ.get('ETS2GARAGE_SHELL') or 'window').lower()

    if shell == 'webview':
        try:
            return run_webview(url, cfg)
        except Exception as exc:                       # noqa: BLE001
            log(f'[ets2garage] webview failed: {exc}')

    if shell in ('window', 'auto', 'edge'):
        try:
            proc = open_app_window(url, cfg)
            if proc is not None:
                wait_for_ui(proc)
                return 0
        except Exception as exc:                       # noqa: BLE001
            log(f'[ets2garage] app window failed: {exc}')

    if shell == 'browser' or shell in ('auto', 'edge', 'window'):
        import webbrowser
        log('[ets2garage] falling back to default browser')
        _auto_scan(cfg)
        webbrowser.open(url)
        wait_for_ui(None)
        return 0


if __name__ == '__main__':
    sys.exit(main() or 0)


def run_webview(url, cfg):
    import webview
    api = Api()
    window = webview.create_window(
        '欧卡2 车辆配件搭配助手 · ETS2 Garage',
        url, js_api=api, width=1600, height=980, min_size=(1200, 720),
        background_color='#0b0f16', text_select=True)
    api.window = window

    def on_loaded():
        time.sleep(0.4)
        _auto_scan(cfg)

    window.events.loaded += on_loaded
    webview.start(debug=bool(os.environ.get('ETS2GARAGE_DEBUG')))
    return True


def main():
    port = int(os.environ.get('ETS2GARAGE_PORT') or 0) or free_port()
    httpd = garage_server.serve(port)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    url = f'http://127.0.0.1:{port}/'
    log(f'[ets2garage] serving {url}')

    cfg = load_config()
    shell = (os.environ.get('ETS2GARAGE_SHELL') or 'window').lower()

    if shell == 'webview':
        try:
            return run_webview(url, cfg)
        except Exception as exc:                       # noqa: BLE001
            log(f'[ets2garage] webview failed: {exc}')

    if shell in ('window', 'auto', 'edge'):
        try:
            if run_app_window(url, cfg):
                return
        except Exception as exc:                       # noqa: BLE001
            log(f'[ets2garage] app window failed: {exc}')

    if shell == 'browser' or shell in ('auto', 'edge', 'window'):
        import webbrowser
        log('[ets2garage] falling back to default browser')
        _auto_scan(cfg)
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()