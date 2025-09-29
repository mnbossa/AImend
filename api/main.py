from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

# REQUIRED: top-level ASGI app variable named exactly `app`
app = FastAPI(title="AImend API")

@app.post("/api/chat")
async def chat_endpoint(payload: dict):
    # Example minimal behavior to verify deployment
    q = payload.get("q")
    if not q:
        raise HTTPException(status_code=400, detail="missing q")
    return JSONResponse({"q": q, "answer": "placeholder - deployment OK"})



# import os
# import json
# import sqlite3
# import time
# import asyncio
# from datetime import datetime
# from typing import List

# import httpx
# from bs4 import BeautifulSoup
# from fastapi import FastAPI, HTTPException, BackgroundTasks
# from pydantic import BaseModel

# # Configuration via environment
# SCRAPER_BASE_URL = os.getenv("SCRAPER_BASE_URL", "https://www.europarl.europa.eu/committees/en/agri/documents/latest-documents")
# WORKER_URL = os.getenv("WORKER_URL")  # e.g. https://your-worker.domain
# WORKER_SHARED_SECRET = os.getenv("WORKER_SHARED_SECRET")
# TOP_K_DEFAULT = int(os.getenv("TOP_K_DEFAULT", "5"))
# DB_PATH = os.getenv("DB_PATH", "./agri_docs.db")
# HF_MODEL_DEFAULT = os.getenv("HF_MODEL_DEFAULT", "HuggingFaceTB/SmolLM3-3B:hf-inference")
# CRAWL_LIMIT = int(os.getenv("CRAWL_LIMIT", "200"))

# if not WORKER_URL:
#     print("WORKER_URL not set, set it in Vercel env")

# app = FastAPI(title="AGRI documents search sqlite3")

# # Pydantic models
# class SearchResult(BaseModel):
#     title: str
#     url: str
#     doc_type: str | None = None
#     date: str | None = None
#     excerpt: str | None = None

# class ChatRequest(BaseModel):
#     q: str
#     top_k: int | None = None

# # SQLite helpers
# def ensure_db():
#     conn = sqlite3.connect(DB_PATH)
#     try:
#         cur = conn.cursor()
#         cur.execute("""
#             CREATE TABLE IF NOT EXISTS documents (
#                 id INTEGER PRIMARY KEY,
#                 title TEXT NOT NULL,
#                 url TEXT UNIQUE NOT NULL,
#                 doc_type TEXT,
#                 date TEXT,
#                 excerpt TEXT,
#                 indexed_at INTEGER
#             )
#         """)
#         conn.commit()
#     finally:
#         conn.close()

# def upsert_document(title: str, url: str, doc_type: str | None, date: str | None, excerpt: str | None):
#     conn = sqlite3.connect(DB_PATH)
#     try:
#         cur = conn.cursor()
#         now = int(time.time())
#         cur.execute("""
#             INSERT INTO documents(title,url,doc_type,date,excerpt,indexed_at)
#             VALUES(?,?,?,?,?,?)
#             ON CONFLICT(url) DO UPDATE SET
#               title=excluded.title,
#               doc_type=excluded.doc_type,
#               date=excluded.date,
#               excerpt=excluded.excerpt,
#               indexed_at=excluded.indexed_at
#         """, (title, url, doc_type, date, excerpt, now))
#         conn.commit()
#     finally:
#         conn.close()

# def load_all_documents() -> List[dict]:
#     conn = sqlite3.connect(DB_PATH)
#     conn.row_factory = sqlite3.Row
#     try:
#         cur = conn.cursor()
#         cur.execute("SELECT title,url,doc_type,date,excerpt FROM documents ORDER BY indexed_at DESC")
#         rows = cur.fetchall()
#         return [dict(r) for r in rows]
#     finally:
#         conn.close()

# # --- Scraper and parser
# def parse_listing(html: str) -> List[dict]:
#     soup = BeautifulSoup(html, "html.parser")
#     results = []
#     # Generic heuristics for links
#     for a in soup.select("a"):
#         href = a.get("href")
#         if not href:
#             continue
#         text = a.get_text(strip=True)
#         if not text:
#             continue
#         # accept links to document pages containing '/documents/' or '/_'
#         if "/documents/" in href or "/doceo/" in href or href.endswith(".pdf"):
#             if href.startswith("/"):
#                 url = "https://www.europarl.europa.eu" + href
#             elif href.startswith("http"):
#                 url = href
#             else:
#                 url = SCRAPER_BASE_URL.rstrip("/") + "/" + href
#             results.append({"title": text, "url": url})
#     # dedupe preserving order
#     seen = set()
#     dedup = []
#     for r in results:
#         if r["url"] in seen: continue
#         seen.add(r["url"])
#         dedup.append(r)
#     return dedup

# def extract_detail(html: str) -> dict:
#     soup = BeautifulSoup(html, "html.parser")
#     title_tag = soup.select_one("h1, h2, .ep_title, .documentTitle")
#     title = title_tag.get_text(strip=True) if title_tag else ""
#     date_tag = soup.select_one(".date, .ep_date, time")
#     date = date_tag.get_text(strip=True) if date_tag else ""
#     p = soup.select_one("p, .summary, .ep_summary")
#     excerpt = p.get_text(strip=True) if p else ""
#     dtype = ""
#     dtype_tag = soup.find(string=lambda s: s and ("Opinion" in s or "Report" in s or "Amendment" in s))
#     if dtype_tag:
#         dtype = dtype_tag.strip()
#     return {"title": title, "date": date, "excerpt": excerpt, "doc_type": dtype}

