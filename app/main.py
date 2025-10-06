import chainlit as cl
import os
import requests
import sqlite3
from pathlib import Path

# ... (tota la part superior del fitxer es queda igual) ...
LLAMA_URL = os.getenv("LLAMA_URL", "http://localhost:8080")
DOCS_DIR = Path(os.getenv("DOCS_DIR", "/docs")).resolve()
RAG_DB_PATH = Path(os.getenv("RAG_DB_PATH", "/rag/rag.db")).resolve()

SYSTEM_PROMPT = (
    "You are a concise assistant. If the user asks for document-based answers, you may call RAG to retrieve snippets."
)

def rag_init():
    """Inicialitza la base de dades FTS5 si no existeix."""
    RAG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(RAG_DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(path, content)")
    conn.commit()
    conn.close()

def chunk_text(text):
    """Divideix el text en fragments (chunks)."""
    CHUNK_SIZE = 1200
    CHUNK_OVERLAP = 150
    return [text[i:i+CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE - CHUNK_OVERLAP)]

def rag_ingest(path: Path):
    """Indexa els fitxers de text d'un directori a la base de dades RAG."""
    print("=============================================")
    print(f"🚀 Iniciant procés d'indexació des de: {path}")
    
    if not path.exists():
        print(f"⚠️  Advertència: El directori de documents no existeix. S'omet la indexació.")
        print("=============================================")
        return 0
        
    conn = sqlite3.connect(RAG_DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM docs")
    
    total_chunks = 0
    files_processed = 0
    
    files_to_process = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in {".txt", ".md", ".log"}]
    print(f"ℹ️  S'han trobat {len(files_to_process)} fitxers per processar.")

    for p in files_to_process:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            for ch in chunk_text(text):
                cur.execute("INSERT INTO docs(path, content) VALUES(?, ?)", (str(p.name), ch))
                total_chunks += 1
            
            files_processed += 1
            
            if files_processed % 10 == 0:
                print(f"  -> Processats {files_processed} de {len(files_to_process)} fitxers...")

        except Exception as e:
            print(f"❌ Error processant {p}: {e}")
            
    conn.commit()
    conn.close()
    
    print(f"✅ Indexació finalitzada!")
    print(f"   - Fitxers processats: {files_processed}")
    print(f"   - Fragments creats: {total_chunks}")
    print("=============================================")
    
    return total_chunks

def rag_search(query: str, k: int = 5):
    """Busca a la base de dades RAG."""
    conn = sqlite3.connect(RAG_DB_PATH)
    cur = conn.cursor()
    
    # ---- LÍNIA MODIFICADA ----
    # Embolcallem la consulta amb cometes dobles per tractar-la com una frase literal
    safe_query = f'"{query}"'
    # --------------------------
    
    cur.execute("SELECT path, content FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?", (safe_query, k))
    rows = cur.fetchall()
    conn.close()
    return rows

def llama_chat(messages, temperature=0.7, max_tokens=512):
    """Envia una petició al servidor de Llama.cpp."""
    payload = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    url = f"{LLAMA_URL}/v1/chat/completions"
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# --- LÒGICA D'ARRENCADA MODIFICADA ---
print("Iniciant el servidor Chainlit...")
rag_init()

db_size = RAG_DB_PATH.stat().st_size if RAG_DB_PATH.exists() else 0
if db_size == 0:
    print("La base de dades RAG està buida. S'inicia la indexació inicial.")
    rag_ingest(DOCS_DIR)
else:
    print("La base de dades RAG ja existeix. S'omet la indexació inicial.")

# --- Interfície de Xat amb Chainlit ---


@cl.on_chat_start
async def start():
    """Lògica que s'executa quan un usuari inicia un xat."""
    await cl.Avatar(
        name="Assistent",
        url="/public/logo.png",
    ).send()

    await cl.Message(content="Hola! Soc el teu assistent de RAG. El sistema ja està llest. Per re-indexar els documents, escriu `REINDEX_RAG`.").send()
@cl.on_message
async def main(message: cl.Message):
    query = message.content

    if query.upper() == "REINDEX_RAG":
        await cl.Message(content="Rebut! Iniciant la re-indexació dels documents. Això pot trigar una estona...").send()
        count = rag_ingest(DOCS_DIR)
        await cl.Message(content=f"Re-indexació finalitzada! S'han processat {count} fragments.").send()
        return

    hits = rag_search(query, k=4)
    context = ""
    if hits:
        context = "RAG_SNIPPETS:\n" + "\n---\n".join([f"Document: {p}\nContent: {c}" for p, c in hits])

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (context + "\n\n" + query)}
    ]

    answer = llama_chat(messages)
    await cl.Message(content=answer).send()