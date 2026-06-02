"""eval/rag_eval.py — RAG accuracy delta vs vanilla gpt-4o (Phase 5 last spec item).

Tests whether ChromaDB-augmented retrieval gives gpt-4o a measurable
accuracy lift over asking the same model without context. 20 held-out
questions across 5 categories:

  1. Archetype lookup (5)        — gpt-4o doesn't know Sabercast's synthesized
                                    archetype labels (those are computed by the
                                    Pipeline 03 Batch API run, unique to our
                                    pipeline). RAG should crush this.
  2. Trend labels (3)             — same as above; trend (improving/declining/
                                    stable) is our computed label.
  3. Combined archetype + trend (4) — where vector similarity search excels.
  4. 2024 specific stats (4)      — gpt-4o has training-cutoff issues; RAG
                                    provides current data.
  5. General knowledge / glossary (4) — both should perform similarly; RAG
                                    might cite glossary or might add noise.

Each question is scored as 0/1:
  list-type:  at least N of the correct_answers appear in the response
  factual:    substring or numeric-within-tolerance match
  glossary:   key term appears in the answer

Two run conditions per question:
  no_retrieval — gpt-4o with no context, returns JSON {"answer": "..."}
  rag          — embed query via text-embedding-3-small → ChromaDB top-8
                 player_profiles + top-3 glossary → gpt-4o with that context

Outputs:
  eval/results/rag_accuracy.csv    one row per question with both answers + correct flags
  eval/results/rag_summary.csv     per-category accuracy + overall delta

Cost: 20 questions × 2 modes × 1 LLM call = 40 gpt-4o calls + 20 embeddings ≈ $0.20.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
VECTORSTORE  = PROJECT_ROOT / "data" / "vectorstore"
RESULTS_DIR  = PROJECT_ROOT / "eval" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))
from app.config import get_openai_api_key                                # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
#  Question set — pre-registered. Ground truth derived from data/vectorstore.
#
#  scoring rule per question:
#    "list_overlap"  -> response must mention at least `min_correct` of
#                       the names in `correct_answers` (case-insensitive
#                       substring match against the answer text).
#    "substring"     -> any of `correct_answers` appears as substring (case-
#                       insensitive).
#    "numeric"       -> the response must contain a number within
#                       `tolerance` of `correct_answers[0]` (parsed as float).
# ──────────────────────────────────────────────────────────────────────────────
def _ground_truth_from_vectorstore() -> dict:
    """Derive ground-truth player-name lists for archetype/trend questions
    directly from the persisted vectorstore. This avoids the curation bias of
    hand-picking 'expected' names — any player Sabercast actually labeled with
    the queried archetype/trend counts as a valid answer.
    """
    import chromadb
    client = chromadb.PersistentClient(path=str(VECTORSTORE))
    col = client.get_collection("sabercast_player_profiles")
    metas = col.get(include=["metadatas"])["metadatas"]
    by_arch = {}
    by_arch_trend = {}
    by_trend_role = {}
    for m in metas:
        name = m.get("player_name", "").strip()
        arch = m.get("archetype", "")
        trend = m.get("trend", "")
        role = m.get("position_role", "")
        by_arch.setdefault(arch, []).append(name)
        by_arch_trend.setdefault((arch, trend), []).append(name)
        by_trend_role.setdefault((trend, role), []).append(name)
    return {"by_arch": by_arch, "by_arch_trend": by_arch_trend, "by_trend_role": by_trend_role}


_GT = _ground_truth_from_vectorstore()


QUESTIONS: list[dict] = [
    # ── Category 1: Archetype lookup ──────────────────────────────────────
    {
        "id": "Q1", "category": "archetype",
        "question": "Name 3 players Sabercast classifies as 'ace_starter' archetype in 2024.",
        "scoring": "list_overlap", "min_correct": 2,
        "correct_answers": _GT["by_arch"].get("ace_starter", []),
    },
    {
        "id": "Q2", "category": "archetype",
        "question": "Name 3 players Sabercast classifies as 'defensive_specialist' archetype in 2024.",
        "scoring": "list_overlap", "min_correct": 2,
        "correct_answers": _GT["by_arch"].get("defensive_specialist", []),
    },
    {
        "id": "Q3", "category": "archetype",
        "question": "Name 4 players Sabercast classifies as 'speed_threat' archetype in 2024.",
        "scoring": "list_overlap", "min_correct": 3,
        "correct_answers": _GT["by_arch"].get("speed_threat", []),
    },
    {
        "id": "Q4", "category": "archetype",
        "question": "Name 3 'closer' archetype pitchers in our 2024 dataset.",
        "scoring": "list_overlap", "min_correct": 2,
        "correct_answers": _GT["by_arch"].get("closer", []),
    },
    {
        "id": "Q5", "category": "archetype",
        "question": "Name 3 'contact_hitter' archetype batters in 2024.",
        "scoring": "list_overlap", "min_correct": 2,
        "correct_answers": _GT["by_arch"].get("contact_hitter", []),
    },

    # ── Category 2: Trend labels ──────────────────────────────────────────
    {
        "id": "Q6", "category": "trend",
        "question": "Name 3 batters Sabercast marks with 'improving' trend in 2024.",
        "scoring": "list_overlap", "min_correct": 2,
        "correct_answers": _GT["by_trend_role"].get(("improving", "batter"), []),
    },
    {
        "id": "Q7", "category": "trend",
        "question": "Name 3 pitchers Sabercast marks with 'declining' trend in 2024.",
        "scoring": "list_overlap", "min_correct": 2,
        "correct_answers": _GT["by_trend_role"].get(("declining", "pitcher"), []),
    },
    {
        "id": "Q8", "category": "trend",
        "question": "Name 2 batters with 'stable' trend classification in 2024.",
        "scoring": "list_overlap", "min_correct": 1,
        "correct_answers": _GT["by_trend_role"].get(("stable", "batter"), []),
    },

    # ── Category 3: Combined archetype + trend filters ────────────────────
    {
        "id": "Q9", "category": "combined_filter",
        "question": "Name 2 'ace_starter' archetype pitchers with improving trend in 2024.",
        "scoring": "list_overlap", "min_correct": 1,
        "correct_answers": _GT["by_arch_trend"].get(("ace_starter", "improving"), []),
    },
    {
        "id": "Q10", "category": "combined_filter",
        "question": "List 3 'power_hitter' archetype batters with declining trend in 2024.",
        "scoring": "list_overlap", "min_correct": 2,
        "correct_answers": _GT["by_arch_trend"].get(("power_hitter", "declining"), []),
    },
    {
        "id": "Q11", "category": "combined_filter",
        "question": "Name a 'closer' archetype reliever with stable trend in 2024.",
        "scoring": "list_overlap", "min_correct": 1,
        "correct_answers": _GT["by_arch_trend"].get(("closer", "stable"), []),
    },
    {
        "id": "Q12", "category": "combined_filter",
        "question": "List 3 batters with 'speed_threat' archetype across MLB in 2024.",
        "scoring": "list_overlap", "min_correct": 2,
        "correct_answers": _GT["by_arch"].get("speed_threat", []),
    },

    # ── Category 4: 2024 specific stats (ground truth derived from our CSVs) ─
    {
        "id": "Q13", "category": "specific_stat",
        "question": "What was Aaron Judge's 2024 OPS according to Sabercast's data?",
        "scoring": "numeric", "tolerance": 0.05,
        "correct_answers": ["1.126"],
    },
    {
        "id": "Q14", "category": "specific_stat",
        "question": "How many home runs did Shohei Ohtani hit in 2024 according to Sabercast's data?",
        "scoring": "numeric", "tolerance": 2,
        "correct_answers": ["57"],
    },
    {
        "id": "Q15", "category": "specific_stat",
        "question": "Who led MLB in home runs during the 2024 regular season?",
        "scoring": "substring",
        "correct_answers": ["Aaron Judge", "Judge"],
    },
    {
        "id": "Q16", "category": "specific_stat",
        "question": "Which player had the highest OPS in MLB during the 2024 season?",
        "scoring": "substring",
        "correct_answers": ["Aaron Judge", "Judge"],
    },

    # ── Category 5: General knowledge / glossary ──────────────────────────
    {
        "id": "Q17", "category": "general",
        "question": "Which MLB team won the 2024 World Series?",
        "scoring": "substring",
        "correct_answers": ["Dodgers", "Los Angeles Dodgers", "LAD"],
    },
    {
        "id": "Q18", "category": "general",
        "question": "What primary position does Aaron Judge play?",
        "scoring": "substring",
        "correct_answers": ["CF", "RF", "OF", "outfield", "right field", "center field"],
    },
    {
        "id": "Q19", "category": "glossary",
        "question": "What does the baseball stat 'WAR' stand for, and what does a value of 0 mean?",
        "scoring": "substring",
        "correct_answers": ["Wins Above Replacement", "replacement-level"],
    },
    {
        "id": "Q20", "category": "glossary",
        "question": "What is wRC+? What does a value of 100 mean for a hitter?",
        "scoring": "substring",
        "correct_answers": ["weighted Runs Created", "league average", "park", "100", "average"],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  RAG retrieval helpers
# ──────────────────────────────────────────────────────────────────────────────
def _get_clients():
    import chromadb
    oai = OpenAI(api_key=get_openai_api_key())
    chroma = chromadb.PersistentClient(path=str(VECTORSTORE))
    return oai, chroma


def retrieve_context(query: str, oai: OpenAI, chroma) -> str:
    """Embed the query and pull top-8 player profiles + top-3 glossary entries.
    Returns a single string with all retrieved documents joined.
    """
    emb = oai.embeddings.create(
        model="text-embedding-3-small",
        input=query,
    ).data[0].embedding

    pp_col = chroma.get_collection("sabercast_player_profiles")
    pp_results = pp_col.query(query_embeddings=[emb], n_results=8,
                              include=["documents", "metadatas"])
    pp_lines = [
        f"[{m.get('archetype', '?')} | {m.get('trend', '?')} | {m.get('position_role', '?')}] "
        f"{d}"
        for d, m in zip(pp_results["documents"][0], pp_results["metadatas"][0])
    ]

    gl_col = chroma.get_collection("sabercast_glossary")
    gl_results = gl_col.query(query_embeddings=[emb], n_results=3,
                              include=["documents", "metadatas"])
    gl_lines = [f"[glossary] {d}" for d in gl_results["documents"][0]]

    return "\n\n".join(["=== Retrieved player profiles ==="] + pp_lines
                        + ["", "=== Retrieved glossary entries ==="] + gl_lines)


# ──────────────────────────────────────────────────────────────────────────────
#  LLM calls
# ──────────────────────────────────────────────────────────────────────────────
SYS_NO_RAG = """You are an MLB analyst. Answer the question accurately based on your knowledge.
Return STRICT JSON only: {"answer": "<your answer as a single string>"}.
If listing players, separate names with commas inside the answer string.
Do NOT hedge — give your best concrete answer. If you don't know, say "unknown"."""

