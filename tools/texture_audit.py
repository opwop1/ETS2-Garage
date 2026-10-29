import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ets2garage'))
from scs import ScsArchive, ScsVfs           # noqa: E402
import texture as T                          # noqa: E402

BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
names = ['base.scs', 'base_vehicle.scs', 'base_share.scs', 'def.scs']
arch = [ScsArchive(os.path.join(BASE, n)) for n in names]
vfs = ScsVfs(arch).index()
tex = [f for f in vfs.all_files() if f.endswith('.tobj')]
print('total tobj', len(tex))
random.seed(7)
sample = random.sample(tex, 3000)
t0 = time.time()
ok = bad = 0
fails = {}
for f in sample:
    try:
        T.extract_texture(vfs, f)
        ok += 1
    except Exception as exc:                     # noqa: BLE001
        bad += 1
        key = f'{type(exc).__name__}: {exc}'
        info = vfs.texture_info(f)
        parts = [(p['key'], p['compression'], p['compressed_size'], p['size'])
                 for p in info.get('parts', [])]
        fails.setdefault(key, []).append((f, parts, info.get('width'), info.get('height'),
                                          info.get('format')))
print(f'sampled {len(sample)}: ok={ok} bad={bad} in {time.time()-t0:.1f}s')
for k, v in list(fails.items())[:8]:
    print('  FAIL', k, f'x{len(v)}')
    print('     ', v[0])