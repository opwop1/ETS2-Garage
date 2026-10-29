import os, struct
from hashfs2 import ScsArchive
from cityhash64 import cityhash64
import cityhash as pyc

BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
a = ScsArchive(os.path.join(BASE, 'def.scs'))

# find the directory entry whose listing is the "def" directory
cands = []
for h, e in a.entries.items():
    if not e.is_dir:
        continue
    d, f = a.read_dir(h)
    if 'vehicle' in d and 'city.sii' in f:
        cands.append((h, d, f))
print('candidate "def" dir entries:', len(cands))
for h, d, f in cands[:5]:
    print(f'  hash={h:#018x} ndirs={len(d)} nfiles={len(f)}')
    print('   dirs:', d[:14])
    print('   files:', f[:14])

if cands:
    target = cands[0][0]
    print('\ntarget hash =', hex(target))
    print('cityhash64("def")            =', hex(cityhash64('def')))
    print('cityhash_1.1("def")          =', hex(pyc.CityHash64(b'def')))
    variants = []
    for base in ('def', '/def', 'def/', '/def/', 'DEF', 'Def', 'def\x00',
                 'def\x00/', 'def\r\n', 'def\n', '.def', 'def.sii', 'def.scs'):
        variants.append(base)
    for v in variants:
        h = cityhash64(v)
        if h in a.entries:
            print('  HIT', repr(v), hex(h))
    # does cityhash64 of anything with 'def' land there?
    for pre in ('', '/', './', 'def/', 'base'):
        s = pre + 'def'
        h = cityhash64(s)
        print(f'  {s!r:12s} {h:#018x} present={h in a.entries}')