SYS_RAG = """You are an MLB analyst with access to the following retrieved player profiles and glossary entries.
Use the retrieved context to answer the question. The 'archetype' and 'trend' labels in the context
are Sabercast's own classifications; if the question asks about them, use the retrieved labels.

Return STRICT JSON only: {"answer": "<your answer as a single string>"}.
If listing players, separate names with commas inside the answer string.
Do NOT hedge — give your best concrete answer based on the retrieved context."""


def ask_no_rag(question: str, oai: OpenAI) -> str:
    resp = oai.chat.completions.create(
        model="gpt-4o",
        temperature=0,
        seed=42,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYS_NO_RAG},
            {"role": "user",   "content": question},
        ],
    )
    data = json.loads(resp.choices[0].message.content)
    return str(data.get("answer", "")).strip()


def ask_rag(question: str, oai: OpenAI, chroma) -> str:
    context = retrieve_context(question, oai, chroma)
    user_msg = f"CONTEXT:\n{context}\n\nQUESTION: {question}"
    resp = oai.chat.completions.create(
        model="gpt-4o",
        temperature=0,
        seed=42,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYS_RAG},
            {"role": "user",   "content": user_msg},
        ],
    )
    data = json.loads(resp.choices[0].message.content)
    return str(data.get("answer", "")).strip()


