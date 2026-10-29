"""Build the catalogue of trucks, trailers and accessories from def/*.sii."""
import os
import re

from sii import Unit, parse, parse_bytes, decode_localized, expand_includes, make_vfs_resolver

TRUCK_ROOT = 'def/vehicle/truck'
TRAILER_ROOTS = ('def/vehicle/trailer_owned', 'def/vehicle/trailer')
GLOBAL_VEHICLE_ROOT = 'def/vehicle'
# wheels of owned trailers live in their own shared folder
WHEEL_ROOTS = (GLOBAL_VEHICLE_ROOT, f'{GLOBAL_VEHICLE_ROOT}/trailer_wheel')

# wheels are defined once globally and attached to chassis wheel locators
WHEEL_SLOTS = {
    'f_tire': 'wheel_f', 'f_disc': 'wheel_f', 'f_hub': 'wheel_f', 'f_nuts': 'wheel_f',
    'f_rim': 'wheel_f',
    'r_tire': 'wheel_r', 'r_disc': 'wheel_r', 'r_hub': 'wheel_r', 'r_nuts': 'wheel_r',
    'r_rim': 'wheel_r',
}
WHEEL_LABELS = {
    'f_tire': '前轮胎', 'f_disc': '前轮毂盘', 'f_hub': '前轮芯', 'f_nuts': '前轮螺母',
    'f_rim': '前钢圈',
    'r_tire': '后轮胎', 'r_disc': '后轮毂盘', 'r_hub': '后轮芯', 'r_nuts': '后轮螺母',
    'r_rim': '后钢圈',
}
EXTRA_LABELS = {
    'interior': '驾驶舱内饰', 'engine': '发动机', 'transmission': '变速箱',
    'head_light': '大灯', 'steering_w': '方向盘', 'trlr_cables': '拖车线束',
    'tank': '油箱', 'frntglss_mid': '前挡风玻璃',
}
LOCALE_CANDIDATES = ('locale/zh_cn/localization.sui', 'locale/zh_cn/local.sii',
                     'locale/en_us/localization.sui', 'locale/en_us/local.sii',
                     'locale/en_gb/localization.sui')
PREFERRED_LANGS = ('zh_cn', 'zh_tw', 'en_us', 'en_gb')

_KV_RE = re.compile(r'(key|val)\[\]\s*:\s*"((?:[^"\\]|\\.)*)"', re.S)
_UNESCAPE = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}


def _parse_locale_pairs(text):
    """localization.sui is a flat list of key[]/val[] pairs."""
    out = {}
    pending = None
    for m in _KV_RE.finditer(text):
        kind, raw = m.group(1), m.group(2)
        val = re.sub(r'\\(.)', lambda mm: _UNESCAPE.get(mm.group(1), mm.group(1)), raw)
        if kind == 'key':
            pending = val
        elif pending is not None:
            out[pending] = val
            pending = None
    return out


def list_languages(vfs):
    if not vfs.exists('locale/zh_cn/localization.sui'):
        # locale.scs stores the language folders directly under its own root
        pass
    dirs, files = vfs.list_dir('locale')
    if files and not dirs:
        dirs = []
    return dirs


def load_locale(vfs, lang=None):
    global _locale
    if _locale is not None and lang is None:
        return _locale
    data_map = {}
    langs = [lang] if lang else []
    langs += [l for l in PREFERRED_LANGS if l not in langs]
    for l in langs:
        for name in ('localization.sui', 'local.sii', 'accessories.sui'):
            p = f'locale/{l}/{name}'
            data = vfs.read(p)
            if not data:
                continue
            text = data.decode('utf-8', 'replace').lstrip('\ufeff')
            try:
                data_map.update(_parse_locale_pairs(text))
            except Exception:                          # noqa: BLE001
                pass
        if data_map:
            break
    _locale = data_map
    return _locale

_unit_cache = {}
_locale = None
_resolver_for = None


def _raw_units(vfs, path):
    data = vfs.read(path)
    if not data:
        return {}
    text = data.decode('utf-8', 'replace').lstrip('\ufeff')
    global _resolver_for
    if _resolver_for is None:
        _resolver_for = {}
    resolver = _resolver_for.get(id(vfs))
    if resolver is None:
        resolver = make_vfs_resolver(vfs)
        _resolver_for[id(vfs)] = resolver
    text = expand_includes(text, path, resolver)
    try:
        return parse(text, path)
    except Exception as exc:                          # noqa: BLE001
        print(f'[catalog] parse failed {path}: {exc}')
        return {}


