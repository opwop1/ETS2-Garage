"""Measure only the truck pixels (canvas alpha) and compare paint variants."""
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
    im = Image.open(io.BytesIO(raw)).convert('RGBA')
    a = np.asarray(im).astype(np.float32)
    mask = a[:, :, 3] > 40
    if mask.sum() < 500:
        return {'area': int(mask.sum())}
    px = a[mask][:, :3]
    return {'area': int(mask.sum()),
            'mean': [round(float(v), 1) for v in px.mean(axis=0)],
            'std': round(float(px.std()), 2),
            'colors': len(np.unique((px // 16).astype(np.int32).reshape(-1, 3), axis=0))}


def grab(page):
    return page.evaluate("() => window.__ets2.snapshot()")


with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader',
                                '--enable-unsafe-swiftshader'])
    page = b.new_page(viewport={'width': 1400, 'height': 900})
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

    print('=== factory (solid colour) ===')
    print('stats:', page.text_content('#renderStats'))
    print('summary:', page.text_content('#truckSummary').replace('\n', ' ')[:120])
    f = grab(page)
    s0 = stats(f)
    print('truck pixels:', json.dumps(s0))
    Image.open(io.BytesIO(base64.b64decode(f.split(',', 1)[1]))).convert('RGB').save(
        SHOT + r'\paint_factory.png')

    print('\n=== pick a paint job with a strong base colour ===')
    res = page.evaluate("""() => {
        const S = window.__ets2.state;
        const sel = document.getElementById('paintSelect');
        const cand = S.current.paint_jobs.filter(p =>
            !p.mask && p.base_color && p.base_color.length === 3 &&
            (Math.abs(p.base_color[0] - p.base_color[1]) + Math.abs(p.base_color[1] - p.base_color[2])) > 0.25);
        const pick = cand.find(p => !p.suitable_for || !p.suitable_for.length ||
                                    p.suitable_for.includes(S.current.paint_jobs.cabUnit)) || cand[0];
        if (!pick) return null;
        sel.value = pick.path; sel.dispatchEvent(new Event('change'));
        return {name: pick.name, base: pick.base_color, list: cand.length};
    }""")
    print('picked coloured paint:', json.dumps(res, ensure_ascii=False))
    page.wait_for_timeout(8000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)
    f2 = grab(page)
    s1 = stats(f2)
    print('truck pixels:', json.dumps(s1))
    Image.open(io.BytesIO(base64.b64decode(f2.split(',', 1)[1]))).convert('RGB').save(
        SHOT + r'\paint_colored.png')

    print('\n=== pick a livery (mask) paint job ===')
    res2 = page.evaluate("""() => {
        const S = window.__ets2.state;
        const sel = document.getElementById('paintSelect');
        const byPath = new Map(S.current.paint_jobs.map(p => [p.path, p]));
        const pick = [...sel.options].map(o => byPath.get(o.value))
            .find(p => p && p.mask && (p.variants || []).length >= 8);
        if (!pick) return {error: 'no livery in the filtered list', options: sel.options.length};
        sel.value = pick.path; sel.dispatchEvent(new Event('change'));
        return {name: pick.name, mask: pick.mask, variants: pick.variants.length,
                options: sel.options.length};
    }""")
    print('picked livery:', json.dumps(res2, ensure_ascii=False))
    page.wait_for_timeout(10000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)
    f3 = grab(page)
    s2 = stats(f3)
    print('truck pixels:', json.dumps(s2))
    Image.open(io.BytesIO(base64.b64decode(f3.split(',', 1)[1]))).convert('RGB').save(
        SHOT + r'\paint_livery.png')

    diff = page.evaluate("""() => {
        const E = window.__ets2;
        let n = 0; E.truckRoot.traverse(o => { if (o.isMesh && o.material.userData.liveryId) n++; });
        return {liveryMeshes: n};
    }""")
    print('livery meshes:', diff)

    # switch colour variant of the livery
    var = page.evaluate("""() => {
        const vs = document.getElementById('variantSelect');
        if (!vs || vs.options.length < 2) return null;
        vs.value = '1'; vs.dispatchEvent(new Event('change'));
        return {options: vs.options.length, chosen: 1};
    }""")
    print('variant switch:', var)
    if var:
        page.wait_for_timeout(9000)
        page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                               timeout=180000)
        f4 = grab(page)
        print('variant-2 pixels:', json.dumps(stats(f4)))
    page.screenshot(path=SHOT + r'\screenshot.png')
    b.close()

print('\nerrors:', len(errors))
for e in errors[:8]:
    print('  ', e[:180])