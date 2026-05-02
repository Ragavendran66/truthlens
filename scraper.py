import httpx
import re
import asyncio
import random
import os
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")

def extract_asin(url: str):
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/product-reviews/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'/(B[0-9A-Z]{9})(?:/|\?|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

async def scrape_amazon_reviews(url: str) -> list[dict]:
    if not SCRAPER_API_KEY:
        raise ValueError("SCRAPER_API_KEY not configured on server.")

    if not url.startswith("http"):
        url = "https://" + url

    url = url.replace("amazon.com", "amazon.in")

    asin = extract_asin(url)
    if not asin:
        raise ValueError("Could not extract ASIN. Make sure it's a valid Amazon product link.")

    target_url = (
        f"https://www.amazon.in/product-reviews/{asin}"
        f"?reviewerType=all_reviews&sortBy=recent&pageNumber=1"
    )

    scraper_url = (
        f"http://api.scraperapi.com"
        f"?api_key={SCRAPER_API_KEY}"
        f"&url={target_url}"
        f"&render=false"
        f"&country_code=in"
    )

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(scraper_url)

        if response.status_code != 200:
            raise ValueError(
                f"Could not fetch reviews (status {response.status_code}). "
                "Please paste reviews manually."
            )

        html = response.text

        if "Enter the characters you see below" in html or \
                "api-services-support@amazon.com" in html:
            raise ValueError("Amazon is showing a CAPTCHA. Please paste reviews manually.")

        soup = BeautifulSoup(html, "html.parser")
        items = soup.select('[data-hook="review"]')

        if not items:
            raise ValueError(
                "No reviews found. The product may have no reviews or "
                "requires sign-in. Please paste reviews manually."
            )

        reviews = []
        for item in items[:10]:
            rating_el = item.select_one('[data-hook="review-star-rating"]')
            title_el  = item.select_one('[data-hook="review-title"]')
            text_el   = item.select_one('[data-hook="review-body"]')
            date_el   = item.select_one('[data-hook="review-date"]')

            text = text_el.get_text(strip=True) if text_el else ""
            if not text:
                continue

            reviews.append({
                "rating": rating_el.get_text(strip=True) if rating_el else "N/A",
                "title":  title_el.get_text(strip=True)  if title_el  else "N/A",
                "text":   text,
                "date":   date_el.get_text(strip=True)   if date_el   else "N/A",
            })

        if not reviews:
            raise ValueError("Reviews found but all were empty. Please paste reviews manually.")

        return reviews

    except ValueError:
        raise
    except httpx.TimeoutException:
        raise ValueError("Request timed out. Please paste reviews manually.")
    except Exception as e:
        raise ValueError(f"Scraping error: {str(e)}. Please paste reviews manually.")