def load_unit(vfs, path):
    path = path.lstrip('/')
    if path in _unit_cache:
        return _unit_cache[path]
    units = _raw_units(vfs, path)
    unit = next(iter(units.values())) if units else None
    _unit_cache[path] = unit
    return unit


def _units_in(vfs, path):
    return _raw_units(vfs, path.lstrip('/'))


BRAND_CASE = {
    'daf': 'DAF', 'man': 'MAN', 'iveco': 'Iveco', 'scania': 'Scania',
    'volvo': 'Volvo', 'renault': 'Renault', 'mercedes': 'Mercedes-Benz',
    'schmitz': 'Schmitz', 'krone': 'Krone', 'kogel': 'Kögel',
    'kassbohrer': 'Kässbohrer', 'feldbinder': 'Feldbinder', 'wielton': 'Wielton',
    'tirsan': 'Tırsan', 'scs': 'SCS',
}


def prettify_id(vid):
    """'scania.s_2016' -> 'Scania S 2016', 'daf.xd' -> 'DAF XD'."""
    out = []
    for part in re.split(r'[._]', vid):
        if not part:
            continue
        low = part.lower()
        if low in BRAND_CASE:
            out.append(BRAND_CASE[low])
        elif re.fullmatch(r'\d+', part):
            out.append(part)
        elif re.fullmatch(r'(?i)[a-z]{1,4}\d+', part):
            out.append(part.upper())
        else:
            out.append(part[:1].upper() + part[1:])
    return ' '.join(out)


def localized(value, default=''):
    if not isinstance(value, str):
        return default or (str(value) if value is not None else '')
    loc = _locale or {}
    if value.startswith('@@') and value.endswith('@@') and len(value) > 4:
        key = value[2:-2]
        if key in loc and loc[key]:
            return loc[key]
        return default or ''
    return value


def pretty(unit, fallback_id):
    """Human readable name for a truck/trailer unit."""
    if unit:
        parts = [localized(v, '') for v in unit.list('info')]
        parts = [p for p in parts if p]
        if parts:
            return ' '.join(parts)
    return prettify_id(fallback_id)


# ------------------------------------------------------------------ indexing
def _iter_vehicle_folders(vfs, root):
    dirs, _files = vfs.list_dir(root)
    return [d for d in dirs if '.' in d]


def build_index(vfs, progress=None):
    """Return a list of vehicle descriptors (trucks + trailers) found in def/."""
    out = []
    load_locale(vfs)
    seen = set()
    roots = [(TRUCK_ROOT, 'truck')] + [(r, 'trailer') for r in TRAILER_ROOTS]
    for root, category in roots:
        for vid in _iter_vehicle_folders(vfs, root):
            key = f'{category}:{vid}'
            if key in seen:
                continue
            seen.add(key)
            data_path = f'{root}/{vid}/data.sii'
            unit = load_unit(vfs, data_path)
            if unit is None:
                continue
            out.append({
                'id': vid,
                'category': category,
                'root': root,
                'data_path': data_path,
                'name': pretty(unit, vid),
                'brand': localized(unit.list('info')[0], vid) if unit.list('info') else vid,
                'model': unit.get('model', ''),
                'info': [localized(v, '') for v in unit.list('info')],
            })
            if progress:
                progress(vid)
    out.sort(key=lambda d: (d['category'], d['name'].lower()))
    return out


# ------------------------------------------------------------------- details
_VEHICLE_UNIT_TYPES = {'accessory_truck_data', 'accessory_trailer_data'}


def _is_accessory_unit(unit):
    """Accept every accessory_* unit type.

    SCS keeps adding specialised classes (accessory_addon_tank_data,
    accessory_addon_trailer_cables_data, ...); a hard-coded whitelist silently
    drops whole slots.
    """
    return (unit is not None
            and unit.type.startswith('accessory')
            and unit.type not in _VEHICLE_UNIT_TYPES)


def resolve_model(unit):
    """Model path of a vehicle part.

    Modern SCS defs use ``model``; the pre-2012 trucks use ``detail_model``
    (often a whole-truck ``truck.pmd``) instead -- missing it left old vehicles
    as a bare shell.
    """
    if unit is None:
        return ''
    for key in ('detail_model', 'exterior_model', 'interior_model', 'model'):
        v = unit.get(key)
        if isinstance(v, str) and v:
            return v
    return ''


