"""Local HTTP service backing the garage UI."""
import io
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import catalog
import model3d
from mat import load_material
from scs import ScsArchive, ScsVfs, ScsError
from texture import extract_texture, gdeflate_available

# The desktop launcher keeps this process alive for exactly as long as the UI
# keeps talking to it: a Chromium `--app` launch can hand the URL to an already
# running browser process and exit immediately, so the browser process is not a
# reliable lifetime signal.
LAST_ACTIVITY = [time.time()]
REQUEST_COUNT = [0]


def touch_activity():
    LAST_ACTIVITY[0] = time.time()
    REQUEST_COUNT[0] += 1


def idle_seconds():
    return time.time() - LAST_ACTIVITY[0]


def requests_seen():
    return REQUEST_COUNT[0]


def _find_web_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [
        os.environ.get('ETS2GARAGE_WEB'),
        here,
        os.path.join(here, 'web'),
        os.path.join(here, '..', 'web'),
        os.path.join(getattr(sys, '_MEIPASS', here), 'web'),
        os.path.join(getattr(sys, '_MEIPASS', here), '_internal', 'web'),
    ]
    for c in cands:
        if c and os.path.isfile(os.path.join(c, 'index.html')):
            return os.path.abspath(c)
    return os.path.join(here, '..', 'web')


WEB_DIR = _find_web_dir()

DEFAULT_GAME_DIRS = [
    r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2',
    r'C:\SteamLibrary\steamapps\common\Euro Truck Simulator 2',
    r'E:\SteamLibrary\steamapps\common\Euro Truck Simulator 2',
    r'D:\Program Files (x86)\Steam\steamapps\common\Euro Truck Simulator 2',
    r'C:\Program Files (x86)\Steam\steamapps\common\Euro Truck Simulator 2',
]

ICON_PREFIXES = ('material/ui/accessory/', 'material/ui/', '')

BUILD_ID = '2026-10-28-launcher'


class NotReady(RuntimeError):
    """Raised when a request needs scanned game data that is not there yet."""

# helper geometry that should not be drawn in a showroom preview
SKIP_EFFECT_HINTS = ('shadow', 'fakeshadow', 'shadowonly')


def _skip_effect(effect):
    e = (effect or '').lower()
    return any(h in e for h in SKIP_EFFECT_HINTS)


