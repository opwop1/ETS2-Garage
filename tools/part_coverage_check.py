"""For every primary vehicle model, flag parts that no PMD variant ever shows.

Such a part would be dropped by the variant filter although it carries geometry,
which is how a filtered view ends up "missing something".
"""
import sys

sys.path.insert(0, 'ets2garage')

from scs import ScsVfs, open_archives  # noqa: E402
from pmg import Pmg  # noqa: E402
from pmd import Pmd  # noqa: E402

BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
vfs = ScsVfs(open_archives(BASE)).index()

seen = set()
models = []
for pattern in ('vehicle/truck/%s/truck.pmg',):
    pass

# collect every primary model used by the vehicle defs
import catalog  # noqa: E402

catalog.load_locale(vfs)
index = catalog.build_index(vfs)
for v in index:
    root = ('def/vehicle/truck/' if v['category'] == 'truck'
            else 'def/vehicle/trailer_owned/')
    for sub in ('cabin', 'chassis', 'body'):
        _d, files = vfs.list_dir(f"{root}{v['id']}/{sub}")
        for f in files:
            if not f.endswith('.sii'):
                continue
            u = catalog.load_unit(vfs, f"{root}{v['id']}/{sub}/{f}")
            m = catalog.resolve_model(u)
            if m and m.lower().endswith('.pmd'):
                models.append(m[:-4] + '.pmg')
models = sorted(set(models))

print(f'checking {len(models)} primary models')
suspicious = []
for pmg in models:
    raw = vfs.read(pmg)
    if not raw:
        continue
    try:
        g = Pmg(raw)
    except Exception as exc:
        print('  parse fail', pmg, exc)
        continue
    pmd_path = pmg[:-4] + '.pmd'
    rawp = vfs.read(pmd_path)
    if not rawp:
        continue
    try:
        m = Pmd(rawp)
    except Exception:
        continue
    if not m.variants:
        continue
    tri = {}
    for pi, p in enumerate(g.parts):
        tot = 0
        for k in range(p['piece_count']):
            idx = p['piece_idx'] + k
            if 0 <= idx < len(g.pieces):
                tot += g.pieces[idx].edges // 3
        tri[pi] = tot
    ever = set()
    for var in m.variants:
        for i, a in enumerate(var['parts']):
            if a.get('visible'):
                ever.add(i)
    for pi, p in enumerate(g.parts):
        if tri.get(pi, 0) > 0 and pi not in ever:
            suspicious.append((pmg, pi, p['name'], tri[pi]))

print(f'models with variants: {len(models)}')
print(f'parts with geometry that NO variant shows: {len(suspicious)}')
for s in suspicious[:40]:
    print(f'   {s[0]}  part[{s[1]}] {s[2]:16s} tris={s[3]}')