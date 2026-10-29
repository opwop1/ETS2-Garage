import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ets2garage'))

from scs import ScsArchive, ScsVfs           # noqa: E402
import catalog                               # noqa: E402
import model3d                               # noqa: E402

BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'

t0 = time.time()
arch = []
for n in ('base.scs', 'base_vehicle.scs', 'def.scs'):
    arch.append(ScsArchive(os.path.join(BASE, n)))
vfs = ScsVfs(arch).index()
print(f'indexed {len(vfs.all_files())} files in {time.time()-t0:.1f}s')

t0 = time.time()
loc = catalog.load_locale(vfs)
print(f'locale entries: {len(loc)} in {time.time()-t0:.1f}s', list(loc.items())[:3])

t0 = time.time()
index = catalog.build_index(vfs)
print(f'vehicles: {len(index)} in {time.time()-t0:.1f}s')
for v in index[:12]:
    print(f"   {v['category']:8s} {v['id']:22s} {v['name']!r}")

truck = next(v for v in index if v['id'] == 'scania.s_2016')
t0 = time.time()
detail = catalog.load_vehicle(vfs, truck['category'], truck['id'])
print(f"\ndetail in {time.time()-t0:.2f}s: {detail['name']!r} "
      f"slots={len(detail['slots'])} cabins={len(detail['cabins'])} chassis={len(detail['chassis'])}")
for s in detail['slots'][:6]:
    print(f"   slot {s['slot']:16s} req={s['required']} options={len(s['options'])} "
          f"e.g. {s['options'][0]['name'] if s['options'] else '-'!r}")
print('   cabins:', [(c['name'], c['model']) for c in detail['cabins'][:3]])

cab = detail['cabins'][0]['path']
cha = detail['chassis'][0]['path']
beacon = next(s for s in detail['slots'] if s['slot'] == 'beacon')['options'][0]['path']
mirror = next(s for s in detail['slots'] if s['slot'] == 'mirror')['options'][0]['path']
config = {'cabin': cab, 'chassis': cha,
          'accessories': {'beacon': beacon, 'mirror': mirror}}
t0 = time.time()
instances, warns = model3d.compose(vfs, config)
print(f'\ncompose in {time.time()-t0:.2f}s -> {len(instances)} instances')
for i in instances:
    print(f"   {i['kind']:9s} {i.get('slot',''):10s} locator={str(i['locator']):16s} "
          f"pos={[round(x,3) for x in i['transform']['position']]} model={i['model']}")
print('   warnings:', warns)

cache = {}
for i in instances:
    m = model3d.load_model(vfs, i['path'], cache)
    if m:
        print(f"   {m.name:24s} pieces={len(m.pieces)} verts={m.pmg.total_vertices():6d} "
              f"tris={m.pmg.total_triangles():6d} mats={len(m.materials)} blob={len(m.blob)/1e6:.2f}MB "
              f"locators={len(m.locators)}")
print('   sample materials:', (cache.get(instances[0]['path']) or model3d.ModelMesh).materials[:3]
      if instances else None)