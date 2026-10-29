"""Full UI verification: pick a truck, mix accessories from other trucks, screenshot."""
import json
import sys
import time

from playwright.sync_api import sync_playwright

SHOT = r'F:\code\car-share\docs'
errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(args=[
        '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    page = browser.new_page(viewport={'width': 1680, 'height': 1000})
    page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
    page.on('console', lambda m: errors.append(f'{m.type}: {m.text}') if m.type == 'error' else None)
    page.goto('http://127.0.0.1:8765/', wait_until='networkidle')
    page.wait_for_selector('#app:not(.hidden)', timeout=120000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=240000)

    def pick_vehicle(vid):
        page.evaluate("""(vid) => {
            const items = [...document.querySelectorAll('.veh-item')];
            const it = items.find(x => x.querySelector('.vid')?.textContent.trim() === vid);
            if (it) it.click();
        }""", vid)
        page.wait_for_timeout(3000)
        page.wait_for_function(
            "() => document.getElementById('renderStats').textContent.length>0", timeout=180000)

    pick_vehicle('scania.s_2016')
    print('scania stats:', page.text_content('#renderStats'))

    # mix a Volvo/S10xx part onto the Scania: open 'beacon' and pick the first non-Scania option
    page.evaluate("""() => {
        const c = [...document.querySelectorAll('.slot')]
            .find(x => x.querySelector('.slot-name')?.textContent.trim() === 'beacon');
        if (c) c.click();
    }""")
    page.wait_for_selector('.modal:not(.hidden)', timeout=20000)
    page.wait_for_function("() => document.querySelectorAll('#pickerList .opt').length > 1",
                           timeout=180000)
    mixed = page.evaluate("""() => {
        const opts = [...document.querySelectorAll('#pickerList .opt')];
        const foreign = opts.find(o => {
            const f = o.querySelector('.ofrom')?.textContent || '';
            return f.includes('daf') || f.includes('volvo') || f.includes('man');
        });
        if (!foreign) return null;
        const name = foreign.querySelector('.oname').textContent;
        const from = foreign.querySelector('.ofrom').textContent;
        foreign.click();
        return {name, from};
    }""")
    print('mixed in:', mixed)
    page.wait_for_timeout(5000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)

    rows = page.eval_on_selector_all('#coordTable tbody tr',
                                     'els => els.map(e => Array.from(e.children).map(c => c.textContent))')
    print(f'coordinate rows: {len(rows)}')
    for r in rows[:14]:
        print('   ', ' | '.join(r))

    stats = page.evaluate("""() => {
        const T = window.__ets2.THREE, root = window.__ets2.truckRoot;
        let meshes = 0, tris = 0;
        root.traverse(o => { if (o.isMesh) { meshes++; tris += o.geometry.index ? o.geometry.index.count/3 : 0; } });
        const bb = new T.Box3().setFromObject(root);
        return {meshes, tris, size: bb.getSize(new T.Vector3()).toArray().map(v=>+v.toFixed(2)),
                center: bb.getCenter(new T.Vector3()).toArray().map(v=>+v.toFixed(2)),
                locators: window.__ets2.locatorRoot.children.length};
    }""")
    print('scene:', json.dumps(stats))
    page.screenshot(path=SHOT + r'\screenshot.png')

    # open a picker screenshot showing cross-truck list
    page.evaluate("""() => {
        const c = [...document.querySelectorAll('.slot')]
            .find(x => x.querySelector('.slot-name')?.textContent.trim() === 'f_bumper');
        if (c) c.click();
    }""")
    page.wait_for_selector('.modal:not(.hidden)', timeout=20000)
    page.wait_for_function("() => document.querySelectorAll('#pickerList .opt').length > 1",
                           timeout=180000)
    page.screenshot(path=SHOT + r'\screenshot_picker.png')
    page.keyboard.press('Escape')
    page.evaluate("() => document.getElementById('pickerClose').click()")

    # trailer check
    page.evaluate("() => document.querySelector('.tab[data-cat=\"trailer\"]').click()")
    page.wait_for_timeout(800)
    trailers = page.eval_on_selector_all('.veh-item', 'e => e.length')
    print('trailer entries:', trailers)
    if trailers:
        page.evaluate("() => document.querySelectorAll('.veh-item')[0].click()")
        page.wait_for_timeout(4000)
        print('trailer stats:', page.text_content('#renderStats'))
        page.screenshot(path=SHOT + r'\screenshot_trailer.png')

    browser.close()

print('errors:', len(errors))
for e in errors[:10]:
    print('  ', e[:200])