# ──────────────────────────────────────────────────────────────────────────────
#  Scoring
# ──────────────────────────────────────────────────────────────────────────────
def _normalize(s: str) -> str:
    """Lowercase + strip accents for substring match."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s.lower()


def score(question: dict, answer: str) -> bool:
    rule = question["scoring"]
    correct = question["correct_answers"]
    norm_answer = _normalize(answer)

    if rule == "substring":
        return any(_normalize(c) in norm_answer for c in correct)

    if rule == "list_overlap":
        min_correct = question.get("min_correct", 1)
        matches = sum(1 for c in correct if _normalize(c) in norm_answer)
        return matches >= min_correct

    if rule == "numeric":
        import re
        tolerance = question.get("tolerance", 0)
        target = float(correct[0])
        numbers = [float(m) for m in re.findall(r"[-+]?\d*\.?\d+", answer)]
        return any(abs(n - target) <= tolerance for n in numbers)

    return False


# ──────────────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print(f"=== eval/rag_eval.py — RAG vs no-retrieval gpt-4o on {len(QUESTIONS)} questions ===\n")
    oai, chroma = _get_clients()

    rows: list[dict] = []
    for i, q in enumerate(QUESTIONS, 1):
        print(f"\n--- {q['id']} [{q['category']}] ---")
        print(f"Q: {q['question']}")
        try:
            ans_norag = ask_no_rag(q["question"], oai)
        except Exception as e:                                          # noqa: BLE001
            print(f"  [FAIL no-RAG] {type(e).__name__}: {e}")
            ans_norag = ""
        try:
            ans_rag = ask_rag(q["question"], oai, chroma)
        except Exception as e:                                          # noqa: BLE001
            print(f"  [FAIL RAG]    {type(e).__name__}: {e}")
            ans_rag = ""

        correct_norag = score(q, ans_norag)
        correct_rag   = score(q, ans_rag)
        print(f"  no-RAG: {'✓' if correct_norag else '✗'}  {ans_norag[:120]}")
        print(f"  RAG:    {'✓' if correct_rag else '✗'}  {ans_rag[:120]}")
        rows.append({
            "id":            q["id"],
            "category":      q["category"],
            "question":      q["question"],
            "scoring":       q["scoring"],
            "answer_norag":  ans_norag,
            "answer_rag":    ans_rag,
            "correct_norag": int(correct_norag),
            "correct_rag":   int(correct_rag),
            "delta":         int(correct_rag) - int(correct_norag),
        })
        time.sleep(0.5)   # courteous pacing

    df = pd.DataFrame(rows)
    out_csv = RESULTS_DIR / "rag_accuracy.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"\nSaved {out_csv} ({len(df)} questions)")

    # Summary by category
    print(f"\n{'=' * 60}")
    print("ACCURACY BY CATEGORY")
    print(f"{'=' * 60}")
    summary_rows: list[dict] = []
    for cat in df["category"].unique():
        sub = df[df["category"] == cat]
        n = len(sub)
        norag_acc = sub["correct_norag"].mean()
        rag_acc = sub["correct_rag"].mean()
        delta = rag_acc - norag_acc
        print(f"  {cat:18s}  n={n:2d}  no-RAG={norag_acc*100:5.1f}%  "
              f"RAG={rag_acc*100:5.1f}%  Δ={delta*100:+5.1f}pp")
        summary_rows.append({
            "category": cat, "n": n,
            "no_rag_acc": round(norag_acc, 4),
            "rag_acc":    round(rag_acc, 4),
            "delta_pp":   round(delta, 4),
        })

    overall_norag = df["correct_norag"].mean()
    overall_rag   = df["correct_rag"].mean()
    overall_delta = overall_rag - overall_norag
    print(f"\n  {'OVERALL':18s}  n={len(df):2d}  no-RAG={overall_norag*100:5.1f}%  "
          f"RAG={overall_rag*100:5.1f}%  Δ={overall_delta*100:+5.1f}pp")
    summary_rows.append({
        "category": "OVERALL", "n": len(df),
        "no_rag_acc": round(overall_norag, 4),
        "rag_acc":    round(overall_rag, 4),
        "delta_pp":   round(overall_delta, 4),
    })
    pd.DataFrame(summary_rows).to_csv(RESULTS_DIR / "rag_summary.csv",
                                       index=False, encoding="utf-8")

    # McNemar's test for paired binary accuracy
    from scipy import stats as sps
    rag_only_right  = int(((df.correct_rag == 1) & (df.correct_norag == 0)).sum())
    norag_only_right = int(((df.correct_rag == 0) & (df.correct_norag == 1)).sum())
    # Exact binomial test for McNemar with small n
    if rag_only_right + norag_only_right > 0:
        pval = sps.binomtest(rag_only_right, rag_only_right + norag_only_right, 0.5).pvalue
    else:
        pval = float("nan")
    print(f"\n  McNemar's paired test:")
    print(f"    RAG-only-correct:    {rag_only_right}")
    print(f"    no-RAG-only-correct: {norag_only_right}")
    print(f"    p-value:             {pval:.4f}")
    print(f"    verdict: "
          + ("RAG significantly better" if pval < 0.05 and rag_only_right > norag_only_right
             else "no-RAG significantly better" if pval < 0.05 and norag_only_right > rag_only_right
             else "no significant difference"))


if __name__ == "__main__":
    main()
