import os, struct, re
from hashfs2 import ScsArchive
from cityhash64 import cityhash64

BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
a = ScsArchive(os.path.join(BASE, 'def.scs'))
d = open('cab_s_low.pmg', 'rb').read()

# collect every accessory slot directory name used by any truck
slots = set()
d0, f0 = a.read_dir('def/vehicle/truck')
for truck in d0:
    acc = 'def/vehicle/truck/' + truck + '/accessory'
    r = a.read_dir(acc)
    if r:
        slots.update(r[0])
# also the top-level dirs under the truck folder (cabin/chassis/...)
extras = {'cabin', 'chassis', 'interior', 'engine', 'transmission', 'badge',
          'paint_job', 'head_light', 'f_tire', 'r_tire', 'f_disc', 'f_hub',
          'mirror', 'beacon', 'sunshld', 'doorhndl', 'steering_w', 'toybed',
          'toyseat', 'toyhang', 'toybig', 'toystand', 'exhaust_l', 'exhaust_r',
          'l_horn', 'r_horn', 'l_pillow', 's_panel', 'sideskirt', 'tank'}
slots |= extras
print('candidate slot names:', len(slots))

hits = []
for nm in sorted(slots):
    for cand in (nm, nm + '_l', nm + '_r', nm.upper()):
        h = cityhash64(cand)
        for pat, tag in ((struct.pack('<Q', h), 'LE'), (struct.pack('>Q', h), 'BE')):
            i = d.find(pat)
            if i >= 0:
                hits.append((cand, tag, i, h))
print('hash hits in cab_s_low.pmg:', len(hits))
for h in hits[:40]:
    print(f'  {h[0]:16s} {h[1]} @0x{h[2]:06x}')
if not hits:
    print('  (none) - locator names are not CityHash of the slot names')