class Garage:
    """Holds the mounted game data and every cache the UI needs."""

    def __init__(self):
        self.lock = threading.RLock()
        self.hits = {}
        self.vfs = None
        self.game_dir = None
        self.mod_dir = None
        self.vehicles = []
        self.status = 'idle'
        self.progress = ''
        self.error = None
        self.started = 0.0
        self.elapsed = 0.0
        self.stats = {}
        self._mesh_cache = {}
        self._texture_cache = {}
        self._png_cache = {}
        self._detail_cache = {}
        self._slot_index = {}
        self._material_cache = {}

    # ------------------------------------------------------------- scanning
    def detect(self):
        out = []
        for d in DEFAULT_GAME_DIRS:
            if os.path.isdir(d):
                out.append(d)
        return out

    def scan(self, game_dir, mod_dir=None):
        with self.lock:
            if self.status == 'scanning':
                return False
            self.status = 'scanning'
            self.progress = '正在打开游戏归档…'
            self.error = None
            self.started = time.time()
            t = threading.Thread(target=self._scan_worker, args=(game_dir, mod_dir), daemon=True)
            t.start()
            return True

    def _scan_worker(self, game_dir, mod_dir):
        try:
            extra = []
            if not mod_dir:
                docs = os.path.join(os.path.expanduser('~'), 'Documents',
                                    'Euro Truck Simulator 2', 'mod')
                if os.path.isdir(docs):
                    mod_dir = docs
            if mod_dir and os.path.isdir(mod_dir):
                extra = [mod_dir]
            names = ['base.scs', 'base_vehicle.scs', 'base_share.scs', 'base_cfg.scs',
                     'core.scs', 'def.scs', 'effect.scs', 'locale.scs', 'version.scs']
            present = [f for f in os.listdir(game_dir) if f.lower().endswith('.scs')]
            lower = {n.lower(): n for n in present}
            ordered = [lower[k] for k in names if k in lower]
            ordered += sorted(n for n in present if n not in ordered)
            if mod_dir and os.path.isdir(mod_dir):
                for n in sorted(os.listdir(mod_dir)):
                    if n.lower().endswith('.scs'):
                        ordered.append(os.path.join(mod_dir, n))
            total = len(ordered)
            archives = []
            for i, n in enumerate(ordered):
                self.progress = f'({i+1}/{total}) {os.path.basename(n)}'
                p = n if os.path.isabs(n) else os.path.join(game_dir, n)
                try:
                    a = ScsArchive(p)
                except ScsError as exc:
                    print(f'[scan] skip {n}: {exc}')
                    continue
                a.list_files()
                archives.append(a)
            self.progress = '正在合并文件索引…'
            vfs = ScsVfs(archives).index()
            self.progress = '正在读取本地化文本…'
            catalog.load_locale(vfs)
            self.progress = '正在扫描车辆…'
            vehicles = catalog.build_index(vfs, progress=lambda v: setattr(self, 'progress', f'车辆 {v}'))
            with self.lock:
                self.vfs = vfs
                self.game_dir = game_dir
                self.mod_dir = mod_dir
                self.vehicles = vehicles
                self._mesh_cache.clear()
                self._texture_cache.clear()
                self._png_cache.clear()
                self._detail_cache.clear()
                self._slot_index.clear()
                self._material_cache.clear()
                self.stats = {
                    'files': len(vfs.all_files()),
                    'archives': len(archives),
                    'vehicles': len(vehicles),
                    'trucks': sum(1 for v in vehicles if v['category'] == 'truck'),
                    'trailers': sum(1 for v in vehicles if v['category'] == 'trailer'),
                    'mods': len([1 for a in archives if mod_dir and os.path.dirname(a.path) == mod_dir]),
                    'gdeflate': gdeflate_available(),
                    'hits': dict(garage.hits),
                }
                self.status = 'ready'
                self.elapsed = time.time() - self.started
                self.progress = '就绪'
        except Exception as exc:                      # noqa: BLE001
            traceback.print_exc()
            with self.lock:
                self.status = 'error'
                self.error = f'{type(exc).__name__}: {exc}'
                self.progress = '失败'

    # ------------------------------------------------------------- accessors
    def require_ready(self):
        if self.status != 'ready' or self.vfs is None:
            raise NotReady('尚未扫描游戏目录，请先选择游戏路径并扫描')

    @property
    def ready(self):
        return self.status == 'ready' and self.vfs is not None

    def vehicle_detail(self, category, vid):
        self.require_ready()
        key = (category, vid)
        with self.lock:
            if key in self._detail_cache:
                return self._detail_cache[key]
        root = catalog.TRUCK_ROOT if category == 'truck' else catalog.TRAILER_ROOTS[0]
        detail = catalog.load_vehicle(self.vfs, category, vid, root=root)
        with self.lock:
            self._detail_cache[key] = detail
        return detail

    def slot_options(self, slot, query=None, limit=400):
        self.require_ready()
        with self.lock:
            if slot in self._slot_index:
                options = self._slot_index[slot]
            else:
                options = catalog.all_accessory_options(self.vfs).get(slot, [])
                self._slot_index[slot] = options
        if query:
            q = query.lower()
            options = [o for o in options
                       if q in o['name'].lower() or q in o['path'].lower()
                       or q in o.get('from_truck', '').lower()]
        return options[:limit]

    def material(self, path):
        self.require_ready()
        with self.lock:
            if path in self._material_cache:
                return self._material_cache[path]
        mat = load_material(self.vfs, path)
        with self.lock:
            self._material_cache[path] = mat
        return mat

    def mesh(self, path):
        if not self.ready:
            return None
        with self.lock:
            if path in self._mesh_cache:
                return self._mesh_cache[path]
        mesh = model3d.load_model(self.vfs, path, self._mesh_cache)
        return mesh

    def icon_path(self, icon):
        if not icon or not self.ready:
            return None
        icon = icon.lstrip('/')
        for pre in ICON_PREFIXES:
            for cand in (f'{pre}{icon}.tobj', f'{pre}{icon}/icon.tobj'):
                if self.vfs.exists(cand):
                    return cand
        return None

    def png(self, tobj_path, max_size=512):
        with self.lock:
            cached = self._png_cache.get(tobj_path)
        if cached is not None:
            return cached
        from PIL import Image
        if not self.ready:
            im = Image.new('RGBA', (2, 2), (40, 46, 58, 255))
            buf = io.BytesIO()
            im.save(buf, format='PNG')
            return buf.getvalue()
        try:
            dds, info = extract_texture(self.vfs, tobj_path)
            im = Image.open(io.BytesIO(dds))
            im.load()
            if im.mode not in ('RGB', 'RGBA'):
                im = im.convert('RGBA')
            if max(im.size) > max_size:
                im.thumbnail((max_size, max_size), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format='PNG', optimize=True)
            data = buf.getvalue()
        except Exception as exc:                       # noqa: BLE001
            print(f'[texture] {tobj_path}: {type(exc).__name__}: {exc}')
            im = Image.new('RGBA', (2, 2), (40, 46, 58, 255))
            buf = io.BytesIO()
            im.save(buf, format='PNG')
            data = buf.getvalue()
        with self.lock:
            self._png_cache[tobj_path] = data
        return data


