"""Compare the wheel count / drawn part set before and after variant filtering."""
import json
import urllib.request

B = 'http://127.0.0.1:8770'


def get(path):
    return json.loads(urllib.request.urlopen(B + path).read())


def asm(cfg):
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        B + '/api/assemble', data=json.dumps(cfg).encode(),
        headers={'Content-Type': 'application/json'})).read())


for vid in ('daf.xf', 'scania.s_2016', 'man.tgx', 'volvo.fh16_2012'):
    d = get(f'/api/vehicle?category=truck&id={vid}')
    parts = {}
    for pr in d['primaries']:
        if pr['options']:
            parts[pr['key']] = pr['options'][0]['path']
    merged = {}
    merged.update(d['factory_filled'])
    merged.update(d['factory'])
    for v in d['part_defaults'].values():
        merged.update(v)
    acc = {k: v for k, v in merged.items() if k not in ('cabin', 'chassis', 'body')}
    r = asm({'parts': parts, 'accessories': acc})
    wheels = [i for i in r['instances']
              if i['slot'] in ('f_tire', 'f_disc', 'f_hub', 'f_nuts',
                               'r_tire', 'r_disc', 'r_hub', 'r_nuts')]
    print(f"== {vid}: parts={d['primaries'] and len(parts)} instances={len(r['instances'])}")
    total_copies = 0
    for i in wheels:
        n = len(i.get('placements') or [])
        total_copies += n
        print(f"     {i['slot']:8s} copies={n} locators={[p.get('name') for p in (i.get('placements') or [])]}")
    print(f"     total wheel meshes = {total_copies}")
    byslot = {i['slot']: i for i in r['instances']}
    for k in ('cabin', 'chassis'):
        if k in byslot:
            i = byslot[k]
            drawn = sum(1 for p in i['pieces'] if not p.get('skip'))
            print(f"     {k:8s} variants={i.get('variants')} visible={i.get('visible_parts')} "
                  f"drawn={drawn}/{len(i['pieces'])}")