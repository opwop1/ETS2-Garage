"""Verify the viewport no longer distorts when the window is resized."""
import json

from playwright.sync_api import sync_playwright

SIZES = [(1680, 1000), (1000, 800), (1400, 520), (900, 1100), (1920, 720), (760, 640)]

CHECK = """() => {
    const E = window.__ets2;
    const c = document.getElementById('gl');
    const size = E.renderer.getSize(new E.THREE.Vector2());
    const dpr = E.renderer.getPixelRatio();
    return {
        cssW: c.clientWidth, cssH: c.clientHeight,
        bufW: c.width, bufH: c.height,
        rendererW: Math.round(size.x), rendererH: Math.round(size.y),
        aspect: +E.camera.aspect.toFixed(5),
        cssAspect: +(c.clientWidth / Math.max(1, c.clientHeight)).toFixed(5),
        dpr: +dpr.toFixed(3),
        fov: E.camera.fov,
        // horizontal vs vertical scale of the projection matrix
        p00: +E.camera.projectionMatrix.elements[0].toFixed(5),
        p11: +E.camera.projectionMatrix.elements[5].toFixed(5),
    };
}"""

with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader',
                                '--enable-unsafe-swiftshader'])
    page = b.new_page(viewport={'width': SIZES[0][0], 'height': SIZES[0][1]})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)[:180]))
    page.on('console', lambda m: errs.append(m.text[:140]) if m.type == 'error' else None)
    page.goto('http://127.0.0.1:8770/', wait_until='networkidle')
    page.wait_for_selector('#app:not(.hidden)', timeout=120000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=240000)
    page.evaluate("""() => {
        const it = [...document.querySelectorAll('.veh-item')]
            .find(x => x.querySelector('.vid')?.textContent.trim() === 'scania.s_2016');
        if (it) it.click();
    }""")
    page.wait_for_timeout(9000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)

    bad = 0
    for w, h in SIZES:
        page.set_viewport_size({'width': w, 'height': h})
        page.wait_for_timeout(700)          # let layout + one animation frame land
        r = page.evaluate(CHECK)
        ok = (abs(r['aspect'] - r['cssAspect']) < 1e-3
              and r['bufW'] == round(r['cssW'] * r['dpr'])
              and r['bufH'] == round(r['cssH'] * r['dpr'])
              and r['rendererW'] == r['cssW'] and r['rendererH'] == r['cssH'])
        if not ok:
            bad += 1
        print(f"  {w:5d}x{h:<5d} css={r['cssW']}x{r['cssH']} buf={r['bufW']}x{r['bufH']} "
              f"renderer={r['rendererW']}x{r['rendererH']} aspect={r['aspect']} "
              f"cssAspect={r['cssAspect']} dpr={r['dpr']} "
              f"p00={r['p00']} p11={r['p11']}  {'OK' if ok else '<-- MISMATCH'}")
    print('mismatches:', bad)
    print('errors:', errs[:4])
    page.set_viewport_size({'width': 1680, 'height': 1000})
    page.wait_for_timeout(600)
    b.close()