"""Verify the 3D transform editor: select, nudge, gizmo modes, drop-to-surface."""
import json

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

    # pick the Scania S 2016 and pour a foreign (DAF) beacon onto it
    page.evaluate("""() => {
        const it = [...document.querySelectorAll('.veh-item')]
            .find(x => x.querySelector('.vid')?.textContent.trim() === 'scania.s_2016');
        if (it) it.click();
    }""")
    page.wait_for_timeout(4000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)
    page.evaluate("""() => {
        const c = [...document.querySelectorAll('.slot')]
            .find(x => x.querySelector('.slot-name')?.textContent.trim() === 'beacon');
        c.click();
    }""")
    page.wait_for_selector('.modal:not(.hidden)', timeout=20000)
    page.wait_for_function("() => document.querySelectorAll('#pickerList .opt').length > 1",
                           timeout=180000)
    page.evaluate("""() => {
        const opts = [...document.querySelectorAll('#pickerList .opt')];
        const foreign = opts.find(o => (o.querySelector('.ofrom')?.textContent || '').includes('daf'));
        (foreign || opts[1]).click();
    }""")
    page.wait_for_timeout(5000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=180000)

    print('=== 1. selection ===')
    st = page.evaluate("""() => {
        const E = window.__ets2;
        E.selectSlot('beacon');
        return {selected: E.state.selectedKey,
                attached: !!E.gizmo.object,
                attachedSlot: E.gizmo.object && E.gizmo.object.userData.slot,
                panelVisible: !document.getElementById('editPanel').classList.contains('hidden'),
                title: document.getElementById('editTitle').textContent};
    }""")
    print(json.dumps(st, ensure_ascii=False))

    def row_of(slot):
        return page.evaluate("""(slot) => {
            const r = window.__ets2.state.coordRows.find(x => x.key === slot);
            return r ? {base:r.base, offset:r.offset, final:r.final, rot:r.rot, scale:r.scale, moved:r.moved} : null;
        }""", slot)

    before = row_of('beacon')
    print('before:', json.dumps({k: [round(v, 4) for v in before[k]] if isinstance(before[k], list) else before[k]
                                 for k in ('base', 'offset', 'final', 'moved')}, ensure_ascii=False))

    print('\n=== 2. nudge +X 5 steps, +Y 3 steps (0.05 m step) ===')
    page.evaluate("""() => {
        document.getElementById('epStep').value = '0.05';
        const E = window.__ets2;
        for (let i = 0; i < 5; i++) E.bump('px', 1);
        for (let i = 0; i < 3; i++) E.bump('py', 1);
    }""")
    after = row_of('beacon')
    print('after :', json.dumps({k: [round(v, 4) for v in after[k]] if isinstance(after[k], list) else after[k]
                                 for k in ('base', 'offset', 'final', 'moved')}, ensure_ascii=False))
    print('readout:', page.text_content('#epReadout').replace('\n', ' | '))

    print('\n=== 3. numeric input + rotate + scale ===')
    page.evaluate("""() => {
        const E = window.__ets2;
        E.state.edits.beacon.rot = [0, 30, 0];
        E.state.edits.beacon.scale = 1.5;
        E.applyEditToGroup(E.state.groups.beacon, E.state.bases.beacon, E.state.edits.beacon);
        E.renderCoordTable();
    }""")
    rot = row_of('beacon')
    print('rot/scale:', json.dumps({'rot': [round(v, 2) for v in rot['rot']], 'scale': round(rot['scale'], 3),
                                    'final': [round(v, 4) for v in rot['final']]}, ensure_ascii=False))

    print('\n=== 4. gizmo modes ===')
    for mode in ('rotate', 'scale', 'translate'):
        info = page.evaluate("(m) => { window.__ets2.setGizmoMode(m);"
                             " return {mode: window.__ets2.gizmo.mode, space: window.__ets2.gizmo.space}; }", mode)
        print('  ', mode, info)

    print('\n=== 5. drop to surface ===')
    page.evaluate("() => { document.getElementById('epDrop').click(); }")
    page.wait_for_timeout(400)
    dropped = row_of('beacon')
    print('after drop:', json.dumps({'offset': [round(v, 4) for v in dropped['offset']],
                                     'final': [round(v, 4) for v in dropped['final']]}, ensure_ascii=False))

    print('\n=== 6. panel button bump (DOM) ===')
    page.evaluate("""() => {
        const btns = [...document.querySelectorAll('.ep-ctl button')];
        btns.find(b => b.dataset.axis === 'pz' && b.dataset.d === '1').click();
    }""")
    page.wait_for_timeout(200)
    z = row_of('beacon')
    print('z offset after DOM click:', round(z['offset'][2], 4))

    print('\n=== 7. reset ===')
    page.evaluate("() => document.getElementById('editReset').click()")
    page.wait_for_timeout(200)
    reset = row_of('beacon')
    print('after reset:', json.dumps({'offset': [round(v, 4) for v in reset['offset']],
                                      'final': [round(v, 4) for v in reset['final']],
                                      'moved': reset['moved']}, ensure_ascii=False))

    # make a nice screenshot with an obvious offset
    page.evaluate("""() => {
        const E = window.__ets2;
        E.selectSlot('beacon');
        document.getElementById('epStep').value = '0.05';
        for (let i = 0; i < 3; i++) E.bump('py', 1);
        for (let i = 0; i < 4; i++) E.bump('pz', -1);
    }""")
    page.wait_for_timeout(1200)
    page.screenshot(path=SHOT + r'\screenshot_edit.png')
    print('\nscreenshot ->', SHOT + r'\screenshot_edit.png')
    browser.close()

print('\nerrors:', len(errors))
for e in errors[:10]:
    print('  ', e[:200])