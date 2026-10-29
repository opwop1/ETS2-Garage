import os, sys, time, json
from hashfs2 import ScsArchive, ScsError

BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
out = []
names = sorted(f for f in os.listdir(BASE) if f.lower().endswith('.scs'))
for n in names:
    p = os.path.join(BASE, n)
    size = os.path.getsize(p)
    t0 = time.time()
    try:
        a = ScsArchive(p)
        files = a.list_files()
        resolved = len(a.dirs) + len(a.entries) - 0
        status = 'OK' if (len(a.dirs) + len(files)) == a.entry_count else 'PARTIAL'
        root_children = a.read_dir('')
        line = (f'{status:8s} {n:32s} {size/1e9:6.2f}GB entries={a.entry_count:7d} '
                f'dirs={len(a.dirs):6d} files={len(files):7d} '
                f'roots={root_children[0][:4] if root_children else None} {time.time()-t0:5.2f}s')
        a.close()
    except ScsError as exc:
        status, line = 'SKIP', f'SKIP     {n:32s} {size/1e9:6.2f}GB {exc}'
    except Exception as exc:
        status, line = 'ERR', f'ERR      {n:32s} {size/1e9:6.2f}GB {type(exc).__name__}: {exc}'
    print(line, flush=True)
    out.append((status, n, size))

ok = sum(1 for s, _, _ in out if s == 'OK')
print(f'\n{ok}/{len(out)} archives fully mapped')
json.dump([{'status': s, 'name': n, 'size': sz} for s, n, sz in out],
          open('archive_report.json', 'w'), indent=1)