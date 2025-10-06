import chainlit as cl
import os
import requests
import sqlite3
from pathlib import Path

# --- Configuració i Lògica de Backend ---
LLAMA_URL = os.getenv("LLAMA_URL", "http://localhost:8080")
DOCS_DIR = Path(os.getenv("DOCS_DIR", "/docs")).resolve()
RAG_DB_PATH = Path(os.getenv("RAG_DB_PATH", "/rag/rag.db")).resolve()

SYSTEM_PROMPT = (
    "You are a concise assistant. If the user asks for document-based answers, you may call RAG to retrieve snippets."
)

# --- Funcions de RAG i LLM (sense canvis significatius) ---

def rag_init():
    RAG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(RAG_DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(path, content)")
    conn.commit(); conn.close()

def chunk_text(text):
    CHUNK_SIZE = 1200; CHUNK_OVERLAP = 150
    return [text[i:i+CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE - CHUNK_OVERLAP)]

def rag_ingest(path: Path):
    print("=============================================")
    print(f"🚀 Iniciant procés d'indexació des de: {path}")
    if not path.exists():
        print(f"⚠️  Advertència: El directori de documents no existeix. S'omet la indexació."); print("============================================="); return 0
    conn = sqlite3.connect(RAG_DB_PATH); cur = conn.cursor(); cur.execute("DELETE FROM docs")
    total_chunks, files_processed = 0, 0
    files_to_process = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in {".txt", ".md", ".log"}]
    print(f"ℹ️  S'han trobat {len(files_to_process)} fitxers per processar.")
    for p in files_to_process:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            for ch in chunk_text(text):
                cur.execute("INSERT INTO docs(path, content) VALUES(?, ?)", (str(p.name), ch)); total_chunks += 1
            files_processed += 1
            if files_processed % 10 == 0: print(f"  -> Processats {files_processed} de {len(files_to_process)} fitxers...")
        except Exception as e: print(f"❌ Error processant {p}: {e}")
    conn.commit(); conn.close()
    print(f"✅ Indexació finalitzada!\n   - Fitxers processats: {files_processed}\n   - Fragments creats: {total_chunks}"); print("============================================="); return total_chunks

def rag_search(query: str, k: int = 5):
    conn = sqlite3.connect(RAG_DB_PATH); cur = conn.cursor()
    safe_query = f'"{query}"'
    cur.execute("SELECT path, content FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?", (safe_query, k))
    rows = cur.fetchall(); conn.close(); return rows

def llama_chat(messages, temperature=0.7, max_tokens=1024):
    payload = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    url = f"{LLAMA_URL}/v1/chat/completions"
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# --- NOVA FUNCIÓ DE TRADUCCIÓ ---
async def translate_text(text: str, target_language: str):
    """Tradueix text utilitzant el LLM."""
    prompt = f"Translate the following text to {target_language}. ONLY output the translation and nothing else, no explanations. Text: \"{text}\""
    messages = [{"role": "user", "content": prompt}]
    # Fem una crida amb baixa temperatura per a una traducció més directa
    translated = await cl.make_async(llama_chat)(messages, temperature=0.1)
    return translated.strip().strip('"')

# --- LÒGICA D'ARRENCADA ---
print("Iniciant el servidor Chainlit..."); rag_init()
db_size = RAG_DB_PATH.stat().st_size if RAG_DB_PATH.exists() else 0
if db_size == 0: print("La base de dades RAG està buida. S'inicia la indexació inicial."); rag_ingest(DOCS_DIR)
else: print("La base de dades RAG ja existeix. S'omet la indexació inicial.")

# --- Interfície de Xat amb Chainlit ---

@cl.on_chat_start
async def start():
    await cl.Message(content="Hola! Soc el teu assistent de RAG. El sistema ja està llest. Per re-indexar els documents, escriu `REINDEX_RAG`.").send()

@cl.on_message
async def main(message: cl.Message):
    query_ca = message.content

    if query_ca.upper() == "REINDEX_RAG":
        async with cl.Step(name="Re-indexar Base de Dades") as step:
            step.output = "Iniciant la re-indexació dels documents. Això pot trigar una estona..."
            count = await cl.make_async(rag_ingest)(DOCS_DIR)
            await cl.Message(content=f"Re-indexació finalitzada! S'han processat {count} fragments.").send()
        return

    # --- NOU FLUX DE XAT AMB TRADUCCIÓ ---
    source_elements = []
    context = ""

    async with cl.Step(name="Traduir pregunta") as step:
        step.input = f"Pregunta original (català): {query_ca}"
        query_es = await translate_text(query_ca, "Spanish")
        step.output = f"Pregunta traduïda (castellà): {query_es}"

    async with cl.Step(name="Cercar documents") as step:
        step.input = query_es
        hits = await cl.make_async(rag_search)(query_es, k=4)
        step.output = f"{len(hits)} fragments trobats."

    if hits:
        async with cl.Step(name="Traduir i preparar context") as step:
            step.input = f"{len(hits)} fragments en castellà."
            rag_snippets_es = "\n---\n".join([f"Document: {p}\nContingut: {c}" for p, c in hits])
            
            # Tradueix el context sencer al català
            context_ca = await translate_text(rag_snippets_es, "Catalan")
            context = f"RAG_SNIPPETS (Spanish original):\n{rag_snippets_es}"
            step.output = context_ca
            
            # Prepara els elements per mostrar a la UI
            source_elements = [
                cl.Text(name=f"Fragment {i+1}", content=f"**Original (castellà):**\n{c}\n\n**Traducció (català):**\n{await translate_text(c, 'Catalan')}", display="inline")
                for i, (p, c) in enumerate(hits)
            ]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (context + "\n\n" + query_ca)}
    ]

    async with cl.Step(name="Generar resposta") as step:
        step.input = "Crida al LLM amb el context i la pregunta original."
        answer = await cl.make_async(llama_chat)(messages)
        # Envia la resposta final, adjuntant els fragments de context com a elements
        await cl.Message(content=answer, elements=source_elements).send()