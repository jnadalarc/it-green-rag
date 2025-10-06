# API + UI. Flux: UI -> /chat -> (MCP tools) -> compose prompt -> llama.cpp -> resposta
from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
import os, json, re
import requests
import sqlite3
from pathlib import Path

LLAMA_URL = os.getenv("LLAMA_URL", "http://localhost:8080")
DOCS_DIR = Path(os.getenv("DOCS_DIR", "./docs")).resolve()
RAG_DB_PATH = Path(os.getenv("RAG_DB_PATH", "./rag.db")).resolve()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

tpl = Environment(loader=FileSystemLoader("templates"), autoescape=True)

# --- RAG bàsic: SQLite FTS5 -------------------------------------------------
# Crea DB FTS i indexa fitxers .txt, .md, .pdf (només text pre-extractat)
def rag_init():
    conn = sqlite3.connect(RAG_DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(path, content)")
    conn.commit(); conn.close()

rag_init()

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150

def chunk_text(text):
    out = []
    i = 0
    n = len(text)
    while i < n:
        out.append(text[i:i+CHUNK_SIZE])
        i += CHUNK_SIZE - CHUNK_OVERLAP
    return out

def rag_ingest(path: Path):
    if not path.exists():
        return 0
    conn = sqlite3.connect(RAG_DB_PATH)
    cur = conn.cursor()
    count = 0
    for p in path.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".txt",".md",".log"}:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for ch in chunk_text(text):
                cur.execute("INSERT INTO docs(path, content) VALUES(?, ?)", (str(p), ch))
                count += 1
    conn.commit(); conn.close()
    return count

# Ingest on start
rag_ingest(DOCS_DIR)

def rag_search(query: str, k: int = 5):
    conn = sqlite3.connect(RAG_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT path, content FROM docs WHERE docs MATCH ? LIMIT ?", (query, k))
    rows = cur.fetchall()
    conn.close()
    return rows

# --- MCP tools: filesystem.read i fetch.get ---------------------------------
# filesystem.read: llegeix arxius sota DOCS_DIR

def mcp_filesystem_read(rel_path: str, max_bytes: int = 200_000):
    p = (DOCS_DIR / rel_path).resolve()
    if not str(p).startswith(str(DOCS_DIR)):
        return {"error": "path outside DOCS_DIR"}
    if not p.exists() or not p.is_file():
        return {"error": "not found"}
    data = p.read_text(encoding="utf-8", errors="ignore")
    return {"path": str(p), "content": data[:max_bytes]}

# fetch.get: HTTP GET controlat (només hosts locals o inhabilitat per defecte)
ALLOWED_FETCH_HOSTS = {"localhost", "127.0.0.1"}

def mcp_fetch_get(url: str, timeout=5):
    try:
        host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0]
        if host not in ALLOWED_FETCH_HOSTS:
            return {"error": "host not allowed"}
        r = requests.get(url, timeout=timeout)
        return {"status": r.status_code, "text": r.text[:200000]}
    except Exception as e:
        return {"error": str(e)}

# --- LLM chat ---------------------------------------------------------------

def llama_chat(messages, temperature=0.7, max_tokens=512):
    # llama.cpp server accepts OpenAI-like payload at /v1/chat/completions
    payload = {
        "model": "local",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    url = f"{LLAMA_URL}/v1/chat/completions"
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]

SYSTEM_PROMPT = (
    "You are a concise assistant. If the user asks for document-based answers, you may call RAG to retrieve snippets."
)

# --- UI ---------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    html = tpl.get_template("index.html").render()
    return HTMLResponse(html)

@app.post("/upload")
async def upload(file: UploadFile):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOCS_DIR / file.filename
    data = await file.read()
    dest.write_bytes(data)
    # re-ingesta
    rag_ingest(DOCS_DIR)
    return JSONResponse({"ok": True, "filename": file.filename})

@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    user_msg = body.get("message", "")
    use_rag = body.get("use_rag", True)

    context = []
    # patró simple per crides MCP manuals
    m = re.match(r"filesystem.read:(.*)", user_msg)
    if m:
        res = mcp_filesystem_read(m.group(1).strip())
        return JSONResponse(res)
    m = re.match(r"fetch.get:(.*)", user_msg)
    if m:
        res = mcp_fetch_get(m.group(1).strip())
        return JSONResponse(res)

    if use_rag and len(user_msg) >= 8:
        hits = rag_search(user_msg, k=4)
        if hits:
            context.append("RAG_SNIPPETS:\n" + "\n---\n".join([f"{p}\n{c}" for p,c in hits]))

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": ("\n\n".join(context+[user_msg]))}
    ]
    answer = llama_chat(messages)
    return JSONResponse({"answer": answer})