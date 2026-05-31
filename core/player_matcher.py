"""Embedding-based player matcher (Pipeline 04 → runtime).

Replaces `_pick_targets`'s position-equality + stat-fit ranking with semantic
retrieval over the ChromaDB ``sabercast_player_profiles`` collection:

  1. Build a natural-language description of what the gap needs (the LLM's
     own reasoning, the position, and the offense/defense split).
  2. Embed that description with ``text-embedding-3-small``.
  3. Query ChromaDB for the top-N semantically-similar player profiles.
  4. Filter the matches to those with a signed contract at the gap position,
     signed on or before ``evaluation_year``, AAV within the single-signing
     ceiling. This enforces the no-look-ahead and budget rules.
  5. Return up to k candidates in the same dict shape that the UI already
     understands.

Falls back gracefully if the vectorstore is unavailable.
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VECTORSTORE  = PROJECT_ROOT / "data" / "vectorstore"

sys.path.insert(0, str(PROJECT_ROOT))

# Match the orchestrator's accent-fold helper so Latino names join correctly
# between Spotrac (ASCII) and bref (UTF-8 with diacritics).
def _ascii_fold(s: str) -> str:
    if not isinstance(s, str):
        return s
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


# Lazy globals — built once per process.
_oai_client = None
_chroma_collection = None


def vectorstore_available() -> bool:
    """Best-effort check that the vectorstore exists and is usable."""
    if not VECTORSTORE.exists():
        return False
    try:
        import chromadb                                          # noqa: F401
        return True
    except ImportError:
        return False


def _client_and_collection():
    """Initialize OpenAI + ChromaDB clients once per process."""
    global _oai_client, _chroma_collection
    if _oai_client is not None and _chroma_collection is not None:
        return _oai_client, _chroma_collection

    from openai import OpenAI
    import chromadb

    from app.config import get_openai_api_key
    _oai_client = OpenAI(api_key=get_openai_api_key())

    chroma = chromadb.PersistentClient(path=str(VECTORSTORE))
    try:
        _chroma_collection = chroma.get_collection("sabercast_player_profiles")
    except Exception:
        _chroma_collection = None
    return _oai_client, _chroma_collection


def _gap_to_query(gap: dict) -> str:
    """Turn the LLM's gap description into a natural-language target spec
    suitable for embedding retrieval. Includes the position several times
    so the embedding leans toward profiles of players at that position
    (the vectorstore profiles say "batter"/"pitcher" generically but the
    LLM-generated trend rationales often mention specific positions)."""
    pos = gap.get("position", "?")
    reasoning = gap.get("reasoning", "")
    comp = gap.get("gap_components") or {}
    off = comp.get("offense")
    dfn = comp.get("defense")

    parts = [f"Target acquisition: a {pos} who can improve our team at {pos}."]
    if reasoning:
        parts.append(reasoning)
    if off is not None and dfn is not None:
        if dfn >= off:
            parts.append(
                f"Defensive component dominates ({dfn:.1f}) — prioritize an "
                f"above-average defender at {pos}."
            )
        elif off >= dfn:
            parts.append(
                f"Offensive component dominates ({off:.1f}) — prioritize a "
                f"strong offensive profile at {pos}."
            )
    return " ".join(parts)


def find_matches(gap: dict, contracts: pd.DataFrame,
                 batting: pd.DataFrame, pitching: pd.DataFrame,
                 evaluation_year: int, single_signing_ceiling: float,
                 k: int = 3, top_n_semantic: int = 200) -> list[dict]:
    """Return up to ``k`` player candidates matching the gap, via semantic
    retrieval + budget/position/year filtering.

    Each result dict carries the same fields the UI already expects
    (`player_name`, `team`, `position`, `aav`, `years`, `total_value`,
    `signed_year`, `age_at_signing`, `stats_2024`, `fit_score`) plus three
    new ones surfaced from the vectorstore metadata:
    `archetype`, `trend`, `semantic_score`.

    Returns an empty list (not None) if the vectorstore is unavailable; the
    orchestrator falls back to the stat-fit picker in that case.
    """
    if not vectorstore_available():
        return []
    oai, collection = _client_and_collection()
    if collection is None:
        return []

    query_text = _gap_to_query(gap)
    embed_resp = oai.embeddings.create(model="text-embedding-3-small",
                                       input=[query_text])
    qvec = embed_resp.data[0].embedding

    res = collection.query(query_embeddings=[qvec],
                           n_results=top_n_semantic,
                           include=["documents", "metadatas", "distances"])
    docs    = res.get("documents", [[]])[0]
    metas   = res.get("metadatas", [[]])[0]
    dists   = res.get("distances", [[]])[0]

    # Index contracts by accent-folded name for fast filter lookup.
    contracts = contracts.copy()
    contracts["folded_name"] = contracts["player_name"].astype(str).map(_ascii_fold)
    target_pos = gap.get("position", "")

    results: list[dict] = []
    for doc, meta, dist in zip(docs, metas, dists):
        name = meta.get("player_name") or ""
        folded = _ascii_fold(name)
        # Filter: contracts at the gap position, signed by evaluation_year,
        # and AAV within the single-signing ceiling.
        pool = contracts[
            (contracts["folded_name"] == folded)
            & (contracts["position"] == target_pos)
            & (contracts["signed_year"].fillna(9999) <= evaluation_year)
            & (contracts["aav"].fillna(float("inf")) <= single_signing_ceiling)
        ]
        if pool.empty:
            continue
        row = pool.sort_values("aav", ascending=False).iloc[0]

        # Look up the player's 2024 stats for the card display.
        role = (meta.get("position_role") or "").lower()
        src = batting if role == "batter" else pitching
        stats = None
        if "Name" in src.columns:
            stat_match = src[src["Name"].apply(_ascii_fold) == folded]
            if not stat_match.empty:
                s = stat_match.iloc[0]
                if role == "batter":
                    stats = {
                        "role": "hitter",
                        "PA":   int(s.get("PA", 0)) if pd.notna(s.get("PA"))  else 0,
                        "HR":   int(s.get("HR", 0)) if pd.notna(s.get("HR"))  else 0,
                        "RBI":  int(s.get("RBI", 0)) if pd.notna(s.get("RBI")) else 0,
                        "AVG":  float(s.get("AVG", s.get("BA", 0)) or 0),
                        "OBP":  float(s.get("OBP", 0) or 0),
                        "SLG":  float(s.get("SLG", 0) or 0),
                        "OPS":  float(s.get("OPS", 0) or 0),
                    }
                else:
                    stats = {
                        "role": "pitcher",
                        "IP":   float(s.get("IP", 0) or 0),
                        "G":    int(s.get("G", 0)) if pd.notna(s.get("G")) else 0,
                        "GS":   int(s.get("GS", 0)) if pd.notna(s.get("GS")) else 0,
                        "ERA":  float(s.get("ERA")) if pd.notna(s.get("ERA")) else None,
                        "WHIP": float(s.get("WHIP")) if pd.notna(s.get("WHIP")) else None,
                        "K9":   float(s.get("SO9")) if pd.notna(s.get("SO9")) else None,
                    }

        results.append({
            "player_name":   row["player_name"],
            "team":          row["team"],
            "position":      row["position"],
            "aav":           int(row["aav"])            if pd.notna(row["aav"])            else None,
            "years":         int(row["years"])          if pd.notna(row["years"])          else None,
            "total_value":   int(row["contract_value"]) if pd.notna(row["contract_value"]) else None,
            "signed_year":   int(row["signed_year"])    if pd.notna(row["signed_year"])    else None,
            "age_at_signing":int(row["age"])            if pd.notna(row["age"])            else None,
            "stats_2024":    stats,
            "fit_score":     None,            # not used for vectorstore matches
            "archetype":     meta.get("archetype"),
            "trend":         meta.get("trend"),
            "semantic_score": round(1.0 - float(dist), 3),  # cosine distance → similarity
        })
        if len(results) >= k:
            break
    return results