def _option_from_unit(path, unit):
    return {
        'path': path,
        'type': unit.type,
        'unit': unit.name,
        'name': localized(unit.get('name', unit.name), unit.name),
        'price': unit.get('price', 0),
        'unlock': unit.get('unlock', 0),
        'icon': unit.get('icon', ''),
        'model': resolve_model(unit),
        'suitable_for': unit.list('suitable_for'),
        'part_type': unit.get('part_type', ''),
    }


def _slot_from_def_path(rel):
    """'/def/vehicle/truck/x/accessory/mirror/stock.sii' -> 'mirror'."""
    rel = rel.lstrip('/')
    m = re.match(r'def/vehicle/[^/]+/[^/]+/accessory/([^/]+)/', rel)
    if m:
        return m.group(1)
    m = re.match(r'def/vehicle/[^/]+/[^/]+/([^/]+)/', rel)
    if m:
        return m.group(1)
    return None


def load_vehicle(vfs, category, vid, root=None, with_options=True, option_filter=None):
    root = root or (TRUCK_ROOT if category == 'truck' else TRAILER_ROOTS[0])
    base = f'{root}/{vid}'
    if not vfs.exists(base + '/data.sii') and root == TRAILER_ROOTS[0]:
        base = f'{TRAILER_ROOTS[1]}/{vid}'
    data_unit = load_unit(vfs, base + '/data.sii')
    detail = {
        'id': vid,
        'category': category,
        'root': base,
        'name': pretty(data_unit, vid),
        'info': [localized(v, '') for v in data_unit.list('info')] if data_unit else [],
        'required_slots': data_unit.list('require') if data_unit else [],
        'slots': [],
        'cabins': [],
        'chassis': [],
        'other': {},
        'defaults': {},
        'factory': {},          # explicit factory build from defaults[]/fallback[]
        'factory_filled': {},   # heuristic stock parts for require[]d slots
        'factory_missing': [],  # slots require[]d by the truck with no factory entry
    }
    acc_root_for_defaults = base + '/accessory'

    def remember_factory(key, path):
        if path and vfs.exists(path) and key not in detail['factory']:
            detail['factory'][key] = path

    if data_unit:
        for fb in data_unit.list('fallback'):
            if not isinstance(fb, str) or '|' not in fb:
                continue
            slot, fn = fb.split('|', 1)
            slot, fn = slot.strip(), fn.strip()
            for cand in (f'{base}/{slot}/{fn}', f'{acc_root_for_defaults}/{slot}/{fn}',
                         f'{GLOBAL_VEHICLE_ROOT}/{slot}/{fn}',
                         f'{GLOBAL_VEHICLE_ROOT}/trailer_wheel/{slot}/{fn}',
                         f'{acc_root_for_defaults}/{fn}'):
                if vfs.exists(cand):
                    key = slot if slot != 'accessory' else fn.split('/')[0]
                    detail['defaults'][key] = cand
                    remember_factory(key, cand)
                    break

        # defaults[] lists the factory accessory build (used by newer trucks)
        for dpath in data_unit.list('defaults'):
            if not isinstance(dpath, str) or not dpath.startswith('/'):
                continue
            rel = dpath.lstrip('/')
            m = re.match(r'def/vehicle/[^/]+/[^/]+/accessory/([^/]+)/', rel)
            if m:
                remember_factory(m.group(1), rel)
                continue
            m = re.match(r'def/vehicle/[^/]+/[^/]+/([^/]+)/', rel)
            if m:
                remember_factory(m.group(1), rel)

    dirs, _ = vfs.list_dir(base)
    # accessory slots
    acc_root = base + '/accessory'
    slot_dirs, _ = vfs.list_dir(acc_root)
    required = set(detail['required_slots'])
    for slot in slot_dirs:
        opts = []
        if with_options:
            _d, files = vfs.list_dir(f'{acc_root}/{slot}')
            for f in files:
                if not f.endswith(('.sii', '.sui')):
                    continue
                p = f'{acc_root}/{slot}/{f}'
                unit = load_unit(vfs, p)
                if not _is_accessory_unit(unit):
                    continue
                if option_filter and not option_filter(p, unit):
                    continue
                opts.append(_option_from_unit(p, unit))
        detail['slots'].append({
            'slot': slot,
            'required': slot in required,
            'options': opts,
        })

    # wheels live in shared global definition folders, not per truck
    wheel_entries = []
    for slot, axis in WHEEL_SLOTS.items():
        opts = []
        for root in WHEEL_ROOTS:
            _d, files = vfs.list_dir(f'{root}/{slot}')
            for f in sorted(files):
                if not f.endswith('.sii'):
                    continue
                p = f'{root}/{slot}/{f}'
                unit = load_unit(vfs, p)
                if unit is None:
                    continue
                o = _option_from_unit(p, unit)
                if not o['model']:
                    continue
                o['from_truck'] = '卡车通用' if root == GLOBAL_VEHICLE_ROOT else '挂车通用'
                opts.append(o)
        if not opts:
            continue
        wheel_entries.append({'slot': slot, 'required': False, 'options': opts,
                              'wheel': True, 'wheel_axis': axis,
                              'label': WHEEL_LABELS.get(slot, slot)})
    detail['slots'] = wheel_entries + detail['slots']

    # Parts that carry a model but are not accessory slots (the cockpit interior
    # being the important one) are still part of the factory build.
    _PRIMARY_KEYS = {'cabin', 'chassis', 'body', 'engine', 'transmission',
                     'paint_job', 'head_light', 'badge', 'f_tire', 'r_tire'}
    known = {s['slot'] for s in detail['slots']}
    for key, path in sorted(detail['factory'].items()):
        if key in _PRIMARY_KEYS or key in known:
            continue
        unit = load_unit(vfs, path)
        if unit is None or not resolve_model(unit):
            continue
        slot_dir = path.rsplit('/', 1)[0]
        opts = []
        _d, files = vfs.list_dir(slot_dir)
        for f in sorted(files):
            if not f.endswith('.sii'):
                continue
            p2 = f'{slot_dir}/{f}'
            u2 = load_unit(vfs, p2)
            if u2 is None or u2.type != unit.type:
                continue
            o = _option_from_unit(p2, u2)
            if o['model']:
                opts.append(o)
        if not opts:
            opts = [_option_from_unit(path, unit)]
        detail['slots'].append({'slot': key, 'required': False, 'options': opts,
                                'extra': True,
                                'label': EXTRA_LABELS.get(key, key)})
        known.add(key)

    # For slots the truck requires but that have no explicit factory entry, the
    # game fits the stock part -- approximate it with the cheapest "factory" one.
    for s in detail['slots']:
        slot = s['slot']
        if slot in detail['factory'] or not s['options']:
            continue
        if slot not in required:
            continue
        stock = ([o for o in s['options'] if o.get('part_type') == 'factory' and not o.get('unlock')]
                 or [o for o in s['options'] if o.get('part_type') == 'factory']
                 or [o for o in s['options'] if not o.get('unlock')]
                 or s['options'])
        best = min(stock, key=lambda o: (o.get('price') or 0))
        detail['factory_filled'][slot] = best['path']
    for s in detail['slots']:
        if s['required'] and s['slot'] not in detail['factory'] \
                and s['slot'] not in detail['factory_filled'] and not s['options']:
            detail['factory_missing'].append(s['slot'])

    for sub, key in (('cabin', 'cabins'), ('chassis', 'chassis'),
                     ('body', 'bodies'), ('interior', 'interiors')):
        items = []
        _d, files = vfs.list_dir(f'{base}/{sub}')
        for f in files:
            if not f.endswith('.sii'):
                continue
            p = f'{base}/{sub}/{f}'
            unit = load_unit(vfs, p)
            if unit is None:
                continue
            if not resolve_model(unit):
                continue
            items.append(_option_from_unit(p, unit))
        detail[key] = items

    # Cabin and chassis carry their own defaults[] -- that is where the stock
    # build (fuel tank, rear fenders, chassis cover, trailer cables, paint job,
    # interior, roof lights...) actually comes from.
    detail['part_defaults'] = {}
    for key in ('cabins', 'chassis', 'bodies', 'interiors'):
        for o in detail[key]:
            unit = load_unit(vfs, o['path'])
            if unit is None:
                continue
            m = {}
            for dpath in unit.list('defaults'):
                if not isinstance(dpath, str) or not dpath.startswith('/'):
                    continue
                rel = dpath.lstrip('/')
                slot = _slot_from_def_path(rel)
                if slot and vfs.exists(rel):
                    m.setdefault(slot, rel)
            if m:
                detail['part_defaults'][o['path']] = m

    # paint jobs are their own unit type (no model), so they need a separate pass
    paint_jobs = []
    _d, files = vfs.list_dir(f'{base}/paint_job')
    for f in sorted(files):
        if not f.endswith('.sii'):
            continue
        p = f'{base}/paint_job/{f}'
        unit = load_unit(vfs, p)
        if unit is None or unit.type != 'accessory_paint_job_data':
            continue
        variants = unit.list('color_variant')
        paint_jobs.append({
            'path': p,
            'name': localized(unit.get('name', unit.name), unit.name),
            'price': unit.get('price', 0),
            'unlock': unit.get('unlock', 0),
            'icon': unit.get('icon', ''),
            'base_color': unit.get('base_color'),
            'secondary_color': unit.get('secondary_color'),
            'variants': [list(v) for v in variants[:16] if isinstance(v, tuple)],
            'mask': unit.get('paint_job_mask') or '',
            'base_color_locked': bool(unit.get('base_color_locked', True)),
            'suitable_for': unit.list('suitable_for'),
            'part_type': unit.get('part_type', ''),
        })
    detail['paint_jobs'] = paint_jobs

    if category == 'truck':
        detail['primaries'] = [
            {'key': 'cabin', 'label': '驾驶室', 'options': detail['cabins']},
            {'key': 'chassis', 'label': '底盘', 'options': detail['chassis']},
        ]
    else:
        detail['primaries'] = [
            {'key': 'body', 'label': '车身', 'options': detail['bodies']},
            {'key': 'chassis', 'label': '底盘', 'options': detail['chassis']},
        ]

    for sub in ('engine', 'transmission', 'interior', 'paint_job', 'head_light',
                'badge', 'f_tire', 'r_tire', 'f_disc', 'r_disc', 'f_hub', 'r_hub',
                'f_nuts', 'r_nuts', 'f_rim', 'r_rim'):
        _d, files = vfs.list_dir(f'{base}/{sub}')
        if not files:
            continue
        items = []
        for f in files:
            if not f.endswith('.sii'):
                continue
            p = f'{base}/{sub}/{f}'
            unit = load_unit(vfs, p)
            if unit is None or not resolve_model(unit):
                continue
            items.append(_option_from_unit(p, unit))
        if items:
            detail['other'][sub] = items
    return detail


