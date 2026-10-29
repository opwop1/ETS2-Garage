"""Audit: does every factory accessory of every vehicle find a locator?

An accessory that fails to match a locator is drawn at the origin -- the
"part dangling under the chassis" class of bug.
"""
import sys
from collections import Counter

sys.path.insert(0, 'ets2garage')

import catalog  # noqa: E402
import model3d  # noqa: E402
from scs import ScsVfs, open_archives  # noqa: E402

BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
NON_MODEL = {'engine', 'transmission', 'head_light', 'paint_job'}
PRIMARIES = ('cabin', 'chassis', 'body')

vfs = ScsVfs(open_archives(BASE)).index()
catalog.load_locale(vfs)
index = catalog.build_index(vfs)
cache = {}


def factory_config(vid, category):
    detail = catalog.load_vehicle(vfs, category, vid)
    parts = {}
    for pr in detail['primaries']:
        if pr['options']:
            parts[pr['key']] = pr['options'][0]['path']
    merged = {}
    merged.update(detail['factory_filled'])
    merged.update(detail['factory'])
    for v in detail['part_defaults'].values():
        merged.update(v)
    acc = {k: v for k, v in merged.items()
           if k not in PRIMARIES and k not in NON_MODEL}
    return detail, parts, acc


def fill_from_locators(detail, parts, acc, seen_locators):
    """Mirror the UI's 'fill slots that have a factory part and a locator'."""
    byslot = {s['slot']: s for s in detail['slots']}
    for slot, s in byslot.items():
        if slot in acc or slot in parts:
            continue
        has = any(n == slot or n.startswith(slot + '_') for n in seen_locators)
        if not has:
            continue
        cands = [o for o in s['options'] if o.get('model') and o.get('part_type') == 'factory']
        if not cands:
            continue
        cands.sort(key=lambda o: ((o.get('unlock') or 0), (o.get('price') or 0)))
        acc[slot] = cands[0]['path']


missing = Counter()
examples = {}
rows = 0
for v in index:
    try:
        detail, parts, acc = factory_config(v['id'], v['category'])
        inst, _warn = model3d.compose(vfs, {'parts': parts, 'accessories': acc}, cache)
        locs = set()
        for i in inst:
            if i['kind'] in PRIMARIES:
                m = model3d.load_model(vfs, i['path'], cache)
                if m:
                    locs |= {l.name for l in m.locators_for(i.get('variants'))}
        fill_from_locators(detail, parts, acc, locs)
        inst, _warn = model3d.compose(vfs, {'parts': parts, 'accessories': acc}, cache)
    except Exception as exc:                       # noqa: BLE001
        print(f'  !! {v["id"]}: {exc}')
        continue
    for i in inst:
        if i['kind'] in PRIMARIES or i.get('hidden'):
            continue
        rows += 1
        if i['locator'] is None:
            missing[i['slot']] += 1
            examples.setdefault(i['slot'], (v['id'], sorted(locs)[:14]))

print(f'accessory instances checked: {rows}')
print(f'slots that fail to find a locator: {len(missing)}')
for slot, n in missing.most_common(40):
    vid, sample = examples[slot]
    print(f'   {slot:14s} x{n:3d}  e.g. {vid}')
    print(f'        locators: {sample}')