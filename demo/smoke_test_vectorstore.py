"""Verify the vectorstore returns sensible results for sample queries."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import chromadb  # noqa: E402
from openai import OpenAI  # noqa: E402

from app.config import get_openai_api_key  # noqa: E402

VECTORSTORE = ROOT / "data" / "vectorstore"
EMBED_MODEL = "text-embedding-3-small"

oai    = OpenAI(api_key=get_openai_api_key())
client = chromadb.PersistentClient(path=str(VECTORSTORE))
gloss  = client.get_collection("sabercast_glossary")
players= client.get_collection("sabercast_player_profiles")


def embed(text: str) -> list[float]:
    return oai.embeddings.create(model=EMBED_MODEL, input=[text]).data[0].embedding


def query(collection, q: str, k: int = 3) -> list:
    res = collection.query(query_embeddings=[embed(q)], n_results=k)
    return list(zip(res["documents"][0], res["distances"][0],
                    res["metadatas"][0] if res["metadatas"] else [None]*k))


print("=== Glossary queries ===")
for q in [
    "what does WAR stand for in baseball",
    "metric for catcher arm strength and throwing time",
    "exit velocity definition",
]:
    print(f"\nQuery: {q!r}")
    for doc, dist, meta in query(gloss, q, k=2):
        term = meta.get("term") if meta else "?"
        print(f"  [{dist:.3f}] {term}: {doc[:80]}...")

print("\n\n=== Player profile queries ===")
for q in [
    "elite young shortstop with power and speed",
    "ace left-handed starter with high strikeouts",
    "veteran power-hitting first baseman",
    "shutdown closer with low ERA",
    "improving young pitcher with control issues",
]:
    print(f"\nQuery: {q!r}")
    for doc, dist, meta in query(players, q, k=3):
        name = meta.get("player_name", "?")
        archetype = meta.get("archetype", "?")
        trend = meta.get("trend", "?")
        print(f"  [{dist:.3f}] {name}  ·  {archetype}  ·  trend={trend}")
        print(f"           {doc[:110]}...")
