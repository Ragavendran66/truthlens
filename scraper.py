import httpx
import asyncio
import re
from bs4 import BeautifulSoup
import random

# Rotate user agents to avoid detection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

def get_headers(asin: str) -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Referer": f"https://www.amazon.in/dp/{asin}",
    }

def extract_asin(url: str):
    """Extract ASIN from any Amazon URL format."""
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/product-reviews/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'/gp/aw/d/([A-Z0-9]{10})',
        r'/(B[0-9A-Z]{9})(?:/|\?|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

async def scrape_amazon_reviews(url: str) -> list[dict]:
    if not url.startswith("http"):
        url = "https://" + url

    # Force amazon.in
    url = url.replace("amazon.com", "amazon.in")

    asin = extract_asin(url)
    if not asin:
        raise ValueError(f"Could not extract ASIN from URL. Make sure it's a valid Amazon product link.")

    # Try multiple URL formats — Amazon sometimes 404s one but not another
    urls_to_try = [
        f"https://www.amazon.in/product-reviews/{asin}?reviewerType=all_reviews&sortBy=recent&pageNumber=1",
        f"https://www.amazon.in/product-reviews/{asin}?reviewerType=all_reviews",
        f"https://www.amazon.in/-/en/product-reviews/{asin}?reviewerType=all_reviews",
    ]

    last_error = None

    for reviews_url in urls_to_try:
        try:
            async with httpx.AsyncClient(
                    headers=get_headers(asin),
                    follow_redirects=True,
                    timeout=25,
                    http2=True,        # use HTTP/2 — more like a real browser
            ) as client:
                # First visit the product page to set cookies (looks more human)
                try:
                    await client.get(
                        f"https://www.amazon.in/dp/{asin}",
                        timeout=10
                    )
                except Exception:
                    pass  # if product page fails, still try reviews page

                await asyncio.sleep(random.uniform(0.5, 1.5))  # human-like delay

                response = await client.get(reviews_url)

            html = response.text

            # ── Detect blocks ──────────────────────────────────────────────
            if response.status_code == 404:
                last_error = "404"
                continue  # try next URL format

            if response.status_code == 503:
                raise ValueError("Amazon is temporarily blocking requests. Please paste reviews manually.")

            if response.status_code != 200:
                last_error = f"status_{response.status_code}"
                continue

            if "api-services-support@amazon.com" in html or \
                    "Enter the characters you see below" in html or \
                    "Type the characters you see in this image" in html:
                raise ValueError("Amazon is showing a CAPTCHA. Please paste reviews manually.")

            if "blocked" in html.lower() and "review" not in html.lower():
                raise ValueError("Amazon blocked this request. Please paste reviews manually.")

            # ── Parse reviews ──────────────────────────────────────────────
            soup = BeautifulSoup(html, "html.parser")
            items = soup.select('[data-hook="review"]')

            if not items:
                # Check if page loaded but has no reviews
                if "review" in html.lower():
                    raise ValueError(
                        "This product has no reviews yet, or Amazon requires "
                        "sign-in to view them. Please paste reviews manually."
                    )
                last_error = "no_items"
                continue  # try next URL

            reviews = []
            for item in items[:10]:
                rating_el = item.select_one('[data-hook="review-star-rating"]')
                title_el  = item.select_one('[data-hook="review-title"]')
                text_el   = item.select_one('[data-hook="review-body"]')
                date_el   = item.select_one('[data-hook="review-date"]')

                text = text_el.get_text(strip=True) if text_el else ""
                if not text:
                    continue  # skip empty reviews

                reviews.append({
                    "rating": rating_el.get_text(strip=True) if rating_el else "N/A",
                    "title":  title_el.get_text(strip=True)  if title_el  else "N/A",
                    "text":   text,
                    "date":   date_el.get_text(strip=True)   if date_el   else "N/A",
                })

            if reviews:
                return reviews

            last_error = "empty_reviews"
            continue

        except ValueError:
            raise  # re-raise our clean user-facing errors
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            raise ValueError(f"Network error: {str(e)}. Please paste reviews manually.")
        except Exception as e:
            last_error = str(e)
            continue

    # All URLs failed
    error_messages = {
        "404": (
            "Amazon returned 404 for all URL formats. "
            "This usually means Amazon is blocking server requests. "
            "Please paste the reviews manually — copy them from the Amazon page and paste in the text tab."
        ),
        "no_items": (
            "Page loaded but no reviews were found. "
            "Amazon may require sign-in or the product has no reviews. "
            "Please paste reviews manually."
        ),
        "empty_reviews": (
            "Reviews were found but all had empty text. "
            "Please paste reviews manually."
        ),
    }

    msg = error_messages.get(last_error, f"Could not load reviews ({last_error}). Please paste reviews manually.")
    raise ValueError(msg)