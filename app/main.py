# Aquest és el teu app/main.py revertit a l'estat anterior.
# Aquesta versió depèn de 'chainlit.md' i 'public/styles.css'.

import chainlit as cl
import os
import requests
import sqlite3
from pathlib import Path

# --- Configuració ---
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_API_URL = f"{OLLAMA_HOST}/api/chat"

DOCS_DIR = Path(os.getenv("DOCS_DIR", "/docs")).resolve()
RAG_DB_PATH = Path(os.getenv("RAG_DB_PATH", "/rag/rag.db")).resolve()

SYSTEM_PROMPT = (
    "You are a concise assistant. If the user asks for document-based answers, you may call RAG to retrieve snippets."
)

# --- Funcions de RAG ---
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

# --- Funcions de LLM ---
def llama_chat(messages, temperature=0.7):
    """Envia una petició al servidor d'Ollama usant l'API nativa."""
    payload = {
        "model": "mistral",
        "messages": messages,
        "stream": False,
        "options": { "temperature": temperature }
    }
    r = requests.post(OLLAMA_API_URL, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["message"]["content"]

async def translate_text(text: str, target_language: str):
    prompt = f"Translate the following text to {target_language}. ONLY output the translation and nothing else. Text: \"{text}\""
    messages = [{"role": "user", "content": prompt}]
    translated = await cl.make_async(llama_chat)(messages, temperature=0.1)
    return translated.strip().strip('"')

# --- LÒGICA D'ARRENCADA ---
print("Iniciant el servidor Chainlit..."); rag_init()
db_size = RAG_DB_PATH.stat().st_size if RAG_DB_PATH.exists() else 0
if db_size == 0: print("La base de dades RAG està buida. S'inicia la indexació inicial."); rag_ingest(DOCS_DIR)
else: print("La base de dades RAG ja existeix. S'omet la indexació inicial.")

# --- Interfície de Xat ---
@cl.on_chat_start
async def start():
    """S'executa quan un usuari inicia un xat."""

    # Definir DOS elements d'imatge, un per a cada tema.
    # Aquests fitxers han d'estar a 'app/public/'.
    # logo_light_element = cl.Image(
    #     path="./public/logo-light.png",
    #     name="logo_light",  # Nom per al tema fosc (logo clar)
    #     display="inline",
    #     size="large",
    # )
    # logo_dark_element = cl.Image(
    #     path="./public/logo-dark.png",
    #     name="logo_dark",  # Nom per al tema clar (logo fosc)
    #     display="inline",
    #     size="large",
    # )
    
    # Enviar el missatge de benvinguda adjuntant AMBDÓS elements.
    # El CSS s'hauria d'encarregar de mostrar només el correcte.
    await cl.Message(
        content="Hola! Soc el teu assistent de normativa tècnica.\nPer re-indexar els documents, escriu `REINDEX_RAG`."
        # elements=[logo_light_element, logo_dark_element]
    ).send()


@cl.on_message
async def main(message: cl.Message):
    query_ca = message.content

    if query_ca.upper() == "REINDEX_RAG":
        async with cl.Step(name="Re-indexar Base de Dades") as step:
            step.output = "Iniciant la re-indexació dels documents..."
            count = await cl.make_async(rag_ingest)(DOCS_DIR)
            await cl.Message(content=f"Re-indexació finalitzada! S'han processat {count} fragments.").send()
        return

    source_elements = []
    context = ""

    async with cl.Step(name="Traduir pregunta") as step:
        step.input = f"Pregunta (català): {query_ca}"
        query_es = await translate_text(query_ca, "Spanish")
        step.output = f"Traducció (castellà): {query_es}"

    async with cl.Step(name="Cercar documents") as step:
        step.input = query_es
        hits = await cl.make_async(rag_search)(query_es, k=4)
        step.output = f"{len(hits)} fragments trobats."

    if hits:
        async with cl.Step(name="Preparar context i fonts") as step:
            rag_snippets_es = "\n---\n".join([f"Document: {p}\nContent: {c}" for p, c in hits])
            context = f"RAG_SNIPPETS (Spanish original):\n{rag_snippets_es}"
            
            for i, (p, c) in enumerate(hits):
                async with cl.Step(name=f"Traduir fragment {i+1}"):
                    translated_content = await translate_text(c, 'Catalan')
                    source_elements.append(
                        cl.Text(name=f"Font {i+1}: {p}", content=f"**Original (castellà):**\n{c}\n\n**Traducció (català):**\n{translated_content}", display="inline")
                    )
            step.output = "Context i fonts preparades per a la UI."

    messages = [ {"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": (context + "\n\n" + query_ca)} ]

    async with cl.Step(name="Generar resposta") as step:
        answer = await cl.make_async(llama_chat)(messages)
        await cl.Message(content=answer, elements=source_elements).send()