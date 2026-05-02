from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from scraper import scrape_amazon_reviews
import httpx, os, json, re
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

GROQ_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class AnalyzeRequest(BaseModel):
    url: str = ""
    text: str = ""


# ── Health check — keeps Render from spinning down ────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return FileResponse("review-detector.html")


# ── Helper: extract clean JSON from LLM response ─────────────────────────────
def extract_json(raw: str) -> dict:
    # Strip markdown code fences if present
    clean = raw.replace("```json", "").replace("```", "").strip()

    # Try direct parse first
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # Fallback: find first { ... } block in case of extra text around JSON
    match = re.search(r'\{.*\}', clean, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError("Could not parse valid JSON from model response")


# ── Main analyze endpoint ─────────────────────────────────────────────────────
@app.post("/analyze")
async def analyze(req: AnalyzeRequest):

    # ── Guard: API key ──
    if not GROQ_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured on server.")

    text = ""

    # ── URL mode: scrape reviews ──
    if req.url.strip():
        try:
            reviews = await scrape_amazon_reviews(req.url.strip())
        except ValueError as e:
            # Bad URL / no ASIN
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Scraping failed: {str(e)}. Try pasting reviews manually."
            )

        if not reviews:
            raise HTTPException(
                status_code=404,
                detail="No reviews found at that URL. The page may require login or the product has no reviews. Try pasting them manually."
            )

        text = "\n\n".join(
            f"{r['rating']} - {r['title']}: {r['text']}"
            for r in reviews
        )

    # ── Text mode ──
    elif req.text.strip():
        text = req.text.strip()

    else:
        raise HTTPException(status_code=422, detail="Provide either a URL or review text.")

    # ── Build prompt ──
    prompt = (
            "You are TruthLens, an expert AI that detects fake product reviews. "
            "Analyze these reviews and respond ONLY with raw JSON — no markdown, no backticks, no extra text.\n\n"
            + text +
            "\n\nRespond in this EXACT JSON structure:\n"
            "{\n"
            '  "trustScore": <integer 0-100, where 100 = fully authentic>,\n'
            '  "verdict": "<HIGHLY AUTHENTIC | MOSTLY AUTHENTIC | MIXED SIGNALS | SUSPICIOUS | HIGHLY SUSPICIOUS | FAKE DETECTED>",\n'
            '  "verdictColor": "<safe | warn | danger>",\n'
            '  "shortTitle": "<5-8 word verdict title>",\n'
            '  "shortSummary": "<2-3 sentence plain English verdict>",\n'
            '  "signals": [\n'
            '    {"name": "Sentiment Uniformity",    "icon": "😐", "score": <0-100>, "description": "<finding>"},\n'
            '    {"name": "Linguistic Diversity",    "icon": "📝", "score": <0-100>, "description": "<finding>"},\n'
            '    {"name": "Sponsored Language",      "icon": "💰", "score": <0-100>, "description": "<finding>"},\n'
            '    {"name": "Timing Patterns",         "icon": "⏱️", "score": <0-100>, "description": "<finding>"},\n'
            '    {"name": "Specificity Level",       "icon": "🔍", "score": <0-100>, "description": "<finding>"},\n'
            '    {"name": "Emotional Manipulation",  "icon": "🎭", "score": <0-100>, "description": "<finding>"}\n'
            '  ],\n'
            '  "flags": [\n'
            '    {"type": "<flag category>", "severity": "<high|medium|low>", "description": "<finding>"}\n'
            '  ],\n'
            '  "fullSummary": "<3-5 sentence detailed reasoning>"\n'
            "}\n\n"
            "IMPORTANT: A higher signal score means MORE suspicious/fake. "
            "trustScore is the opposite — higher means MORE trustworthy."
    )

    # ── Call Groq ──
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2000
                }
            )

        data = response.json()

        # ── Groq API-level error ──
        if "error" in data:
            raise HTTPException(
                status_code=502,
                detail="Groq API error: " + data["error"].get("message", "Unknown error")
            )

        raw = data["choices"][0]["message"]["content"]

        # ── Parse JSON from model output ──
        try:
            result = extract_json(raw)
        except ValueError:
            raise HTTPException(
                status_code=500,
                detail="Model returned malformed JSON. Try again."
            )

        return result

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Request to Groq timed out. Try again in a moment."
        )
    except HTTPException:
        raise  # re-raise our own HTTP exceptions untouched
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")