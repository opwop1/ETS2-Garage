"""Sanity-check the two trailers that have almost no declared defaults."""
import json

from playwright.sync_api import sync_playwright

TARGETS = [('trailer', 'krone.boxliner'), ('trailer', 'wielton.containerm'),
           ('trailer', 'tirsan.shg'), ('trailer', 'schwmuller.reefer'),
           ('truck', 'man.tgx'), ('truck', 'scania.s_2016')]

PICK = """(a) => {
    window.__target = a[1];
    const tab = document.querySelector('.tab[data-cat="' + a[0] + '"]');
    if (tab && !tab.classList.contains('active')) tab.click();
    const it = [...document.querySelectorAll('.veh-item')]
        .find(x => x.querySelector('.vid')?.textContent.trim() === a[1]);
    if (it) it.click();
}"""

INFO = """() => {
    const S = window.__ets2.state;
    const T = window.__ets2.THREE;
    const bb = new T.Box3().setFromObject(window.__ets2.truckRoot);
    const sz = bb.getSize(new T.Vector3());
    let meshes = 0, withImg = 0, broken = 0;
    window.__ets2.truckRoot.traverse(o => { if (!o.isMesh) return; meshes++;
        const m = o.material;
        if (m.map) { if (m.map.image && m.map.image.width) withImg++; else broken++; } });
    return {
        parts: S.instances.map(i => i.slot + ':' + i.model),
        kinds: S.instances.map(i => i.kind),
        tris: S.instances.reduce((a,i)=>a+i.pieces.reduce((x,p)=>x+(p.skip?0:p.triangles),0),0),
        meshes, withImg, broken,
        size: [+sz.x.toFixed(2), +sz.y.toFixed(2), +sz.z.toFixed(2)],
    };
}"""

with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader',
                                '--enable-unsafe-swiftshader'])
    page = b.new_page(viewport={'width': 1500, 'height': 950})
    errs = []
    page.on('console', lambda m: errs.append(m.text[:130]) if m.type == 'error' else None)
    page.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)[:150]))
    page.goto('http://127.0.0.1:8770/', wait_until='networkidle')
    page.wait_for_selector('#app:not(.hidden)', timeout=120000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=240000)
    for cat, vid in TARGETS:
        page.evaluate(PICK, [cat, vid])
        page.wait_for_function("() => window.__ets2.state.current?.id === window.__target",
                               timeout=60000)
        page.wait_for_timeout(6000)
        info = page.evaluate(INFO)
        print(f"{vid:22s} parts={len(info['parts']):3d} tris={info['tris']:7d} "
              f"mesh={info['meshes']:4d} tex={info['withImg']:4d} broken={info['broken']} "
              f"size={info['size']}")
        print('      ', ', '.join(info['parts'][:12]) + (' ...' if len(info['parts']) > 12 else ''))
    print('errors:', len(errs))
    for e in errs[:5]:
        print('   ', e)
    b.close()