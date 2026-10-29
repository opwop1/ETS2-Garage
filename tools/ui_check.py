"""Drive the UI in a real browser to verify the app end to end."""
import json
import sys
import time

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765/'
OUT = sys.argv[2] if len(sys.argv) > 2 else r'F:\code\car-share\docs\screenshot.png'

errors = []
logs = []

with sync_playwright() as p:
    browser = p.chromium.launch(args=[
        '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
        '--ignore-gpu-blocklist', '--enable-webgl',
    ])
    page = browser.new_page(viewport={'width': 1560, 'height': 950})
    page.on('console', lambda m: (errors if m.type == 'error' else logs).append(m.text))
    page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
    page.goto(URL, wait_until='networkidle')

    page.wait_for_selector('#app:not(.hidden)', timeout=90000)
    page.wait_for_selector('.veh-item', timeout=60000)
    print('vehicles listed:', page.eval_on_selector_all('.veh-item', 'els => els.length'))

    page.wait_for_function(
        "() => document.getElementById('renderStats').textContent.length > 0",
        timeout=180000)
    stats = page.text_content('#renderStats')
    print('render stats:', stats)

    rows = page.eval_on_selector_all('#coordTable tbody tr',
                                     'els => els.map(e => Array.from(e.children).map(c => c.textContent))')
    print('coordinate rows:', len(rows))
    for r in rows[:10]:
        print('   ', r)

    page.screenshot(path=OUT, full_page=False)
    print('screenshot ->', OUT)

    # open a slot picker and verify cross-truck options appear
    page.evaluate("""() => {
        const el = [...document.querySelectorAll('.slot')].find(s => s.textContent.includes('beacon'));
        if (el) el.click();
    }""")
    time.sleep(2.5)
    opts = page.eval_on_selector_all('#pickerList .opt', 'els => els.length')
    print('picker options for beacon:', opts)
    print('picker note:', page.text_content('#pickerNote'))
    page.screenshot(path=OUT.replace('.png', '_picker.png'))

    browser.close()

print('\nconsole errors:', len(errors))
for e in errors[:20]:
    print('   ERR', e)
print('console logs:', len(logs))
for m in logs[:10]:
    print('   LOG', m)