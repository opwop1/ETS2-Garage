import os
from hashfs2 import ScsArchive

BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
a = ScsArchive(os.path.join(BASE, 'def.scs'))


def tree(prefix, depth=2, indent=0):
    d, f = a.read_dir(prefix)
    pad = '  ' * indent
    for x in sorted(f):
        print(f'{pad}{x}')
    for x in sorted(d):
        print(f'{pad}[{x}]/')
        if depth > 1:
            tree(prefix + '/' + x, depth - 1, indent + 1)


for truck in ('def/vehicle/truck/scania.s_2016', 'def/vehicle/truck/volvo.fh16_2012',
              'def/vehicle/truck/man.tgx_euro6'):
    print('=' * 70)
    print(truck)
    tree(truck, depth=2)
    print()

print('=' * 70)
print('sample accessory defs')
for p in ('def/vehicle/truck/scania.s_2016/accessory/mirror/shape1.sii',
          'def/vehicle/truck/scania.s_2016/accessory/beacon/shape1.sii'):
    d = a.read(p)
    print('---', p, '->', 'MISSING' if d is None else '')
    if d:
        print(d.decode('utf-8', 'replace')[:1200])

print('=' * 70)
print('cabin def listing')
dd, ff = a.read_dir('def/vehicle/truck/scania.s_2016/cabin')
print(ff[:10])
if ff:
    p = 'def/vehicle/truck/scania.s_2016/cabin/' + ff[0]
    print('---', p)
    print(a.read(p).decode('utf-8', 'replace')[:1500])