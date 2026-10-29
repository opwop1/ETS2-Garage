"""Objectively verify that model textures are actually applied in the 3D view.

We diff the rendered canvas with textures enabled vs. disabled, and report how
many material textures actually finished loading.
"""
import base64
import io
import json

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

SHOT = r'F:\code\car-share\docs'
errors = []


def stats(png_bytes):
    im = Image.open(io.BytesIO(png_bytes)).convert('RGB')
    a = np.asarray(im).astype(np.float32)
    # ignore near-black background pixels
    mask = a.max(axis=2) > 24
    if mask.sum() < 1000:
        return {'area': int(mask.sum()), 'mean': [0, 0, 0], 'std': 0.0, 'colors': 0}
    px = a[mask]
    q = (px // 16).astype(np.int32)
    uniq = len(np.unique(q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]))
    return {'area': int(mask.sum()), 'mean': [round(float(v), 1) for v in px.mean(axis=0)],
            'std': round(float(px.std()), 2), 'colors': uniq}


with sync_playwright() as p:
    browser = p.chromium.launch(args=[
        '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
    page.goto('http://127.0.0.1:8765/', wait_until='networkidle')
    page.wait_for_selector('#app:not(.hidden)', timeout=120000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=240000)

    # track texture loads
    page.evaluate("""() => {
        window.__texlog = {ok: 0, fail: 0, names: []};
        const T = window.__ets2.THREE;
        const orig = T.TextureLoader.prototype.load;
        T.TextureLoader.prototype.load = function (url, onLoad, onProgress, onError) {
            return orig.call(this, url, (t) => {
                window.__texlog.ok++;
                window.__texlog.names.push(url.split('path=')[1]);
                if (onLoad) onLoad(t);
            }, onProgress, (e) => { window.__texlog.fail++; if (onError) onError(e); });
        };
    }""")

    # reload the model so textures go through the instrumented loader
    page.evaluate("() => window.__ets2.state.vehicles && 0")
    page.evaluate("""() => {
        const E = window.__ets2;
        const it = [...document.querySelectorAll('.veh-item')]
            .find(x => x.querySelector('.vid')?.textContent.trim() === 'scania.s_2016');
        if (it) it.click();
    }""")
    page.wait_for_timeout(3000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)
    page.wait_for_timeout(12000)     # let textures decode

    log = page.evaluate('() => window.__texlog')
    print('texture loads:', json.dumps(log, ensure_ascii=False)[:600])

    # material bindings
    bind = page.evaluate("""() => {
        const E = window.__ets2;
        let withMap = 0, withoutMap = 0, withImg = 0, vertexColored = 0, meshes = 0;
        const seen = new Set();
        E.truckRoot.traverse(o => {
            if (!o.isMesh) return;
            meshes++;
            const m = o.material;
            if (m.map) { withMap++; if (m.map.image) withImg++; }
            else withoutMap++;
            if (m.vertexColors) vertexColored++;
            if (m.map && m.map.image && m.map.image.src) seen.add(m.map.image.src);
        });
        return {meshes, withMap, withImg, withoutMap, vertexColored, distinctTextures: seen.size};
    }""")
    print('material bindings:', json.dumps(bind, ensure_ascii=False))

    canvas = page.query_selector('#gl')
    with_tex = canvas.screenshot(path=SHOT + r'\render_textured.png')
    print('TEXTURED  ', json.dumps(stats(with_tex)))

    # disable textures and re-render
    page.evaluate("""() => {
        window.__ets2.truckRoot.traverse(o => {
            if (o.isMesh && o.material.map) { o.material.__savedMap = o.material.map;
                o.material.map = null; o.material.needsUpdate = true; }
        });
    }""")
    page.wait_for_timeout(2500)
    no_tex = canvas.screenshot(path=SHOT + r'\render_untextured.png')
    print('UNTEXTURED', json.dumps(stats(no_tex)))

    # restore + also drop vertex colours for comparison
    page.evaluate("""() => {
        window.__ets2.truckRoot.traverse(o => {
            if (o.isMesh && o.material.__savedMap) { o.material.map = o.material.__savedMap;
                o.material.needsUpdate = true; }
        });
    }""")
    page.wait_for_timeout(1500)

    # per-material base texture list, plus average colour of each texture
    mats = page.evaluate("""() => Object.entries(window.__ets2.state.materials)
        .filter(([k, v]) => v.base_url)
        .map(([k, v]) => ({path: k, tex: v.base, url: v.base_url, effect: v.effect}))""")
    print(f'\nmaterials with a base texture: {len(mats)} / '
          f'{len(page.evaluate("() => Object.keys(window.__ets2.state.materials)"))}')
    for m in mats[:6]:
        print('   ', m['tex'], '|', (m['effect'] or '')[:38])
    browser.close()

print('\nerrors:', len(errors))
for e in errors[:8]:
    print('  ', e[:180])