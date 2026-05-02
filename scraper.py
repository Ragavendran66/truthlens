import httpx
import asyncio
import re
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

def extract_asin(url: str) -> str | None:
    if "/dp/" in url:
        return url.split("/dp/")[1].split("/")[0].split("?")[0]
    if "/product-reviews/" in url:
        return url.split("/product-reviews/")[1].split("/")[0].split("?")[0]
    match = re.search(r'/(B[0-9A-Z]{9})(?:/|$|\?)', url)
    if match:
        return match.group(1)
    return None

async def scrape_amazon_reviews(url: str) -> list[dict]:
    if not url.startswith("http"):
        url = "https://" + url

    asin = extract_asin(url)
    if not asin:
        raise ValueError(f"Could not extract ASIN from URL: {url}")

    reviews_url = (
        f"https://www.amazon.in/product-reviews/{asin}"
        f"?reviewerType=all_reviews&sortBy=recent&pageNumber=1"
    )

    try:
        async with httpx.AsyncClient(
                headers=HEADERS,
                follow_redirects=True,
                timeout=20
        ) as client:
            response = await client.get(reviews_url)

        if response.status_code != 200:
            raise ValueError(f"Amazon returned status {response.status_code}. Try pasting reviews manually.")

        soup = BeautifulSoup(response.text, "html.parser")

        # Check if Amazon blocked us (shows captcha or sign-in page)
        if "Enter the characters you see below" in response.text or \
                "Type the characters you see in this image" in response.text:
            raise ValueError("Amazon is showing a CAPTCHA. Please paste reviews manually.")

        if "Sign in" in response.text and "review" not in response.text.lower():
            raise ValueError("Amazon requires sign-in for this page. Please paste reviews manually.")

        items = soup.select('[data-hook="review"]')

        if not items:
            raise ValueError("No reviews found. The product may have no reviews or Amazon blocked the request. Try pasting reviews manually.")

        reviews = []
        for item in items[:10]:
            rating_el = item.select_one('[data-hook="review-star-rating"]')
            title_el  = item.select_one('[data-hook="review-title"]')
            text_el   = item.select_one('[data-hook="review-body"]')
            date_el   = item.select_one('[data-hook="review-date"]')

            reviews.append({
                "rating": rating_el.get_text(strip=True) if rating_el else "N/A",
                "title":  title_el.get_text(strip=True)  if title_el  else "N/A",
                "text":   text_el.get_text(strip=True)   if text_el   else "N/A",
                "date":   date_el.get_text(strip=True)   if date_el   else "N/A",
            })

        return reviews

    except (httpx.TimeoutException, httpx.ConnectError) as e:
        raise ValueError(f"Network error reaching Amazon: {str(e)}")