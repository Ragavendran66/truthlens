from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.amazon.in")
    print("Log in to Amazon in the browser, then press Enter here...")
    input()
    context.storage_state(path="amazon_session.json")
    print("Session saved successfully!")
    browser.close()