# ------------------------------------------------- all accessories from mods/GD
def all_accessory_options(vfs, cache=None):
    """Every accessory definition in every truck (used for cross-truck mixing)."""
    if cache is not None and 'all' in cache:
        return cache['all']
    out = {}
    for slot, axis in WHEEL_SLOTS.items():
        for root in WHEEL_ROOTS:
            _d, files = vfs.list_dir(f'{root}/{slot}')
            for f in sorted(files):
                if not f.endswith('.sii'):
                    continue
                p = f'{root}/{slot}/{f}'
                unit = load_unit(vfs, p)
                if unit is None:
                    continue
                opt = _option_from_unit(p, unit)
                if not opt['model']:
                    continue
                opt['from_truck'] = '卡车通用' if root == GLOBAL_VEHICLE_ROOT else '挂车通用'
                opt['from_category'] = 'shared'
                out.setdefault(slot, []).append(opt)
    for root, _cat in [(TRUCK_ROOT, 'truck')] + [(r, 'trailer') for r in TRAILER_ROOTS]:
        for vid in _iter_vehicle_folders(vfs, root):
            acc_root = f'{root}/{vid}/accessory'
            slot_dirs, _ = vfs.list_dir(acc_root)
            for slot in slot_dirs:
                _d, files = vfs.list_dir(f'{acc_root}/{slot}')
                for f in files:
                    if not f.endswith(('.sii', '.sui')):
                        continue
                    p = f'{acc_root}/{slot}/{f}'
                    unit = load_unit(vfs, p)
                    if not _is_accessory_unit(unit):
                        continue
                    opt = _option_from_unit(p, unit)
                    opt['from_truck'] = vid
                    opt['from_category'] = _cat
                    out.setdefault(slot, []).append(opt)
    if cache is not None:
        cache['all'] = out
    return out