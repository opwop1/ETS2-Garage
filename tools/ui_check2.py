"""Deeper browser probe: click through slots, verify picker and coordinates."""
import json
import sys
import time

from playwright.sync_api import sync_playwright

URL = 'http://127.0.0.1:8765/'
SHOT = r'F:\code\car-share\docs'

errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(args=[
        '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
        '--ignore-gpu-blocklist'])
    page = browser.new_page(viewport={'width': 1600, 'height': 980})
    page.on('console', lambda m: errors.append(f'{m.type}: {m.text}') if m.type == 'error' else None)
    page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
    page.goto(URL, wait_until='networkidle')
    page.wait_for_selector('#app:not(.hidden)', timeout=120000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length > 0",
                           timeout=240000)
    print('stats:', page.text_content('#renderStats'))

    slots = page.eval_on_selector_all('.slot', 'els => els.length')
    print('slot cards:', slots)

    # click the beacon slot card
    clicked = page.evaluate("""() => {
        const cards = [...document.querySelectorAll('.slot')];
        const c = cards.find(x => x.querySelector('.slot-name')?.textContent.trim() === 'beacon');
        if (c) { c.click(); return c.querySelector('.slot-name').textContent; }
        return null;
    }""")
    print('clicked slot:', clicked)
    page.wait_for_selector('.modal:not(.hidden)', timeout=15000)
    page.wait_for_function("() => document.querySelectorAll('#pickerList .opt').length > 1", timeout=120000)
    n = page.eval_on_selector_all('#pickerList .opt', 'e => e.length')
    print('picker options:', n)
    print('picker note:', (page.text_content('#pickerNote') or '').strip())
    page.screenshot(path=SHOT + r'\screenshot_picker.png')

    # pick the first real accessory (skip the "remove" card)
    page.evaluate("() => document.querySelectorAll('#pickerList .opt')[1].click()")
    page.wait_for_timeout(4000)
    page.wait_for_function("() => document.getElementById('renderStats').textContent.length > 0",
                           timeout=120000)
    print('after pick, stats:', page.text_content('#renderStats'))
    rows = page.eval_on_selector_all('#coordTable tbody tr',
                                     'els => els.map(e => Array.from(e.children).map(c => c.textContent))')
    print('coordinate rows:', len(rows))
    for r in rows:
        print('   ', r)
    page.screenshot(path=SHOT + r'\screenshot.png')

    # count accessories present in the scene
    bbox = page.evaluate("""() => {
        const T = window.__ets2.THREE;
        const b = new T.Box3().setFromObject(window.__ets2.truckRoot);
        const s = b.getSize(new T.Vector3()), c = b.getCenter(new T.Vector3());
        return {size:[s.x,s.y,s.z], center:[c.x,c.y,c.z],
                children: window.__ets2.truckRoot.children.length,
                locators: window.__ets2.locatorRoot.children.length};
    }""")
    print('bbox:', json.dumps(bbox))
    browser.close()

print('errors:', len(errors))
for e in errors[:15]:
    print('  ', e)