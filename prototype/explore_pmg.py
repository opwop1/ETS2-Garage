import os, re, struct, collections
from hashfs2 import ScsArchive

BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
av = ScsArchive(os.path.join(BASE, 'base_vehicle.scs'))
print('base_vehicle roots:', av.read_dir(''))

targets = [
    'vehicle/truck/scania_2016/cabin/cab_s_low.pmg',
    'vehicle/truck/scania_2016/cabin/cab_s_low.pmd',
]
for path in targets:
    d = av.read(path)
    print('=' * 70)
    print(path, 'len', None if d is None else len(d))
    if d is None:
        for p in ('vehicle/truck/scania_2016/cabin', 'vehicle/truck/scania_2016'):
            print('  dir', p, av.read_dir(p))
        continue
    print(d[:64].hex(' '))
    print('head ascii:', d[:32])
    # printable strings
    runs = [(m.start(), m.group().decode('latin1'))
            for m in re.finditer(rb'[ -~]{4,}', d)]
    print('ascii runs:', len(runs))
    for off, s in runs[:60]:
        print(f'   0x{off:06x} {s}')
    open(os.path.basename(path), 'wb').write(d)