# async def crawl_and_index():
#     ensure_db()
#     async with httpx.AsyncClient(timeout=30) as client:
#         try:
#             listing_resp = await client.get(SCRAPER_BASE_URL)
#             listing_resp.raise_for_status()
#         except Exception as e:
#             print("Error fetching listing", e)
#             return
#         listing = parse_listing(listing_resp.text)
#         for item in listing[:CRAWL_LIMIT]:
#             try:
#                 r = await client.get(item["url"], timeout=20)
#                 if r.status_code != 200:
#                     detail = {"title": item["title"], "date": None, "excerpt": None, "doc_type": None}
#                 else:
#                     detail = extract_detail(r.text)
#                 title = detail.get("title") or item["title"]
#                 upsert_document(title, item["url"], detail.get("doc_type"), detail.get("date"), detail.get("excerpt"))
#             except Exception as e:
#                 print("Error indexing", item.get("url"), e)
#                 continue

# # --- Search and ranking
# def rank_results(rows: List[dict], q: str) -> List[dict]:
#     ql = q.lower()
#     scored = []
#     for r in rows:
#         score = 0
#         title = (r.get("title") or "").lower()
#         excerpt = (r.get("excerpt") or "").lower()
#         if ql in title:
#             score += 100
#         if ql in excerpt:
#             score += 50
#         overlap = sum(1 for t in ql.split() if t and (t in title or t in excerpt))
#         score += overlap * 10
#         scored.append((score, r))
#     scored.sort(key=lambda x: x[0], reverse=True)
#     return [r for s, r in scored if s > 0]

# # --- FastAPI endpoints
# @app.on_event("startup")
# async def startup():
#     ensure_db()

# @app.get("/api/search", response_model=List[SearchResult])
# async def api_search(q: str):
#     if not q:
#         raise HTTPException(status_code=400, detail="q query parameter required")
#     rows = load_all_documents()
#     ranked = rank_results(rows, q)
#     return ranked[:TOP_K_DEFAULT]

# @app.post("/api/reindex")
# async def api_reindex(background_tasks: BackgroundTasks):
#     background_tasks.add_task(crawl_and_index)
#     return {"ok": True, "message": "Reindex scheduled"}

# @app.post("/api/chat")
# async def api_chat(req: ChatRequest):
#     q = req.q.strip()
#     if not q:
#         raise HTTPException(status_code=400, detail="q required")
#     top_k = req.top_k or TOP_K_DEFAULT
#     rows = load_all_documents()
#     candidates = rank_results(rows, q)[:top_k]

#     # Build strict prompt as in earlier scaffold
#     system_instruct = (
#         "You are a search assistant that only uses European Parliament AGRI committee documents provided in the context. "
#         "You must not invent or infer document titles or links. If the supplied candidate list contains relevant documents, "
#         "produce a concise answer that references only those documents by exact title and URL. If none match, reply exactly: "
#         "'I can only search AGRI committee documents; no matching documents found.' Output must be a JSON array of matches: "
#         '[{\"title\":\"...\",\"url\":\"...\",\"snippet\":\"...\",\"matched_terms\":\"...\"}].'
#     )

#     cand_lines = []
#     for i, c in enumerate(candidates, start=1):
#         title = c.get("title") or ""
#         url = c.get("url") or ""
#         excerpt = c.get("excerpt") or ""
#         cand_lines.append(f"{i}) Title: {title}\n   URL: {url}\n   Excerpt: {excerpt}")
#     candidate_block = "\n".join(cand_lines) if cand_lines else "No candidates available."

#     user_block = f"User question: {q}\nTask: Return a JSON array of matching documents from the candidate list only. If no candidate matches, return the single-string refusal above."

#     messages = [
#         {"role": "system", "content": system_instruct},
#         {"role": "system", "content": "Candidate documents (do not alter):\n" + candidate_block},
#         {"role": "user", "content": user_block}
#     ]

#     payload = {"model": HF_MODEL_DEFAULT, "messages": messages, "stream": False}

#     # sign and forward to Worker using WORKER_SHARED_SECRET
#     # Vercel must set WORKER_SHARED_SECRET and WORKER_URL env vars
#     if not WORKER_SHARED_SECRET:
#         raise HTTPException(status_code=500, detail="WORKER_SHARED_SECRET not configured in environment")

#     # Add envelope with timestamp and nonce then compute HMAC
#     envelope = payload.copy()
#     envelope["timestamp"] = int(time.time())
#     # generate short nonce
#     import secrets
#     envelope["nonce"] = secrets.token_hex(8)

#     # Create signature
#     import hmac, hashlib
#     raw = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
#     mac = hmac.new(WORKER_SHARED_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
#     sig = f"sha256={mac}"

#     headers = {"Content-Type": "application/json", "X-Signature": sig}
#     async with httpx.AsyncClient(timeout=30) as client:
#         try:
#             resp = await client.post(f"{WORKER_URL}/chat", content=raw, headers=headers)
#             resp.raise_for_status()
#             data = resp.json()
#             return {"ok": True, "worker": data}
#         except httpx.HTTPStatusError as e:
#             text = e.response.text if e.response else ""
#             raise HTTPException(status_code=502, detail=f"Worker error: {e.response.status_code} {text}")
#         except Exception as e:
#             raise HTTPException(status_code=502, detail=str(e))
