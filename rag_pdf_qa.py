import sys
import numpy as np                  # fast math for comparing vectors
import ollama                       # local LLM + local embeddings
from pypdf import PdfReader         # pip install pypdf  (read PDF text)

CHAT_MODEL = "llama3.1:8b"          # the model that writes answers
EMBED_MODEL = "nomic-embed-text"    # the model that makes embeddings (ollama pull nomic-embed-text)

# ---------- STEP 1: read the PDF ----------
def read_pdf(path):
    reader = PdfReader(path)
    # extract_text() gives the text of one page; we join all pages
    return "\n".join((page.extract_text() or "") for page in reader.pages)

# ---------- STEP 2: cut the text into chunks ----------
def split_into_chunks(text, size=800, overlap=150):
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])   # one piece of 800 characters
        start += size - overlap                   # move forward, but keep 150 chars overlap
    return [c for c in chunks if c.strip()]       # remove empty pieces

# ---------- STEP 3: embeddings = numbers that describe the meaning of text ----------
def embed(texts):
    result = ollama.embed(model=EMBED_MODEL, input=texts)   # one call for many texts
    vectors = np.array(result["embeddings"], dtype=float)
    # Make every vector length 1, so "dot product" = "cosine similarity"
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

# ---------- STEP 4: our tiny "vector store" (a list of chunks + a matrix) ----------
def build_index(pdf_path):
    chunks = split_into_chunks(read_pdf(pdf_path))
    return chunks, embed(chunks)

def search(question, chunks, vectors, top_k=3):
    q = embed([question])[0]                      # the question as numbers
    scores = vectors @ q                          # similarity with every chunk
    best = np.argsort(scores)[::-1][:top_k]       # indexes of the best chunks
    return [chunks[i] for i in best]

# ---------- STEP 5: ask the LLM, using ONLY the found chunks ----------
def answer(question, chunks, vectors):
    context = "\n---\n".join(search(question, chunks, vectors))
    prompt = (
        "Answer the question using ONLY the context below. "
        "If the answer is not in the context, say: I don't know.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )
    reply = ollama.chat(model=CHAT_MODEL, messages=[{"role": "user", "content": prompt}])
    return reply["message"]["content"]

if __name__ == "__main__":
    chunks, vectors = build_index(sys.argv[1])    # python rag_pdf_qa.py handbook.pdf
    print(f"Ready: {len(chunks)} chunks. Type 'exit' to stop.")
    while True:
        q = input("\nQuestion> ").strip()
        if q.lower() in ("exit", "quit", ""):
            break
        print(answer(q, chunks, vectors))
