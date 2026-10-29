"""Verify stock build + paint/livery + locked shell."""
import base64
import io
import json

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

SHOT = r'F:\code\car-share\docs'
errors = []


def stats(png):
    a = np.asarray(Image.open(io.BytesIO(png)).convert('RGB')).astype(np.float32)
    m = a.max(axis=2) > 24
    if m.sum() < 1000:
        return {'area': int(m.sum())}
    px = a[m]
    return {'area': int(m.sum()), 'mean': [round(float(v), 1) for v in px.mean(axis=0)],
            'std': round(float(px.std()), 2),
            'colors': len(np.unique((px // 16).astype(np.int32).reshape(-1, 3), axis=0))}


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

    print('=== 1. stock/factory build ===')
    info = page.evaluate("""() => {
        const S = window.__ets2.state;
        return {count: S.factoryCount, parts: S.config.parts, paint: S.config.paint_job,
                accessories: Object.keys(S.config.accessories).length,
                kinds: S.instances.map(i => i.kind)};
    }""")
    print('factoryCount:', info['count'], '| accessories:', info['accessories'])
    print('parts:', {k: v.split('/')[-1] for k, v in info['parts'].items()})
    print('paint_job:', (info['paint'] or '').split('/')[-1])
    print('cart summary:', page.text_content('#truckSummary').replace('\n', ' ')[:130])

    print('\n=== 2. locked shell ===')
    lock = page.evaluate("""() => {
        const E = window.__ets2;
        E.selectSlot(E.state.instances[0].slot);
        const locked = {selected: E.state.selectedKey, panelHidden:
            document.getElementById('editPanel').classList.contains('hidden')};
        E.selectSlot('beacon');
        const acc = {selected: E.state.selectedKey, attached: !!E.gizmo.object};
        return {locked, acc,
                lockedRows: document.querySelectorAll('#coordTable tr.locked').length};
    }""")
    print(json.dumps(lock, ensure_ascii=False))

    print('\n=== 3. paint: factory colour ===')
    base = page.evaluate("""() => {
        const S = window.__ets2.state;
        const pm = Object.values(S.materials).filter(m => m.is_paint);
        return pm.map(m => ({effect: m.effect, base: m.paint && m.paint.base,
                             mask: !!(m.paint && m.paint.mask),
                             variants: (m.paint && m.paint.variants.length) || 0}));
    }""")
    print(json.dumps(base, ensure_ascii=False))
    canvas = page.query_selector('#gl')
    png_factory = canvas.screenshot(path=SHOT + r'\paint_factory.png')
    print('factory render:', json.dumps(stats(png_factory)))

    print('\n=== 4. paint: pick a livery paint job ===')
    picked = page.evaluate("""() => {
        const sel = document.getElementById('paintSelect');
        if (!sel) return null;
        const S = window.__ets2.state;
        const opts = [...sel.options];
        const i = opts.findIndex(o => o.textContent.includes('academy'));
        const o = opts[i >= 0 ? i : Math.min(1, opts.length - 1)];
        sel.value = o.value;
        sel.dispatchEvent(new Event('change'));
        return {name: o.textContent, value: o.value};
    }""")
    print('picked:', picked)
    page.wait_for_timeout(9000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)
    livery = page.evaluate("""() => {
        const S = window.__ets2.state;
        const pm = Object.values(S.materials).filter(m => m.is_paint);
        return {paintDef: (S.config.paint_job||'').split('/').pop(),
                materials: pm.map(m => ({mask: !!(m.paint && m.paint.mask),
                                         base: m.paint && m.paint.base,
                                         palette: (m.paint && m.paint.variants.length) || 0})),
                shaderMeshes: (() => { let n = 0; window.__ets2.truckRoot.traverse(o => {
                    if (o.isMesh && o.material.userData.liveryId) n++; }); return n; })()};
    }""")
    print(json.dumps(livery, ensure_ascii=False))
    png_livery = canvas.screenshot(path=SHOT + r'\paint_livery.png')
    print('livery render:', json.dumps(stats(png_livery)))
    page.screenshot(path=SHOT + r'\screenshot.png')

    b.close()

print('\nerrors:', len(errors))
for e in errors[:8]:
    print('  ', e[:180])