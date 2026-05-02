from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from scraper import scrape_amazon_reviews
import httpx, os, json
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

app.add_middleware(CORSMiddleware,
                   allow_origins=["*"],
                   allow_credentials=True,
                   allow_methods=["*"],
                   allow_headers=["*"])

GROQ_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

class AnalyzeRequest(BaseModel):
    url: str = ""
    text: str = ""

@app.get("/")
async def root():
    return FileResponse("review-detector.html")

@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    if not GROQ_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not found")

    if req.url:
        reviews = await scrape_amazon_reviews(req.url)
        text = "\n\n".join([f"{r['rating']} - {r['title']}: {r['text']}" for r in reviews])
        if not text.strip():
            raise HTTPException(status_code=400, detail="No reviews found at that URL. Please make sure it is a valid Amazon product URL.")
    else:
        text = req.text

    if not text.strip():
        raise HTTPException(status_code=400, detail="No text provided")

    prompt = (
            "You are TruthLens, an expert AI that detects fake product reviews. "
            "Analyze these reviews and respond ONLY with raw JSON, no markdown, no backticks:\n\n"
            + text +
            "\n\nRespond in this exact JSON structure:\n"
            "{\n"
            '  "trustScore": <integer 0-100>,\n'
            '  "verdict": "<HIGHLY AUTHENTIC | MOSTLY AUTHENTIC | MIXED SIGNALS | SUSPICIOUS | HIGHLY SUSPICIOUS | FAKE DETECTED>",\n'
            '  "verdictColor": "<safe | warn | danger>",\n'
            '  "shortTitle": "<5-8 word verdict title>",\n'
            '  "shortSummary": "<2-3 sentence plain English verdict>",\n'
            '  "signals": [\n'
            '    {"name": "Sentiment Uniformity", "icon": "S", "score": <0-100>, "description": "<finding>"},\n'
            '    {"name": "Linguistic Diversity", "icon": "L", "score": <0-100>, "description": "<finding>"},\n'
            '    {"name": "sponserd Language", "icon": "I", "score": <0-100>, "description": "<finding>"},\n'
            '    {"name": "Timing Patterns", "icon": "T", "score": <0-100>, "description": "<finding>"},\n'
            '    {"name": "Specificity Level", "icon": "SP", "score": <0-100>, "description": "<finding>"},\n'
            '    {"name": "Emotional Manipulation", "icon": "E", "score": <0-100>, "description": "<finding>"}\n'
            '  ],\n'
            '  "flags": [\n'
            '    {"type": "<flag category>", "severity": "<high|medium|low>", "description": "<finding>"}\n'
            '  ],\n'
            '  "fullSummary": "<3-5 sentence detailed reasoning>"\n'
            "}"
    )

    try:
        async with httpx.AsyncClient() as client:
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
                },
                timeout=60
            )

        data = response.json()

        if "error" in data:
            raise HTTPException(status_code=500, detail="Groq error: " + data["error"]["message"])

        raw = data["choices"][0]["message"]["content"]
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Groq returned invalid JSON")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))