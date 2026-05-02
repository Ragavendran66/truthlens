from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor
import asyncio
import time
import os

_executor = ThreadPoolExecutor(max_workers=2)

def _extract_asin(url: str):
    """Extract ASIN from Amazon URL."""
    if "/dp/" in url:
        return url.split("/dp/")[1].split("/")[0].split("?")[0]
    if "/product-reviews/" in url:
        return url.split("/product-reviews/")[1].split("/")[0].split("?")[0]
    # Try to find B0... style ASIN anywhere in URL
    import re
    match = re.search(r'/(B[0-9A-Z]{9})(?:/|$|\?)', url)
    if match:
        return match.group(1)
    return None

def _sync_scrape(url: str):
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    # --- FIX 1: Extract ASIN safely before using it ---
    asin = _extract_asin(url)
    if not asin:
        raise ValueError(f"Could not extract ASIN from URL: {url}")

    reviews_url = (
        f"https://www.amazon.in/product-reviews/{asin}"
        f"?reviewerType=all_reviews&sortBy=recent&pageNumber=1"
    )

    reviews = []

    with sync_playwright() as p:
        # --- FIX 2: headless=True — required on Render (no display available) ---
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",        # important on Render
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context_args = dict(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-IN",
            extra_http_headers={
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

        session_file = "amazon_session.json"
        if os.path.exists(session_file):
            context_args["storage_state"] = session_file

        context = browser.new_context(**context_args)
        page = context.new_page()

        # Hide webdriver fingerprint
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        try:
            # --- FIX 3: use domcontentloaded — networkidle hangs on Amazon ---
            page.goto(reviews_url, timeout=30000, wait_until="domcontentloaded")
            # Small wait for review elements to render
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Page load warning (continuing anyway): {e}")

        try:
            items = page.query_selector_all('[data-hook="review"]')
            print(f"REVIEWS FOUND: {len(items)}")

            for item in items[:10]:
                try:
                    rating_el = item.query_selector('[data-hook="review-star-rating"]')
                    text_el   = item.query_selector('[data-hook="review-body"]')
                    title_el  = item.query_selector('[data-hook="review-title"]')
                    date_el   = item.query_selector('[data-hook="review-date"]')

                    reviews.append({
                        "rating": rating_el.inner_text().strip() if rating_el else "N/A",
                        "title":  title_el.inner_text().strip()  if title_el  else "N/A",
                        "text":   text_el.inner_text().strip()   if text_el   else "N/A",
                        "date":   date_el.inner_text().strip()   if date_el   else "N/A",
                    })
                except Exception as e:
                    print(f"Error parsing review item: {e}")
                    continue

        except Exception as e:
            print(f"Error reading reviews: {e}")

        finally:
            browser.close()

    return reviews


async def scrape_amazon_reviews(url: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _sync_scrape, url)