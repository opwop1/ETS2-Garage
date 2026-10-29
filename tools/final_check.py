"""Final verification: stock build, paint colour, livery, custom colour, locked shell."""
import base64
import io
import json

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

SHOT = r'F:\code\car-share\docs'
errors = []


def stats(data_url):
    raw = base64.b64decode(data_url.split(',', 1)[1])
    a = np.asarray(Image.open(io.BytesIO(raw)).convert('RGBA')).astype(np.float32)
    m = a[:, :, 3] > 40
    if m.sum() < 500:
        return {'area': int(m.sum())}
    px = a[m][:, :3]
    return {'area': int(m.sum()), 'mean': [round(float(v), 1) for v in px.mean(axis=0)],
            'std': round(float(px.std()), 2),
            'colors': len(np.unique((px // 16).astype(np.int32).reshape(-1, 3), axis=0))}


def save(data_url, name):
    Image.open(io.BytesIO(base64.b64decode(data_url.split(',', 1)[1]))).convert('RGB').save(name)


with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader',
                                '--enable-unsafe-swiftshader'])
    page = b.new_page(viewport={'width': 1680, 'height': 1000})
    page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
    page.on('console', lambda m: errors.append(f'{m.type}: {m.text}') if m.type == 'error' else None)
    page.goto('http://127.0.0.1:8770/', wait_until='networkidle')
    page.wait_for_selector('#app:not(.hidden)', timeout=120000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=240000)
    page.evaluate("""() => {
        const it = [...document.querySelectorAll('.veh-item')]
            .find(x => x.querySelector('.vid')?.textContent.trim() === 'scania.s_2016');
        if (it) it.click();
    }""")
    page.wait_for_timeout(6000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)
    snap = lambda: page.evaluate("() => window.__ets2.snapshot()")

    print('=== stock build ===')
    info = page.evaluate("""() => {
        const S = window.__ets2.state;
        return {factory: S.factoryCount, parts: S.config.parts,
                acc: Object.keys(S.config.accessories).sort(),
                paint: (S.config.paint_job||'').split('/').pop(),
                instances: S.instances.length};
    }""")
    print('factory accessories:', info['factory'], '| instances:', info['instances'])
    print('parts:', {k: v.split('/')[-1] for k, v in info['parts'].items()},
          '| paint:', info['paint'])
    print('accessories:', ', '.join(info['acc']))
    s = stats(snap())
    print('render:', json.dumps(s))
    save(snap(), SHOT + r'\paint_factory.png')

    print('\n=== custom paint colour ===')
    has = page.evaluate("() => !!document.getElementById('paintColor')")
    print('colour picker present:', has)
    if has:
        page.evaluate("""() => {
            const el = document.getElementById('paintColor');
            el.value = '#c81e1e';
            el.dispatchEvent(new Event('input'));
        }""")
        page.wait_for_timeout(7000)
        page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                               timeout=180000)
        s2 = stats(snap())
        print('after red  :', json.dumps(s2))
        save(snap(), SHOT + r'\paint_custom.png')

    print('\n=== locked shell ===')
    lock = page.evaluate("""() => {
        const E = window.__ets2;
        E.clearSelection();
        E.selectSlot('cabin');
        const cabinBlocked = E.state.selectedKey === null &&
              document.getElementById('editPanel').classList.contains('hidden');
        const accSlot = Object.keys(E.state.groups).find(k => E.state.instances
              .find(i => i.slot === k && i.kind === 'accessory'));
        E.selectSlot(accSlot);
        return {cabinBlocked, accessorySelectable: E.state.selectedKey === accSlot,
                attached: !!E.gizmo.object, lockedRows:
                document.querySelectorAll('#coordTable tr.locked').length};
    }""")
    print(json.dumps(lock, ensure_ascii=False))
    page.evaluate("() => window.__ets2.clearSelection()")
    page.screenshot(path=SHOT + r'\screenshot.png')

    print('\n=== livery + colour variants ===')
    res = page.evaluate("""() => {
        const S = window.__ets2.state;
        const sel = document.getElementById('paintSelect');
        const byPath = new Map(S.current.paint_jobs.map(p => [p.path, p]));
        const pick = [...sel.options].map(o => byPath.get(o.value))
            .find(p => p && p.mask && (p.variants || []).length >= 8);
        if (!pick) return null;
        sel.value = pick.path; sel.dispatchEvent(new Event('change'));
        return {name: pick.name};
    }""")
    print('livery:', res)
    if res:
        page.wait_for_timeout(10000)
        page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                               timeout=180000)
        s3 = stats(snap())
        print('variant 1 :', json.dumps(s3))
        save(snap(), SHOT + r'\paint_livery.png')
        mesh = page.evaluate("""() => { let n=0; window.__ets2.truckRoot.traverse(o=>{
            if (o.isMesh && o.material.userData.liveryId) n++; }); return n; }""")
        print('meshes using the livery shader:', mesh)
        vs = page.evaluate("""() => {
            const vs = document.getElementById('variantSelect');
            if (!vs || vs.options.length < 2) return null;
            vs.value = '1'; vs.dispatchEvent(new Event('change'));
            return vs.options.length;
        }""")
        print('variant options:', vs)
        if vs:
            page.wait_for_timeout(9000)
            page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                                   timeout=180000)
            print('variant 2 :', json.dumps(stats(snap())))
            save(snap(), SHOT + r'\paint_livery2.png')
    page.screenshot(path=SHOT + r'\screenshot_edit.png')
    b.close()

print('\nerrors:', len(errors))
for e in errors[:8]:
    print('  ', e[:200])