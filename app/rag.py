"""The RAG brain: embed firm docs in pgvector, retrieve, rerank,
and answer with a citation — or stay silent.

Rule we never break: a wrong fee quote is a liability. If retrieval
can't find support for the question, we say so and route to a human
instead of inventing an answer.
"""

from __future__ import annotations

import os

import psycopg
from openai import OpenAI
from pgvector.psycopg import register_vector

from app.ingest import Chunk, ingest_dir

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
TOP_K_RETRIEVE = 8
TOP_K_FINAL = 3
MIN_SIMILARITY = float(os.environ.get("RAG_MIN_SIMILARITY", "0.30"))

_client = OpenAI()


def get_conn():
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    register_vector(conn)
    return conn


def init_store() -> None:
    """Create the documents table if it doesn't exist."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS firm_docs (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                source TEXT NOT NULL,
                section TEXT NOT NULL,
                chunk_index INT NOT NULL,
                embedding vector(1536),
                deprecated BOOLEAN NOT NULL DEFAULT FALSE
            )
            """
        )


def embed(texts: list[str]) -> list[list[float]]:
    resp = _client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def store_chunks(chunks: list[Chunk]) -> int:
    """Embed and store chunks. Returns the number stored."""
    vectors = embed([c.text for c in chunks])
    rows = [
        (c.text, c.source, c.section, c.index, v)
        for c, v in zip(chunks, vectors)
    ]
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO firm_docs (text, source, section, chunk_index, embedding)
            VALUES (%s, %s, %s, %s, %s)
            """,
            rows,
        )
    return len(rows)


def retrieve(question: str, top_k: int = TOP_K_RETRIEVE) -> list[dict]:
    """Top-k similarity search. Deprecated docs sink to the bottom."""
    qvec = embed([question])[0]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT text, source, section, chunk_index,
                   1 - (embedding <=> %s::vector) AS similarity,
                   deprecated
            FROM firm_docs
            ORDER BY deprecated ASC, embedding <=> %s::vector
            LIMIT %s
            """,
            (qvec, qvec, top_k),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def rerank(question: str, candidates: list[dict], top_k: int = TOP_K_FINAL) -> list[dict]:
    """Cheap keyword rerank: prefer chunks sharing the question's key terms.

    Good enough for an intake FAQ corpus. Swap for a cross-encoder
    when the doc set grows past a few hundred pages.
    """
    terms = {t.lower().strip("?,.!") for t in question.split() if len(t) > 3}
    for c in candidates:
        hay = f"{c['section']} {c['text']}".lower()
        c["_overlap"] = sum(1 for t in terms if t in hay)
    return sorted(candidates, key=lambda c: (c["_overlap"], c["similarity"]),
                  reverse=True)[:top_k]


def answer(question: str) -> dict:
    """Answer a firm question with citations, or decline honestly.

    Returns {"answer": str, "citations": [...], "declined": bool}.
    """
    candidates = retrieve(question)
    if not candidates or candidates[0]["similarity"] < MIN_SIMILARITY:
        return {
            "answer": "I don't have that information in the firm's documents. "
                      "Let me connect you with someone at the firm who does.",
            "citations": [],
            "declined": True,
        }
    top = rerank(question, candidates)
    context = "\n\n".join(
        f"[{c['source']} :: {c['section'] or 'general'}]\n{c['text']}"
        for c in top
    )
    resp = _client.chat.completions.create(
        model=os.environ.get("ANSWER_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": (
                    "You answer questions about the law firm using ONLY the "
                    "provided documents. Cite each fact as [source :: section]. "
                    "If the documents don't contain the answer, say you don't "
                    "know. You never give legal advice. Keep answers short."
                ),
            },
            {"role": "user", "content": f"Documents:\n{context}\n\nQuestion: {question}"},
        ],
    )
    return {
        "answer": resp.choices[0].message.content.strip(),
        "citations": [{"source": c["source"], "section": c["section"]} for c in top],
        "declined": False,
    }


if __name__ == "__main__":
    init_store()
    chunks = ingest_dir(__import__("pathlib").Path("data"))
    print(f"storing {len(chunks)} chunks...")
    print(f"stored: {store_chunks(chunks)}")
