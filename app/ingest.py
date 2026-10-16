"""Document ingest: load the firm's markdown docs, clean them up, and
cut them into overlapping chunks ready for embedding.

Boring on purpose. Bad chunks in, bad answers out — the chunker
is the cheapest quality lever in the whole system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

CHUNK_TOKENS = 400
CHUNK_OVERLAP = 50


@dataclass
class Chunk:
    text: str
    source: str      # e.g. "firm_faqs.md"
    section: str     # markdown heading the chunk came from, "" if none
    index: int


def load_markdown(path: Path) -> str:
    """Read a markdown file, strip the noisy bits we don't want embedded."""
    text = path.read_text(encoding="utf-8")
    # Drop horizontal rules and collapse 3+ blank lines; everything else
    # stays verbatim so chunk text matches what a human would read.
    text = re.sub(r"^---+\s*$", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _word_tokens(text: str) -> list[str]:
    # Cheap tokenizer. tiktoken would be more accurate, but word count
    # is close enough for chunk boundaries and keeps ingest dependency-free.
    return text.split()


def chunk_text(text: str, source: str, chunk_tokens: int = CHUNK_TOKENS,
               overlap: int = CHUNK_OVERLAP) -> list[Chunk]:
    """Sliding-window chunking over words, keeping the current section heading."""
    words = _word_tokens(text)
    chunks: list[Chunk] = []
    section = ""
    i, idx = 0, 0
    while i < len(words):
        window = words[i:i + chunk_tokens]
        # The heading at the start of the window is the section context.
        for w in window[:20]:
            if w.startswith("#"):
                section = w.lstrip("#").strip()
                break
        chunks.append(Chunk(
            text=" ".join(window),
            source=source,
            section=section,
            index=idx,
        ))
        idx += 1
        i += chunk_tokens - overlap
    return chunks


def ingest_dir(data_dir: Path) -> list[Chunk]:
    """Ingest every .md file in a directory. Returns chunks in read order."""
    chunks: list[Chunk] = []
    for path in sorted(data_dir.glob("*.md")):
        text = load_markdown(path)
        chunks.extend(chunk_text(text, source=path.name))
    return chunks


if __name__ == "__main__":
    chunks = ingest_dir(Path(__file__).resolve().parent.parent / "data")
    print(f"{len(chunks)} chunks from data/")
    for c in chunks[:3]:
        print(f"[{c.source} #{c.index} :: {c.section}] {c.text[:80]}...")