garage = Garage()


# --------------------------------------------------------------------- HTTP
CTYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.mjs': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff2': 'font/woff2',
}


class Handler(BaseHTTPRequestHandler):
    server_version = 'ETS2Garage/1.0'
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def _hit(self, path):
        g = garage
        g.hits[path] = g.hits.get(path, 0) + 1
        g.hits['__total__'] = g.hits.get('__total__', 0) + 1

    # ---------------------------------------------------------------- utils
    def _send(self, code, body, ctype='application/json; charset=utf-8', extra=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _fail(self, exc):
        traceback.print_exc()
        self._json({'error': f'{type(exc).__name__}: {exc}'}, 500)

    def _query(self):
        u = urlparse(self.path)
        return u.path, {k: v[0] for k, v in parse_qs(u.query).items()}

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode('utf-8'))

    # ----------------------------------------------------------------- verbs
    def do_GET(self):                                    # noqa: N802
        touch_activity()
        path, q = self._query()
        try:
            if path.startswith('/api/'):
                return self.api_get(path, q)
            return self.static(path)
        except NotReady as exc:
            return self._json({'error': str(exc), 'not_ready': True}, 409)
        except Exception as exc:                          # noqa: BLE001
            return self._fail(exc)

    def do_POST(self):                                   # noqa: N802
        touch_activity()
        path, q = self._query()
        try:
            if path == '/api/scan':
                body = self._body()
                ok = garage.scan(body.get('path', ''), body.get('mod_dir'))
                return self._json({'started': ok, 'status': garage.status})
            if path == '/api/assemble':
                return self._json(self.assemble(self._body()))
            return self._json({'error': 'not found'}, 404)
        except NotReady as exc:
            return self._json({'error': str(exc), 'not_ready': True}, 409)
        except Exception as exc:                          # noqa: BLE001
            return self._fail(exc)

    # ------------------------------------------------------------------ api
    def api_get(self, path, q):
        self._hit(path)
        if path == '/api/status':
            return self._json({
                'build': BUILD_ID,
                'status': garage.status,
                'progress': garage.progress,
                'error': garage.error,
                'game_dir': garage.game_dir,
                'mod_dir': garage.mod_dir,
                'elapsed': round(garage.elapsed, 2),
                'stats': garage.stats,
                'hits': dict(garage.hits),
                'candidates': garage.detect(),
            })
        if path == '/api/vehicles':
            garage.require_ready()
            return self._json({'vehicles': garage.vehicles})
        if path == '/api/vehicle':
            d = garage.vehicle_detail(q.get('category', 'truck'), q.get('id', ''))
            return self._json(d)
        if path == '/api/ping':
            return self._json({'ok': True, 'seen': requests_seen(),
                               'idle': round(idle_seconds(), 1)})
        if path == '/api/slot':
            opts = garage.slot_options(q.get('slot', ''), q.get('q'))
            return self._json({'slot': q.get('slot', ''), 'options': opts,
                               'count': len(opts)})
        if path == '/api/mesh':
            mesh = garage.mesh(q.get('path', ''))
            if mesh is None:
                return self._json({'error': 'mesh not found'}, 404)
            return self._send(200, mesh.blob, 'application/octet-stream')
        if path == '/api/meshinfo':
            mesh = garage.mesh(q.get('path', ''))
            if mesh is None:
                return self._json({'error': 'mesh not found'}, 404)
            return self._json(mesh.manifest)
        if path == '/api/locators':
            mesh = garage.mesh(q.get('path', ''))
            if mesh is None:
                return self._json({'error': 'mesh not found'}, 404)
            variants = [v for v in (q.get('variant') or '').split(',') if v]
            locs = mesh.locators_for(variants) if variants else mesh.locators
            return self._json([{
                'name': l.name, 'index': l.index,
                'position': list(l.position), 'rotation': list(l.rotation),
                'scale': l.scale, 'hookup': l.hookup,
            } for l in locs])
        if path == '/api/texture':
            p = q.get('path', '')
            data = garage.png(p, int(q.get('size', 512)))
            return self._send(200, data, 'image/png')
        if path == '/api/icon':
            ip = garage.icon_path(q.get('icon', ''))
            if not ip:
                return self._json({'error': 'icon not found'}, 404)
            return self._send(200, garage.png(ip, int(q.get('size', 128))), 'image/png')
        return self._json({'error': 'not found'}, 404)

    # -------------------------------------------------------------- assemble
    def paint_info(self, def_path):
        """Resolve an accessory_paint_job_data into something the shader can use."""
        info = {'base': [1.0, 1.0, 1.0], 'secondary': None,
                'variants': [], 'mask': None, 'def': def_path}
        if not def_path or not garage.ready:
            return info
        unit = catalog.load_unit(garage.vfs, def_path)
        if unit is None:
            return info
        bc = unit.get('base_color')
        if isinstance(bc, tuple) and len(bc) >= 3:
            info['base'] = [float(v) for v in bc[:3]]
        sc = unit.get('secondary_color')
        if isinstance(sc, tuple) and len(sc) >= 3:
            info['secondary'] = [float(v) for v in sc[:3]]
        info['variants'] = [[float(x) for x in v[:3]]
                            for v in unit.list('color_variant')
                            if isinstance(v, tuple) and len(v) >= 3][:64]
        mask = unit.get('paint_job_mask')
        if isinstance(mask, str) and mask:
            rel = mask.lstrip('/')
            if garage.vfs.exists(rel):
                info['mask'] = rel
                info['mask_url'] = '/api/texture?path=' + rel + '&size=1024'
        info['name'] = catalog.localized(unit.get('name', unit.name), unit.name)
        return info

    def assemble(self, config):
        garage.require_ready()
        paint = self.paint_info(config.get('paint_job'))
        custom = config.get('paint_color')
        if isinstance(custom, (list, tuple)) and len(custom) >= 3:
            try:
                paint['base'] = [max(0.0, min(1.0, float(v))) for v in custom[:3]]
                paint['custom'] = True
            except (TypeError, ValueError):
                pass
        instances, warnings = model3d.compose(garage.vfs, config, garage._mesh_cache)
        out = []
        for inst in instances:
            mesh = garage.mesh(inst['path'])
            if mesh is None:
                continue
            entry = dict(inst)
            entry['mesh_url'] = '/api/mesh?path=' + inst['path']
            entry['bounds'] = mesh.bounds()
            # a vehicle model bundles every configuration side by side; the PMD
            # variant table decides which parts belong to the selected cabin /
            # chassis (otherwise all axle variants would be drawn at once)
            vis = mesh.visible_parts(inst.get('variants'))
            entry['visible_parts'] = sorted(vis) if vis is not None else None
            entry['parts'] = mesh.manifest.get('parts')
            pieces = []
            for p in mesh.manifest['pieces']:
                mat_path = (mesh.materials[p['material']]
                            if p['material'] < len(mesh.materials) else '')
                effect = (garage.material(mat_path).effect if mat_path else '') or ''
                pentry = {
                    'material': p['material'],
                    'material_path': mat_path,
                    'effect': effect,
                    'part': p.get('part'),
                    'skip': _skip_effect(effect)
                            or (vis is not None and p.get('part') not in vis),
                    'count': p['count'],
                    'triangles': p['triangles'],
                    'sections': {k: v for k, v in p.items()
                                 if k in ('position', 'normal', 'uv0', 'uv1', 'uv2',
                                          'color', 'index')},
                }
                pieces.append(pentry)
            entry['pieces'] = pieces
            out.append(entry)
        materials = {}
        # every instance's materials must be published, otherwise accessories
        # (wheels included) render untextured
        for inst in out:
            mesh = garage.mesh(inst['path'])
            if mesh is None:
                continue
            for mp in mesh.materials:
                if mp in materials:
                    continue
                mat = garage.material(mp)
                tex = mat.base_texture()
                effect = mat.effect or ''
                materials[mp] = {
                    'effect': effect,
                    # truckpaint stores the paint colour in the vertex colours and
                    # uses the texture only as a subtle modulation; multiplying by
                    # it directly makes the body far too dark.
                    'is_paint': 'paint' in effect.lower(),
                    'diffuse': list(mat.diffuse) if isinstance(mat.diffuse, tuple) else None,
                    'textures': mat.textures,
                    'base': tex,
                    'base_url': ('/api/texture?path=' + tex.lstrip('/')) if tex else None,
                    'normal_url': None,
                    'paint': paint if 'paint' in effect.lower() else None,
                }
                nm = mat.normal_texture()
                if nm:
                    materials[mp]['normal_url'] = '/api/texture?path=' + nm.lstrip('/')
        return {'instances': out, 'warnings': warnings, 'materials': materials,
                'paint': paint}

    # ---------------------------------------------------------------- static
    def static(self, path):
        self._hit('static' + os.path.splitext(path)[1].lower())
        if path in ('/', ''):
            path = '/index.html'
        if path == '/favicon.ico' and not os.path.isfile(
                os.path.join(WEB_DIR, 'favicon.ico')):
            # answer quietly when web/favicon.ico is absent: browsers request it
            # unprompted and a 404 there looks like an application error
            return self._send(204, b'', 'image/x-icon')
        p = os.path.normpath(os.path.join(WEB_DIR, path.lstrip('/')))
        if not p.startswith(os.path.normpath(WEB_DIR)) or not os.path.isfile(p):
            return self._send(404, b'not found', 'text/plain; charset=utf-8')
        ext = os.path.splitext(p)[1].lower()
        with open(p, 'rb') as fh:
            data = fh.read()
        return self._send(200, data, CTYPES.get(ext, 'application/octet-stream'))


def serve(port=0, host='127.0.0.1'):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    httpd = serve(port)
    print(f'serving on http://127.0.0.1:{httpd.server_address[1]}')
    httpd.serve_forever()