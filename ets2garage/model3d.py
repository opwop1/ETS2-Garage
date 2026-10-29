"""Combine .pmd + .pmg into renderable meshes and assemble a truck."""
import os
import struct

import numpy as np

# nothing on a vehicle is bigger than this; guards against parametric models
MAX_COORD = 60.0

from mat import load_material  # noqa: E402
from pmd import Pmd
from pmg import Pmg


class ModelMesh:
    __slots__ = ('path', 'name', 'pmd', 'pmg', 'pieces', 'locators', 'parts',
                 'materials', 'blob', 'manifest')

    def __init__(self, path, pmd, pmg):
        self.path = path
        self.name = os.path.basename(path).rsplit('.', 1)[0]
        self.pmd = pmd
        self.pmg = pmg
        self.pieces = []
        self.parts = pmg.parts
        self.locators = pmg.locators
        self.materials = pmd.material_list() if pmd else []
        self.blob = b''
        self.manifest = None
        self._build()

    def _build(self):
        chunks = []
        offset = 0
        manifest = {'name': self.name, 'path': self.path, 'pieces': [],
                    'materials': self.materials,
                    'parts': [p['name'] for p in self.pmg.parts]}

        def add(entry, key, data):
            """Append a section, keeping every subsequent offset 4-byte aligned."""
            nonlocal offset
            entry[key] = [offset, len(data)]
            chunks.append(data)
            offset += len(data)
            pad = (-offset) % 4
            if pad:
                chunks.append(b'\x00' * pad)
                offset += pad

        for p in self.pmg.pieces:
            entry = {'material': p.material, 'count': p.verts,
                     'triangles': (p.edges // 3),
                     'part': self.pmg.piece_part[p.index] if p.index < len(self.pmg.piece_part) else 0}
            if not p.positions:
                manifest['pieces'].append(entry)
                continue
            pos = np.asarray(p.positions, dtype='<f4')
            # A few SCS models are parametric and carry design-space vertices far
            # outside the vehicle (e.g. wielton's tube cargo spans 760 m). Such a
            # piece would blow up the whole viewport, so drop it.
            if not np.isfinite(pos).all() or float(np.abs(pos).max()) > MAX_COORD:
                print(f'[model3d] {self.name}: piece {p.index} out of range '
                      f'(max |v| = {float(np.abs(np.nan_to_num(pos)).max()):.0f} m), skipped')
                entry['skip'] = True
                manifest['pieces'].append(entry)
                continue
            add(entry, 'position', pos.tobytes())
            if p.normals:
                add(entry, 'normal', np.asarray(p.normals, dtype='<f4').tobytes())
            if p.uvs:
                arr = np.asarray(p.uvs, dtype='<f4')
                width = max(1, p.uv_width)
                for c in range(min(width, 3)):
                    add(entry, f'uv{c}',
                        np.ascontiguousarray(arr[:, 2 * c:2 * c + 2]).tobytes())
            col_off = p.offsets.get('color', -1)
            if col_off != -1 and p.stride:
                # PMG vertex attributes are interleaved: every attribute lives at
                # its own sub-offset inside a `stride`-byte vertex record. Reading
                # them as one contiguous block yields noise, not colours.
                stride = p.stride
                block = np.frombuffer(self.pmg.data, dtype=np.uint8,
                                      count=p.verts * stride, offset=col_off)
                cols = np.ascontiguousarray(block.reshape(p.verts, stride)[:, :4])
                add(entry, 'color', cols.tobytes())
            if p.indices:
                add(entry, 'index', np.asarray(p.indices, dtype='<u2').tobytes())
            manifest['pieces'].append(entry)
        self.blob = b''.join(chunks)
        self.manifest = manifest

    def locator_map(self):
        out = {}
        for l in self.locators:
            out.setdefault(l.name, []).append(l)
        return out

    def visible_parts(self, variant_names):
        """Part indices shown for the given PMD variant names, or None.

        A vehicle model contains every configuration side by side; the PMD's
        variant table marks which parts belong to the selected cabin/chassis
        (e.g. `chs_4x2` -> parts `chs_4x2` + `chs_base` only).  Returning None
        means "no matching variant", i.e. draw everything.
        """
        if self.pmd is None or not variant_names:
            return None
        names = {n.strip().lower() for n in variant_names if n}
        if not names:
            return None
        selected = [v for v in self.pmd.variants
                    if (v['name'] or '').strip().lower() in names]
        if not selected:
            return None

        # A part is a *configuration alternative* only when some variant shows
        # it. Parts no variant ever shows (support braces, trailer cables, the
        # `defaultpart` hull) are not alternatives and must stay, otherwise the
        # filtered view loses geometry it should keep.
        claimed = set()
        for v in self.pmd.variants:
            for i, a in enumerate(v['parts']):
                if a.get('visible'):
                    claimed.add(i)

        keep = set()
        for v in selected:
            for i, a in enumerate(v['parts']):
                if a.get('visible'):
                    keep.add(i)
        keep |= {i for i in range(len(self.pmg.parts)) if i not in claimed}
        return keep

    def locators_for(self, variant_names):
        if self.pmd is None:
            return self.locators
        vis = self.visible_parts(variant_names)
        if vis is None:
            return self.locators
        return [l for l in self.locators
                if l.index < len(self.pmg.locator_part)
                and self.pmg.locator_part[l.index] in vis]

    def bounds(self):
        lo = np.array([1e9, 1e9, 1e9])
        hi = np.array([-1e9, -1e9, -1e9])
        for p in self.pmg.pieces:
            if not p.positions:
                continue
            a = np.asarray(p.positions)
            lo = np.minimum(lo, a.min(axis=0))
            hi = np.maximum(hi, a.max(axis=0))
        return lo.tolist(), hi.tolist()


def load_model(vfs, pmd_path, cache=None):
    key = pmd_path.lstrip('/')
    if cache is not None and key in cache:
        return cache[key]
    mesh = None
    try:
        pdata = vfs.read(key)
        gdata = vfs.read(key[:-4] + '.pmg')
        if pdata and gdata:
            mesh = ModelMesh(key, Pmd(pdata), Pmg(gdata))
    except Exception as exc:                       # noqa: BLE001 - preview tool
        print(f'[model3d] failed to load {key}: {type(exc).__name__}: {exc}')
    if cache is not None:
        cache[key] = mesh
    return mesh


# ------------------------------------------------------------------ assembly
def match_locators(mesh, slot, variants=None):
    """Attachment points of *mesh* that host an accessory of *slot*.

    SCS does not always name the locator exactly after the slot, so several
    naming styles have to be tolerated, in this order:

    ===========  ==========================  ====================
    rank         rule                        example
    ===========  ==========================  ====================
    0            exact                       ``mirror``
    1            exact alias                 ``swheel`` for ``steering_w``
    2            ``slot_*``                  ``beacon_sl``
    3            ``alias_*``                 ``f_mirror_1``
    4            slot + trailing digits      ``interior2``
    5            slot + plural ``s``         ``doorsteps``
    6            any prefix                  ``interior_uk``
    ===========  ==========================  ====================
    """
    locs = mesh.locators_for(variants)
    strong = [slot] + LOCATOR_ALIASES.get(slot, [])
    weak = LOCATOR_WEAK_ALIASES.get(slot, [])

    def group(pred):
        return [l for l in locs if pred(l.name)]

    ranks = ([lambda n, p=p: n == p for p in strong]
             + [lambda n, p=p: n.startswith(p + '_') for p in strong]
             + [lambda n, p=p: n.startswith(p) and n[len(p):].isdigit() for p in strong]
             + [lambda n, p=p: n == p + 's' for p in strong]
             + [lambda n, p=p: n.startswith(p) for p in strong]
             + [lambda n, p=p: n == p for p in weak]
             + [lambda n, p=p: n.startswith(p) for p in weak])
    for pred in ranks:
        found = group(pred)
        if found:
            return found
    return []


# slot -> alternative locator names used by some models
LOCATOR_ALIASES = {
    'steering_w': ['swheel'],
    'doorstep': ['doorsteps'],
    'curtain_f': ['curtain'],
    'drv_plate': ['plate_f', 'front_plate'],
    'codrv_plate': ['plate_f2', 'front_plate2'],
}
# only tried when nothing above matched: these name *other* things in most
# models (`ext_interior` is an exterior-view point, not the cockpit)
LOCATOR_WEAK_ALIASES = {
    'interior': ['ext_interior', 'int_interior', 'cockpit'],
}

WHEEL_GROUP_SLOTS = {
    'wheel_f': ('f_tire', 'f_disc', 'f_hub', 'f_nuts', 'f_rim'),
    'wheel_r': ('r_tire', 'r_disc', 'r_hub', 'r_nuts', 'r_rim'),
}


def resolve_wheel_axis(mesh, axis, variants, configured):
    """Locators a wheel group should use.

    Some models name *every* wheel ``wheel_f_*`` (low-loader trailers have six
    of them and no ``wheel_r_*`` at all). When only one axis exists it is handed
    to whichever group actually has parts fitted, so the wheels are not lost --
    and never to both, which would stack two complete sets.
    """
    locs = wheel_locators(mesh, axis, variants)
    if locs:
        return axis, locs
    other = 'wheel_r' if axis == 'wheel_f' else 'wheel_f'
    locs = wheel_locators(mesh, other, variants)
    if not locs:
        return None, []
    other_configured = any(s in configured for s in
                           WHEEL_GROUP_SLOTS.get(other, ()))
    mine_configured = any(s in configured for s in
                          WHEEL_GROUP_SLOTS.get(axis, ()))
    if other_configured and mine_configured:
        return None, []                     # the other group owns this axis
    return other, locs


def wheel_locators(mesh, axis, variants=None):
    """All wheel attachment points of an axis ('wheel_f' / 'wheel_r')."""
    out = []
    for l in mesh.locators_for(variants):
        if l.name == axis or l.name.startswith(axis + '_'):
            out.append(l)
    return out


def _locator_pose(loc):
    return (loc.position, loc.rotation, loc.scale or 1.0)


def quat_matrix(q):
    w, x, y, z = q
    n = (w * w + x * x + y * y + z * z) ** 0.5
    if n == 0:
        return np.eye(3)
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def locator_transform(loc):
    return {
        'position': [float(v) for v in loc.position],
        'rotation': [float(v) for v in loc.rotation],
        'scale': float(loc.scale or 1.0),
    }


def compose(vfs, config, cache=None):
    """Build the instance list for a truck configuration.

    config = {
        'truck': 'scania.s_2016',
        'cabin': 'def/vehicle/truck/scania.s_2016/cabin/normal.sii',   # optional
        'chassis': '...',
        'accessories': {'beacon': 'def/.../accessory/beacon/shape1.sii', ...},
    }
    """
    from catalog import load_unit, localized, WHEEL_SLOTS, resolve_model  # noqa: E402
    instances = []
    warnings = []
    host_meshes = []          # (mesh, variant_names) of cabin/chassis/body

    def label(unit):
        return localized(unit.get('name', unit.name), unit.name)

    def variants_of(unit):
        """PMD variant name this definition selects (e.g. 'chs_4x2').

        Only the primary variant is used -- `variant_uk` describes the
        right-hand-drive twin of the same part and picking both would draw two
        overlapping cabs.
        """
        v = unit.get('variant')
        if isinstance(v, str) and v:
            return [v]
        v = unit.get('variant_uk')
        if isinstance(v, str) and v:
            return [v]
        return []

    # primary parts: cabin+chassis for trucks, body+chassis for trailers
    primary = dict(config.get('parts') or {})
    for key in ('cabin', 'chassis', 'body'):
        if config.get(key):
            primary.setdefault(key, config[key])

    # Load the primary parts first; a pre-2012 truck can point both the cabin and
    # the chassis at the very same whole-truck model, and only the PMD variant
    # tables say which part belongs to which of the two.
    prim = []
    for key, defp in primary.items():
        if not defp:
            continue
        unit = load_unit(vfs, defp)
        if not unit:
            warnings.append(f'{key}: definition not found ({defp})')
            continue
        model = resolve_model(unit)
        if not model:
            continue
        mesh = load_model(vfs, model, cache)
        if mesh is None:
            warnings.append(f'{key}: model failed to load ({model})')
            continue
        prim.append({'key': key, 'def': defp, 'unit': unit, 'mesh': mesh,
                     'variants': variants_of(unit)})

    for entry in prim:
        key, mesh = entry['key'], entry['mesh']
        # Another primary using the very same mesh already covers this one's
        # parts -> skip it, otherwise the geometry would be drawn twice.
        hidden = False
        for other in prim:
            if other is entry or other['mesh'] is not mesh:
                continue
            if other['key'] not in ('cabin', 'body'):
                continue
            mine = mesh.visible_parts(entry['variants'])
            theirs = mesh.visible_parts(other['variants'])
            if theirs is None or (mine is not None and theirs >= mine):
                hidden = True
                break
        host_meshes.append((mesh, entry['variants']))
        instances.append({'kind': key, 'slot': key, 'model': mesh.name,
                          'path': mesh.path, 'def': entry['def'],
                          'hidden': hidden,
                          'variants': entry['variants'],
                          'transform': {'position': [0, 0, 0], 'rotation': [1, 0, 0, 0],
                                        'scale': 1.0},
                          'locator': None, 'source': label(entry['unit'])})

    # wheels attach to the chassis' wheel locators -- one copy per wheel
    configured = set(config.get('accessories') or {})
    for slot, defp in (config.get('accessories') or {}).items():
        if not defp:
            continue
        unit = load_unit(vfs, defp)
        if not unit:
            warnings.append(f'{slot}: definition not found')
            continue
        model = resolve_model(unit)
        if not model:
            warnings.append(f'{slot}: no model in definition')
            continue
        mesh = load_model(vfs, model, cache)
        if mesh is None:
            warnings.append(f'{slot}: model failed to load ({model})')
            continue
        host = None
        loc = None
        placements = None
        axis = WHEEL_SLOTS.get(slot)
        if axis:
            for hm, hvars in host_meshes:
                _ax, locs = resolve_wheel_axis(hm, axis, hvars, configured)
                if locs:
                    host = hm
                    placements = [dict(locator_transform(l), name=l.name) for l in locs]
                    loc = locs[0]
                    break
        if loc is None and not placements:
            for hm, hvars in host_meshes:
                found = match_locators(hm, slot, hvars)
                if found:
                    host, loc = hm, found[0]
                    break
        if loc is None and not placements:
            # No attachment point: the model does not support this part. Drawing
            # it at the origin is what dropped the cockpit under the chassis.
            warnings.append(f'{slot}: no "{slot}" locator on the vehicle, '
                            f'part not fitted')
            continue
        if placements:
            tr = dict(locator_transform(loc))
        else:
            tr = locator_transform(loc)
        instances.append({'kind': 'accessory', 'slot': slot,
                          'model': mesh.name, 'path': mesh.path, 'def': defp,
                          'transform': tr, 'locator': loc.name if loc else None,
                          'host': host.name if host else None,
                          'placements': placements,
                          'variants': variants_of(unit),
                          'source': label(unit)})
    return instances, warnings