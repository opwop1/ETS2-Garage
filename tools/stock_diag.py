"""Diagnose: what does a stock truck actually contain, and is it visible?"""
import base64
import io
import json

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright


def stats(data_url):
    raw = base64.b64decode(data_url.split(',', 1)[1])
    a = np.asarray(Image.open(io.BytesIO(raw)).convert('RGBA')).astype(np.float32)
    m = a[:, :, 3] > 40
    if m.sum() < 200:
        return {'area': int(m.sum())}
    px = a[m][:, :3]
    return {'area': int(m.sum()), 'mean': [round(float(v), 1) for v in px.mean(axis=0)]}


with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader',
                                '--enable-unsafe-swiftshader'])
    page = b.new_page(viewport={'width': 1400, 'height': 900})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)[:300]))
    page.on('console', lambda m: errs.append(f'{m.type}:{m.text[:200]}') if m.type == 'error' else None)
    page.goto('http://127.0.0.1:8770/', wait_until='networkidle')
    page.wait_for_selector('#app:not(.hidden)', timeout=120000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=240000)
    page.evaluate("""() => {
        const it = [...document.querySelectorAll('.veh-item')]
            .find(x => x.querySelector('.vid')?.textContent.trim() === 'daf.xd');
        if (it) it.click();
    }""")
    page.wait_for_timeout(6000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)

    print('=== what the stock truck contains ===')
    inv = page.evaluate("""() => {
        const E = window.__ets2, S = E.state, T = E.THREE;
        E.truckRoot.updateMatrixWorld(true);
        const out = [];
        for (const inst of S.instances) {
            const g = S.groups[inst.slot];
            if (!g) continue;
            const bb = new T.Box3().setFromObject(g);
            const sz = bb.getSize(new T.Vector3());
            const c = bb.getCenter(new T.Vector3());
            out.push({slot: inst.slot, kind: inst.kind, locator: inst.locator,
                      verts: inst.pieces.reduce((a, p) => a + (p.skip ? 0 : p.count), 0),
                      tris: inst.pieces.reduce((a, p) => a + (p.skip ? 0 : p.triangles), 0),
                      size: [+sz.x.toFixed(2), +sz.y.toFixed(2), +sz.z.toFixed(2)],
                      center: [+c.x.toFixed(2), +c.y.toFixed(2), +c.z.toFixed(2)]});
        }
        return out;
    }""")
    for r in inv:
        print(f"   {r['kind']:9s} {r['slot']:12s} loc={str(r['locator']):14s} "
              f"tris={r['tris']:6d} size={r['size']} center={r['center']}")
    print('   total instances:', len(inv))

    print('\n=== render: stock vs bare shell ===')
    stock = page.evaluate("() => window.__ets2.snapshot()")
    print('stock   :', json.dumps(stats(stock)))

    bare = page.evaluate("""async () => {
        const E = window.__ets2, S = E.state;
        const saved = JSON.parse(JSON.stringify(S.config.accessories));
        S.config.accessories = {};
        await E.refreshModel();
        const s = E.snapshot();
        S.config.accessories = saved;
        await E.refreshModel();
        return s;
    }""")
    print('bare    :', json.dumps(stats(bare)))

    print('\n=== wheels: are they loaded at all? ===')
    wheels = page.evaluate("""() => {
        const d = window.__ets2.state.current;
        return {otherKeys: Object.keys(d.other || {}),
                wheelLists: {f_tire: (d.other.f_tire||[]).length,
                             r_tire: (d.other.r_tire||[]).length,
                             f_disc: (d.other.f_disc||[]).length,
                             f_hub: (d.other.f_hub||[]).length},
                defaults: d.defaults,
                factoryKeys: Object.keys(d.factory),
                filledKeys: Object.keys(d.factory_filled)};
    }""")
    print(json.dumps(wheels, ensure_ascii=False)[:900])

    print('\n=== reset-to-factory button ===')
    btn = page.evaluate("""() => {
        const b = document.getElementById('loadFactory');
        if (!b) return {found: false};
        b.click();
        return {found: true, text: b.textContent};
    }""")
    print('click:', btn)
    page.wait_for_timeout(6000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)
    after = page.evaluate("""() => ({
        factoryCount: window.__ets2.state.factoryCount,
        acc: Object.keys(window.__ets2.state.config.accessories).length,
        paint: (window.__ets2.state.config.paint_job||'').split('/').pop(),
        stats: document.getElementById('renderStats').textContent})""")
    print('after reset:', json.dumps(after, ensure_ascii=False))

    print('\n=== default paint job ===')
    pj = page.evaluate("""() => {
        const S = window.__ets2.state, d = S.current;
        const sel = document.getElementById('paintSelect');
        return {configured: S.config.paint_job,
                configuredName: (S.current.paint_jobs.find(p=>p.path===S.config.paint_job)||{}).name,
                hasMask: !!(S.current.paint_jobs.find(p=>p.path===S.config.paint_job)||{}).mask,
                selectValue: sel ? sel.value : null,
                selectFirst: sel && sel.options.length ? sel.options[0].value : null,
                firstIsMask: !!(S.current.paint_jobs.find(p=>p.path===(sel&&sel.options[0]&&sel.options[0].value))||{}).mask,
                firstThree: sel ? [...sel.options].slice(0,3).map(o=>o.textContent) : []};
    }""")
    print(json.dumps(pj, ensure_ascii=False))
    b.close()

print('\nerrors:', len(errs))
for e in errs[:6]:
    print('  ', e)