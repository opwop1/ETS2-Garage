import os, struct
from hashfs2 import ScsArchive, ScsError
from cityhash64 import cityhash64

BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
a = ScsArchive(os.path.join(BASE, 'def.scs'))
print('entry_count', a.entry_count, 'parsed', len(a.entries))

ndir = sum(1 for e in a.entries.values() if e.is_dir)
ntobj = sum(1 for e in a.entries.values() if e.is_tobj)
print('is_dir entries', ndir, 'tobj', ntobj, 'plain', len(a.entries)-ndir-ntobj)

print('\n-- root "" raw listing --')
print(a.read_dir(''))
print('root entry:', a.entries.get(cityhash64('')))

for probe in ('def', 'def/city.sii', 'vehicle', 'def/vehicle', 'locale',
              'def/vehicle/truck', 'custom', 'custom/city.sii'):
    h = cityhash64(probe)
    e = a.entries.get(h)
    print(f'{probe!r:28s} present={e is not None} {e}')

# Show the first few entries in index order
print('\n-- first 12 entries by index --')
entries = sorted(a.entries.values(), key=lambda e: e.index_offset)
for e in entries[:12]:
    print(f'  hash={e.hash:#018x} dir={int(e.is_dir)} parts={len(e.parts)} '
          f'off=0x{e.offset:x} z={e.zsize} u={e.size} comp=0x{e.compression:x} kind0={e.parts[0][1]:#x}')
    try:
        d = a.read(e.hash)
        print('     raw:', d[:80])
    except Exception as exc:
        print('     ERR', exc)