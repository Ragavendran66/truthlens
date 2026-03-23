from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor
import asyncio
import time
import os

_executor = ThreadPoolExecutor(max_workers=2)

def _sync_scrape(url: str):
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    if "/dp/" in url:
        asin = url.split("/dp/")[1].split("/")[0].split("?")[0]
    url = f"https://www.amazon.in/product-reviews/{asin}?reviewerType=all_reviews&sortBy=recent&pageNumber=1"

    reviews = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )

        session_file = "amazon_session.json"
        if os.path.exists(session_file):
            context = browser.new_context(
                storage_state=session_file,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="en-IN",
                extra_http_headers={
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
            )
        else:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="en-IN",
                extra_http_headers={
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
            )

        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            page.goto(url, timeout=30000, wait_until="networkidle")
        except:
            pass  # ignore timeout, page might still have content

        time.sleep(1)

        try:
            items = page.query_selector_all('[data-hook="review"]')
            print("REVIEWS FOUND:", len(items))

            for item in items[:10]:
                try:
                    rating_el = item.query_selector('[data-hook="review-star-rating"]')
                    text_el   = item.query_selector('[data-hook="review-body"]')
                    title_el  = item.query_selector('[data-hook="review-title"]')
                    date_el   = item.query_selector('[data-hook="review-date"]')

                    reviews.append({
                        "rating": rating_el.inner_text() if rating_el else "N/A",
                        "title":  title_el.inner_text()  if title_el  else "N/A",
                        "text":   text_el.inner_text()   if text_el   else "N/A",
                        "date":   date_el.inner_text()   if date_el   else "N/A",
                    })
                except:
                    continue
        except Exception as e:
            print("Error reading reviews:", e)

        browser.close()
    return reviews

async def scrape_amazon_reviews(url: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _sync_scrape, url)