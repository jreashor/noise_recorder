#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)
    page = browser.new_page()
    print("Dashboard loaded:", page.title())
    time.sleep(1)
    html = page.content()
    print(html[:800])
    browser.close()
