"""Regenerate the showcase screenshots."""
import base64
import io
import os

from PIL import Image
from playwright.sync_api import sync_playwright

SHOT = r'F:\code\car-share\docs'
TARGETS = [('truck', 'scania.s_2016', 'screenshot'),
           ('truck', 'daf.xf', 'screenshot_dafxf'),
           ('truck', 'daf.xf_euro6', 'screenshot_dafxf_euro6'),
           ('truck', 'man.tgx', 'screenshot_old'),
           ('trailer', 'schwmuller.reefer', 'screenshot_trailer')]

PICK = """(a) => {
    window.__target = a[1];
    const tab = document.querySelector('[data-cat="' + a[0] + '"]');
    if (tab && !tab.classList.contains('active')) tab.click();
    const it = [...document.querySelectorAll('.veh-item')]
        .find(x => x.querySelector('.vid')?.textContent.trim() === a[1]);
    if (it) it.click();
}"""

with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader',
                                '--enable-unsafe-swiftshader'])
    page = b.new_page(viewport={'width': 1680, 'height': 1000})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)[:150]))
    page.on('console', lambda m: errs.append(m.text[:120]) if m.type == 'error' else None)
    page.goto('http://127.0.0.1:8770/', wait_until='networkidle')
    page.wait_for_selector('#app:not(.hidden)', timeout=120000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length>0",
                           timeout=240000)
    for cat, vid, name in TARGETS:
        page.evaluate(PICK, [cat, vid])
        page.wait_for_function("() => window.__ets2.state.current?.id === window.__target",
                               timeout=60000)
        page.wait_for_timeout(16000)
        print(f'{name:20s} {page.text_content("#renderStats")}')
        page.screenshot(path=os.path.join(SHOT, name + '.png'))
        d = page.evaluate('() => window.__ets2.snapshot()')
        Image.open(io.BytesIO(base64.b64decode(d.split(',', 1)[1]))).convert('RGB').save(
            os.path.join(SHOT, 'render_' + name + '.png'))
    print('errors:', errs[:4])
    b.close()