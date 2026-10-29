"""Check that every vehicle comes out complete, and that concurrent texture
loads no longer corrupt archive reads."""
import base64
import io
import json
import threading
import urllib.request

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8770'


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path).read())


with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader',
                                '--enable-unsafe-swiftshader'])
    page = b.new_page(viewport={'width': 1680, 'height': 1000})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)[:200]))
    page.on('console', lambda m: errs.append(f'{m.type}:{m.text[:160]}') if m.type == 'error' else None)
    page.goto(BASE + '/', wait_until='networkidle')
    page.wait_for_selector('#app:not(.hidden)', timeout=120000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=240000)

    print('=== every truck / trailer gets a complete stock build ===')
    vehicles = get('/api/vehicles')['vehicles']
    step = int(__import__('os').environ.get('STEP', '1'))
    vehicles = vehicles[::step]
    bad = []
    checked = 0
    for v in vehicles:
        page.evaluate("""(args) => {
            const [cat, vid] = args;
            const E = window.__ets2;
            window.__target = vid;
            const tab = document.querySelector(`.tab[data-cat="${cat}"]`);
            if (tab && !tab.classList.contains('active')) tab.click();
            const it = [...document.querySelectorAll('.veh-item')]
                .find(x => x.querySelector('.vid')?.textContent.trim() === vid);
            if (it) it.click();
        }""", [v['category'], v['id']])
        try:
            page.wait_for_function("() => window.__ets2.state.current?.id === window.__target",
                                   timeout=60000)
            page.wait_for_function(
                "() => document.getElementById('renderStats').textContent.length>0", timeout=120000)
            page.wait_for_timeout(400)
            # the auto-fill pass triggers a second build; wait until it settles
            page.wait_for_function(
                "() => !document.getElementById('loading') || "
                "document.getElementById('loading').classList.contains('hidden')", timeout=120000)
        except Exception as exc:
            bad.append((v['id'], f'timeout {exc}'))
            continue
        info = page.evaluate("""() => {
            const E = window.__ets2, S = E.state, d = S.current;
            const NON_MODEL = new Set(['engine', 'transmission', 'head_light', 'paint_job']);
            const PRIMARIES = new Set(['cabin', 'chassis', 'body']);
            const declared = [...new Set([...Object.keys(d.factory || {}),
                                          ...Object.keys(d.defaults || {})])]
                .filter(k => !NON_MODEL.has(k) && !PRIMARIES.has(k));
            const notLoaded = declared.filter(k => !S.config.accessories[k] && !S.config.parts[k]);
            const req = (d.required_slots || []).filter(s =>
                !NON_MODEL.has(s) && !S.config.accessories[s] && !S.config.parts[s]);
            const missingPrimary = (d.primaries || []).filter(pr => pr.options.length &&
                !S.config.parts[pr.key]).map(pr => pr.key);
            const kinds = S.instances.map(i => i.kind);
            const bb = new window.__ets2.THREE.Box3().setFromObject(window.__ets2.truckRoot);
            const sz = bb.isEmpty() ? null : bb.getSize(new window.__ets2.THREE.Vector3());
            let meshes = 0, withMap = 0, withImg = 0, broken = 0;
            E.truckRoot.traverse(o => { if (!o.isMesh) return; meshes++;
                const m = o.material;
                if (m.map) { withMap++; if (m.map.image && m.map.image.width) withImg++; else broken++; } });
            return {id: d.id, declared: declared.length, notLoaded, req: req.length,
                    missingReq: req, missingPrimary, kinds,
                    filled: Object.keys(S.config.accessories).length,
                    parts: S.instances.length, meshes, withMap, withImg, broken,
                    size: sz ? [+sz.x.toFixed(2), +sz.y.toFixed(2), +sz.z.toFixed(2)] : null,
                    tris: S.instances.reduce((a,i)=>a+i.pieces.reduce((x,p)=>x+(p.skip?0:p.triangles),0),0)};
        }""")
        checked += 1
        problems = []
        if info['notLoaded']:
            problems.append('defaults:' + ','.join(info['notLoaded'][:4]))
        if info['missingReq']:
            problems.append('require:' + ','.join(info['missingReq'][:4]))
        if info['missingPrimary']:
            problems.append('primary:' + ','.join(info['missingPrimary']))
        if info['broken']:
            problems.append('tex:' + str(info['broken']))
        if info['parts'] < 3:
            problems.append('too-few-parts')
        if info['size'] and max(info['size']) > 30:
            problems.append('bad-size:' + str(info['size']))
        ok = not problems
        if not ok:
            bad.append((info['id'], problems))
        print(f"  {info['id']:22s} decl={info['declared']:3d} filled={info['filled']:3d} "
              f"parts={info['parts']:3d} mesh={info['meshes']:4d} tex={info['withImg']:4d} "
              f"size={info['size']} tris={info['tris']:7d}"
              + ('' if ok else '  <-- ' + '; '.join(problems)))
    print(f'checked {checked}, incomplete: {len(bad)}')
    for x in bad[:10]:
        print('   INCOMPLETE', x)

    print('\n=== concurrent texture loading (race check) ===')
    page.evaluate("""() => {
        const it = [...document.querySelectorAll('.veh-item')]
            .find(x => x.querySelector('.vid')?.textContent.trim() === 'scania.s_2016');
        if (it) it.click();
    }""")
    page.wait_for_timeout(9000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)
    page.wait_for_timeout(9000)
    mesh = page.evaluate("""() => {
        let meshes=0, withMap=0, withImg=0, broken=0; const tex=new Set();
        window.__ets2.truckRoot.traverse(o => { if (!o.isMesh) return; meshes++;
            const m = o.material;
            if (m.map) { withMap++; if (m.map.image && m.map.image.width) { withImg++;
                tex.add(m.map.image.src); } else broken++; } });
        return {meshes, withMap, withImg, broken, distinct: tex.size};
    }""")
    print('meshes:', json.dumps(mesh))
    print('errors:', len(errs))
    for e in errs[:6]:
        print('   ', e)
    page.screenshot(path=r'F:\code\car-share\docs\screenshot.png')
    d = page.evaluate('() => window.__ets2.snapshot()')
    Image.open(io.BytesIO(base64.b64decode(d.split(',', 1)[1]))).convert('RGB').save(
        r'F:\code\car-share\docs\render_stock.png')
    b.close()