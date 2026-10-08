import sys
from pathlib import Path

import chromadb

ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "data" / "notes"
CHROMA_DIR = ROOT / "data" / "chroma"

# Cosine distance: lower = more similar. Tune this using the debug output below.
MAX_DISTANCE = 0.75

_collection = None


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_or_create_collection(
            name="notes", metadata={"hnsw:space": "cosine"}
        )
    return _collection


def warmup() -> None:
    """Load the collection and embedding model once, so the first real query isn't slow."""
    _get_collection().query(query_texts=["warmup"], n_results=1)


def chunk_text(text: str, max_chars: int = 700) -> list[str]:
    """Split on blank lines, then merge paragraphs up to max_chars."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        if current and len(current) + len(p) > max_chars:
            chunks.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}".strip()
    if current:
        chunks.append(current)
    return chunks


def ingest() -> None:
    col = _get_collection()
    existing = col.get()["ids"]
    if existing:
        col.delete(ids=existing)  # rebuild from scratch each time
    total = 0
    for path in sorted(NOTES_DIR.glob("*.md")):
        chunks = chunk_text(path.read_text(encoding="utf-8"))
        if not chunks:
            continue
        col.add(
            ids=[f"{path.stem}-{i}" for i in range(len(chunks))],
            documents=chunks,
            metadatas=[{"source": path.stem, "chunk": i} for i in range(len(chunks))],
        )
        total += len(chunks)
        print(f"Ingested {path.name}: {len(chunks)} chunks")
    print(f"Done. {total} chunks total.")


def search(query: str, k: int = 3, debug: bool = False) -> list[dict]:
    res = _get_collection().query(query_texts=[query], n_results=k)
    out = []
    for doc, meta, dist in zip(
        res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        if debug:
            print(f"  dist={dist:.3f}  [{meta['source']}]  {doc[:70]!r}")
        if dist <= MAX_DISTANCE:
            out.append({"source": meta["source"], "text": doc, "distance": dist})
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "ingest":
        ingest()
    elif len(sys.argv) >= 3 and sys.argv[1] == "search":
        hits = search(" ".join(sys.argv[2:]), debug=True)
        print(f"{len(hits)} hits under threshold {MAX_DISTANCE}")
    else:
        print("Usage: python src/rag.py ingest | python src/rag.py search <query>")