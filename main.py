import os
import json
import asyncio
from typing import List
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
import sqlalchemy
from databases import Database

# --- Configuration (via Vercel env vars)
SCRAPER_BASE_URL = os.getenv("SCRAPER_BASE_URL", "https://www.europarl.europa.eu/committees/en/agri/documents/latest-documents")
WORKER_URL = os.getenv("WORKER_URL")  # e.g., https://wild-dream-a536.mnbossa.workers.dev
WORKER_SHARED_SECRET = os.getenv("WORKER_SHARED_SECRET")  # shared secret between Vercel and Worker
TOP_K_DEFAULT = int(os.getenv("TOP_K_DEFAULT", "5"))
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./agri_docs.db")

if not WORKER_URL or not WORKER_SHARED_SECRET:
    # do not expose secrets; fail-fast in logs at deploy-time
    print("WORKER_URL and WORKER_SHARED_SECRET must be set as environment variables")

# --- Database setup
metadata = sqlalchemy.MetaData()
documents = sqlalchemy.Table(
    "documents",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("title", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("url", sqlalchemy.String, unique=True, nullable=False),
    sqlalchemy.Column("doc_type", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("date", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("excerpt", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("indexed_at", sqlalchemy.String, nullable=True)
)

engine = sqlalchemy.create_engine(DB_URL, connect_args={"check_same_thread": False} if "sqlite" in DB_URL else {})
metadata.create_all(engine)
database = Database(DB_URL)

app = FastAPI(title="AGRI documents search")

# --- Pydantic models
class SearchResult(BaseModel):
    title: str
    url: str
    doc_type: str | None = None
    date: str | None = None
    excerpt: str | None = None

class ChatRequest(BaseModel):
    q: str
    top_k: int | None = None

# --- Simple scraper (synchronous helper wrapped async)
def _parse_listing(html: str) -> List[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    # The Europarl listing pages use .doc and other selectors; using robust heuristics
    for item in soup.select(".searchResult, .ep_doc, li a, td a"):
        a = item if item.name == "a" else item.find("a")
        if not a or not a.get("href"):
            continue
        title = a.get_text(strip=True)
        href = a["href"]
        # normalize absolute URL
        if href.startswith("/"):
            url = "https://www.europarl.europa.eu" + href
        elif href.startswith("http"):
            url = href
        else:
            url = SRC_URL.rstrip("/") + "/" + href
        results.append({"title": title, "url": url})
    # fallback: parse explicit table rows
    # deduplicate while preserving order
    seen = set()
    dedup = []
    for r in results:
        if r["url"] in seen: 
            continue
        seen.add(r["url"])
        dedup.append(r)
    return dedup

def _extract_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    # heuristics for title, date, excerpt
    title_tag = soup.select_one("h1, h2, .ep_title, .documentTitle")
    title = title_tag.get_text(strip=True) if title_tag else ""
    date_tag = soup.select_one(".date, .ep_date, time")
    date = date_tag.get_text(strip=True) if date_tag else ""
    # excerpt: first paragraph under content
    p = soup.select_one("p, .summary, .ep_summary")
    excerpt = p.get_text(strip=True) if p else ""
    # doc_type heuristics
    dtype = ""
    dtype_tag = soup.find(string=lambda s: s and ("Opinion" in s or "Report" in s or "Amendment" in s))
    if dtype_tag:
        dtype = dtype_tag.strip()
    return {"title": title, "date": date, "excerpt": excerpt, "doc_type": dtype}

async def crawl_and_index():
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(SCRAPER_BASE_URL)
            resp.raise_for_status()
        except Exception as e:
            print("Error fetching listing:", e)
            return
        listing = _parse_listing(resp.text)
        now = datetime.utcnow().isoformat()
        # store or update entries
        for item in listing[:200]:  # limit to first 200 links for safety
            try:
                r = await client.get(item["url"], timeout=20)
                if r.status_code != 200:
                    # store minimal info but continue
                    detail = {"title": item["title"], "date": None, "excerpt": None, "doc_type": None}
                else:
                    detail = _extract_detail(r.text)
                query = documents.select().where(documents.c.url == item["url"])
                existing = await database.fetch_one(query)
                if existing:
                    update = documents.update().where(documents.c.url == item["url"]).values(
                        title = detail["title"] or item["title"],
                        date = detail.get("date"),
                        excerpt = detail.get("excerpt"),
                        doc_type = detail.get("doc_type"),
                        indexed_at = now
                    )
                    await database.execute(update)
                else:
                    insert = documents.insert().values(
                        title = detail["title"] or item["title"],
                        url = item["url"],
                        doc_type = detail.get("doc_type"),
                        date = detail.get("date"),
                        excerpt = detail.get("excerpt"),
                        indexed_at = now
                    )
                    await database.execute(insert)
            except Exception as e:
                print("Error indexing", item["url"], e)
                continue

# --- Utility: simple high-precision search
def rank_results(rows: List[dict], q: str) -> List[dict]:
    ql = q.lower()
    scored = []
    for r in rows:
        score = 0
        title = (r["title"] or "").lower()
        excerpt = (r.get("excerpt") or "").lower()
        if ql in title:
            score += 100
        if ql in excerpt:
            score += 50
        # token overlap
        tokens = ql.split()
        overlap = sum(1 for t in tokens if t and (t in title or t in excerpt))
        score += overlap * 10
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for s,r in scored if s>0]

# --- Startup / shutdown
@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# --- Endpoints
@app.get("/api/search", response_model=List[SearchResult])
async def api_search(q: str):
    if not q:
        raise HTTPException(status_code=400, detail="q query parameter required")
    query = documents.select()
    rows = await database.fetch_all(query)
    rows = [dict(r) for r in rows]
    ranked = rank_results(rows, q)
    top = ranked[:TOP_K_DEFAULT]
    return top

@app.post("/api/reindex")
async def api_reindex(background_tasks: BackgroundTasks):
    # background trigger for crawl; secured endpoint recommended
    background_tasks.add_task(crawl_and_index)
    return {"ok": True, "message": "Reindex scheduled"}

@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    q = req.q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="q required")
    top_k = req.top_k or TOP_K_DEFAULT
    # search
    query = documents.select()
    rows = await database.fetch_all(query)
    rows = [dict(r) for r in rows]
    candidates = rank_results(rows, q)[:top_k]
    # Build strict prompt
    system_instruct = (
        "You are a search assistant that only uses European Parliament AGRI committee documents provided in the context. "
        "You must not invent or infer document titles or links. If the supplied candidate list contains relevant documents, "
        "produce a concise answer that references only those documents by exact title and URL. If none match, reply exactly: "
        "'I can only search AGRI committee documents; no matching documents found.' Output must be a JSON array of matches: "
        '[{\"title\":\"...\",\"url\":\"...\",\"snippet\":\"...\",\"matched_terms\":\"...\"}].'
    )
    # Candidates block (exact authoritative text)
    cand_lines = []
    for i, c in enumerate(candidates, start=1):
        title = c.get("title") or ""
        url = c.get("url") or ""
        excerpt = c.get("excerpt") or ""
        cand_lines.append(f"{i}) Title: {title}\n   URL: {url}\n   Excerpt: {excerpt}")
    candidate_block = "\n".join(cand_lines) if cand_lines else "No candidates available."

    user_block = f"User question: {q}\nTask: Return a JSON array of matching documents from the candidate list only. If no candidate matches, return the single-string refusal above."

    messages = [
        {"role": "system", "content": system_instruct},
        {"role": "system", "content": "Candidate documents (do not alter):\n" + candidate_block},
        {"role": "user", "content": user_block}
    ]

    # Forward to Cloudflare Worker which holds HF secret
    payload = {"model": "HuggingFaceTB/SmolLM3-3B:hf-inference", "messages": messages, "stream": False}
    headers = {"Content-Type": "application/json", "X-Worker-Shared-Secret": WORKER_SHARED_SECRET}
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(f"{WORKER_URL}/chat", json=payload, headers=headers)
            resp.raise_for_status()
            # Worker returns JSON with { reply: "..." } or model structured output
            data = resp.json()
            return {"ok": True, "worker": data}
        except httpx.HTTPStatusError as e:
            text = e.response.text if e.response else ""
            raise HTTPException(status_code=502, detail=f"Worker error: {e.response.status_code} {text}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))
