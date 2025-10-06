import chainlit as cl
import os
import requests
import sqlite3
from pathlib import Path

# --- Configuració i Lògica de Backend (la mateixa que tenies) ---

LLAMA_URL = os.getenv("LLAMA_URL", "http://localhost:8080")
# Les rutes ara apunten als volums muntats al contenidor
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

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150

def chunk_text(text):
    """Divideix el text en fragments (chunks)."""
    return [text[i:i+CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE - CHUNK_OVERLAP)]

def rag_ingest(path: Path):
    """Indexa els fitxers de text d'un directori a la base de dades RAG."""
    if not path.exists():
        return 0
    conn = sqlite3.connect(RAG_DB_PATH)
    cur = conn.cursor()
    # Esborrem el contingut anterior per re-indexar tot
    cur.execute("DELETE FROM docs")
    count = 0
    for p in path.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".txt", ".md", ".log"}:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                for ch in chunk_text(text):
                    cur.execute("INSERT INTO docs(path, content) VALUES(?, ?)", (str(p.name), ch))
                    count += 1
            except Exception as e:
                print(f"Error processant {p}: {e}")
    conn.commit()
    conn.close()
    return count

def rag_search(query: str, k: int = 5):
    """Busca a la base de dades RAG."""
    conn = sqlite3.connect(RAG_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT path, content FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?", (query, k))
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

# --- Interfície de Xat amb Chainlit ---

@cl.on_chat_start
async def start():
    """Lògica que s'executa quan un usuari inicia un xat."""
    # Inicialitza la base de dades en arrencar
    rag_init()
    
    # Informa a l'usuari que s'estan indexant els documents
    await cl.Message(content="Iniciant l'assistent... Indexant documents, si us plau, espera un moment.").send()
    
    # Realitza la indexació inicial
    count = rag_ingest(DOCS_DIR)
    
    await cl.Message(content=f"Indexació finalitzada! S'han processat {count} fragments de documents. Ja pots fer preguntes.").send()
    cl.user_session.set("rag_ready", True)

@cl.on_message
async def main(message: cl.Message):
    """Lògica que s'executa cada cop que l'usuari envia un missatge."""
    
    # Gestiona la pujada de fitxers de text
    txt_files = [f for f in message.elements if "text/plain" in f.mime]
    for file in txt_files:
        # Desa el fitxer a la carpeta de documents
        dest_path = DOCS_DIR / file.name
        dest_path.write_bytes(file.content)
        await cl.Message(content=f"Fitxer '{file.name}' desat. Re-indexant documents...").send()
        rag_ingest(DOCS_DIR)
        await cl.Message(content="Re-indexació finalitzada. Ja pots preguntar sobre el nou contingut.").send()
        return

    # Lògica principal del xat 
    query = message.content
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