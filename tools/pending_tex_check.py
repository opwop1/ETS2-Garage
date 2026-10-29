"""Confirm that 'pending' textures are just async loads, not failures."""
import json

from playwright.sync_api import sync_playwright

TARGETS = [('trailer', 'kassbohrer.sla'), ('trailer', 'krone.boxliner'),
           ('truck', 'daf.xf_electric'), ('truck', 'scania.streamline')]

PICK = """(a) => {
    window.__target = a[1];
    const tab = document.querySelector('.tab[data-cat="' + a[0] + '"]');
    if (tab && !tab.classList.contains('active')) tab.click();
    const it = [...document.querySelectorAll('.veh-item')]
        .find(x => x.querySelector('.vid')?.textContent.trim() === a[1]);
    if (it) it.click();
}"""

COUNT = """() => {
    let meshes = 0, withMap = 0, loaded = 0, pending = 0, brokenSrc = 0;
    window.__ets2.truckRoot.traverse(o => {
        if (!o.isMesh) return;
        meshes++;
        const m = o.material;
        if (!m.map) return;
        withMap++;
        const im = m.map.image;
        if (im && im.width) loaded++; else pending++;
    });
    return {meshes, withMap, loaded, pending};
}"""

with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader',
                                '--enable-unsafe-swiftshader'])
    page = b.new_page(viewport={'width': 1400, 'height': 900})
    errs = []
    page.on('console', lambda m: errs.append(m.text[:140]) if m.type == 'error' else None)
    page.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)[:150]))
    page.goto('http://127.0.0.1:8770/', wait_until='networkidle')
    page.wait_for_selector('#app:not(.hidden)', timeout=120000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=240000)
    for cat, vid in TARGETS:
        page.evaluate(PICK, [cat, vid])
        page.wait_for_function("() => window.__ets2.state.current?.id === window.__target",
                               timeout=60000)
        for wait in (2, 10, 25):
            page.wait_for_timeout(wait * 1000)
            print(f'  {vid:20s} +{wait:2d}s: {json.dumps(page.evaluate(COUNT))}')
    print('console errors:', len(errs))
    for e in errs[:6]:
        print('   ', e)
    b.close()