"""Pipeline 04 — Build the ChromaDB vectorstore.

Two document types are embedded with ``text-embedding-3-small``:

  1. **Glossary docs.** Short authoritative definitions of MLB analytics terms
     (WAR, wRC+, wOBA, FIP, xFIP, BABIP, ISO, OPS, OAA, exit velocity, barrel
     rate, hard-hit %, sprint speed, pop time, framing runs). These let the
     orchestrator answer "what does X mean" questions via retrieval.

  2. **Player profiles.** One per row in ``data/archetypes/player_archetypes.csv``
     (output of Pipeline 03). Each profile is a natural-language paragraph
     combining the player's archetype, 2024 line, position, team, age, and
     year-over-year trend. The Gap Filler player matcher will use these for
     embedding-based candidate retrieval.

If ``player_archetypes.csv`` is missing (Pipeline 03 not yet harvested), the
script embeds only the glossary docs and prints a note so the user knows to
re-run after harvesting.

Persistence: ``data/vectorstore/`` (ChromaDB persistent client).
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import chromadb
import pandas as pd
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
ARCHETYPES   = PROJECT_ROOT / "data" / "archetypes"
VECTORSTORE  = PROJECT_ROOT / "data" / "vectorstore"

sys.path.insert(0, str(PROJECT_ROOT))
from app.config import get_openai_api_key  # noqa: E402

EMBED_MODEL = "text-embedding-3-small"
EMBED_BATCH = 100


# ──────────────────────────────────────────────────────────────────────────────
# Glossary docs (inline; can be moved to data/raw/knowledge/*.txt later)
# ──────────────────────────────────────────────────────────────────────────────
GLOSSARY: list[tuple[str, str]] = [
    ("WAR",
     "Wins Above Replacement (WAR) is a comprehensive single-number measure of a "
     "player's total contribution, expressed as wins added versus a freely "
     "available replacement-level player at the same position. WAR combines "
     "offense, defense, base-running, and (for pitchers) run prevention. The "
     "league-average position player WAR is roughly 2.0; an All-Star is 4-5; an "
     "MVP candidate is 6+. WAR is reported by FanGraphs (fWAR) and Baseball "
     "Reference (bWAR) with small methodological differences."),
    ("wRC+",
     "Weighted Runs Created Plus (wRC+) is a park- and league-adjusted offensive "
     "rate stat scaled so that league-average production equals 100. A wRC+ of "
     "130 means the hitter created 30% more runs than league average; 70 means "
     "30% fewer. Because the scale is consistent across seasons and ballparks, "
     "wRC+ is the go-to for comparing hitters across eras and contexts."),
    ("wOBA",
     "Weighted On-Base Average (wOBA) is an offensive rate stat that weights "
     "each batted-ball and walk outcome by its actual run value. Unlike OPS, "
     "wOBA correctly values doubles more than walks and weights home runs "
     "appropriately. League-average wOBA is roughly the same as league-average "
     "OBP (around .315-.320). Elite hitters post .380+."),
    ("FIP",
     "Fielding Independent Pitching (FIP) estimates a pitcher's ERA based only "
     "on outcomes they directly control: strikeouts, walks, hit-by-pitches, and "
     "home runs allowed. By stripping out ball-in-play results, FIP is more "
     "predictive of future ERA than ERA itself. League average is ~4.00; an ace "
     "posts sub-3.00."),
    ("xFIP",
     "Expected FIP (xFIP) is identical to FIP but replaces the pitcher's actual "
     "home runs allowed with the league-average HR/FB rate applied to their "
     "fly-ball rate. xFIP is even more stable across years than FIP and is "
     "preferred for projecting future ERA when a pitcher's HR rate looks "
     "unsustainable."),
    ("BABIP",
     "Batting Average on Balls in Play (BABIP) is the batting average on all "
     "non-strikeout, non-home-run plate appearances. League BABIP is ~.300. "
     "For hitters BABIP reflects a mix of skill and luck; sustained marks above "
     ".340 usually indicate elite contact quality. For pitchers, BABIP is "
     "largely outside their control, so unusual highs or lows often regress."),
    ("ISO",
     "Isolated Power (ISO) is slugging percentage minus batting average — it "
     "measures extra-base power independent of contact rate. League average ISO "
     "is around .160; an elite power hitter posts .230+. ISO is the simplest "
     "way to isolate raw pop from overall batting average."),
    ("OPS",
     "On-base Plus Slugging (OPS) is the sum of on-base percentage and slugging "
     "percentage. League average is around .720-.750. .800 is solid, .900 is "
     "All-Star level, 1.000+ is MVP territory. OPS slightly underweights OBP "
     "relative to its true run value but remains the most widely-used quick "
     "offensive summary."),
    ("OAA",
     "Outs Above Average (OAA) is Statcast's range-based fielding metric. It "
     "credits or debits fielders for outs they generated above or below "
     "expected given the difficulty of every batted ball faced (distance, "
     "direction, hang time). Positive OAA = above-average range. Catchers are "
     "excluded from the standard OAA leaderboard because their defense is "
     "measured separately via pop time, framing, and arm strength."),
    ("Exit Velocity",
     "Exit Velocity is the speed of the baseball as it comes off the bat, "
     "measured in mph by Statcast. Average exit velocity around 88 mph is "
     "league average; 92+ mph is elite. Exit velocity is the strongest single "
     "predictor of batted-ball outcomes — higher exit velo drives more hits, "
     "extra-base hits, and home runs."),
    ("Barrel Rate",
     "A Barrel is a Statcast classification for batted balls with optimal "
     "combinations of exit velocity and launch angle (typically EV >= 98 mph "
     "and launch angle 26-30 degrees). Barrel rate (Barrels / Batted Ball "
     "Events) of 6% is league average; 12%+ is elite. Barrels are the highest-"
     "value batted ball outcomes — historically league-wide they produce a 1.500+ "
     "slugging percentage."),
    ("Hard-Hit Rate",
     "Hard-Hit Rate is the share of a hitter's batted balls with an exit "
     "velocity of 95 mph or greater. League average is around 38%; elite is "
     "50%+. Hard-hit rate is more predictive of future power than slugging "
     "itself because it strips out batted-ball luck and park effects."),
    ("Sprint Speed",
     "Sprint Speed is Statcast's measure of a runner's foot speed in feet per "
     "second, averaged over their fastest one-second windows on competitive "
     "running plays. League average is ~27 ft/sec; elite is 29.5+. Sprint speed "
     "predicts base-running value and infield-fly outcomes more than stolen "
     "base totals because it isolates the physical tool from situational "
     "decisions."),
    ("Pop Time",
     "Pop Time is the elapsed time from a pitch hitting the catcher's mitt to "
     "the ball arriving at second base on a stolen base attempt. League average "
     "pop time to 2B is around 1.96 seconds. Sub-1.85s is elite. Pop time "
     "combines arm strength, exchange quickness, and accuracy — it is the "
     "primary catcher defensive metric available on the Statcast leaderboard."),
    ("Framing Runs",
     "Framing Runs measure the runs a catcher saves or costs his pitcher by the "
     "quality of his pitch presentation — turning borderline pitches into "
     "called strikes. Elite framers save 10-15 runs per season versus average; "
     "poor framers cost 10+ runs. Framing was first measured publicly around "
     "2010 and is now part of the standard catcher defensive valuation, though "
     "Sabercast cannot retrieve it from the current pybaseball release."),
]


# ──────────────────────────────────────────────────────────────────────────────
# Player profile builder
# ──────────────────────────────────────────────────────────────────────────────
def build_player_profile(row: pd.Series, bat: pd.DataFrame, pit: pd.DataFrame) -> str | None:
    """Combine archetype + 2024 stats + trend into a single natural-language paragraph."""
    name = row.get("player_name")
    pid  = str(row.get("player_id", "")).strip()
    if not name or not pid:
        return None

    role = row.get("position_role", "")   # "batter" or "pitcher"
    archetype = row.get("archetype", "?")
    pitch_role = row.get("role")
    trend = row.get("trend", "stable")
    trend_reason = row.get("trend_reason", "")

    pid_int = None
    try:
        pid_int = int(float(pid))
    except (TypeError, ValueError):
        pass

    src = bat if role == "batter" else pit
    if pid_int is not None and "mlbID" in src.columns:
        match = src[src["mlbID"].astype(str) == str(pid_int)]
    else:
        match = src[src["Name"] == name]

    if match.empty:
        return None
    s = match.iloc[0]

    team = str(s.get("Tm", "?"))
    if role == "batter":
        pa  = int(s.get("PA", 0)) if pd.notna(s.get("PA")) else 0
        hr  = int(s.get("HR", 0)) if pd.notna(s.get("HR")) else 0
        avg = float(s.get("AVG", s.get("BA", 0)) or 0)
        obp = float(s.get("OBP", 0) or 0)
        slg = float(s.get("SLG", 0) or 0)
        ops = float(s.get("OPS", 0) or 0)
        body = (
            f"{name} is a 2024 {team} batter classified as a {archetype}. "
            f"In {pa} plate appearances he slashed .{int(avg*1000):03d}/"
            f".{int(obp*1000):03d}/.{int(slg*1000):03d} with {hr} home runs "
            f"and a {ops:.3f} OPS. Year-over-year trend: {trend}. {trend_reason}"
        )
    else:
        ip   = float(s.get("IP", 0) or 0)
        gs   = int(s.get("GS", 0)) if pd.notna(s.get("GS")) else 0
        era  = float(s.get("ERA", 0) or 0)
        whip = float(s.get("WHIP", 0) or 0)
        k9   = float(s.get("SO9", 0) or 0)
        body = (
            f"{name} is a 2024 {team} pitcher classified as a {archetype}"
            + (f" filling a {pitch_role} role" if pitch_role else "")
            + f". Over {ip:.1f} innings ({gs} starts) he posted a {era:.2f} ERA, "
            f"{whip:.3f} WHIP, and {k9:.1f} K/9. Year-over-year trend: {trend}. "
            f"{trend_reason}"
        )
    return body.strip()


# ──────────────────────────────────────────────────────────────────────────────
# Vectorstore build
# ──────────────────────────────────────────────────────────────────────────────
def embed_batched(client: OpenAI, texts: list[str]) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        chunk = texts[i:i + EMBED_BATCH]
        resp = client.embeddings.create(model=EMBED_MODEL, input=chunk)
        embeddings.extend([d.embedding for d in resp.data])
        print(f"  embedded {i + len(chunk):>5}/{len(texts):>5}")
    return embeddings


def main() -> None:
    print("=== Pipeline 04: Build vectorstore ===")

    # Clear any prior vectorstore contents without removing the directory
    # itself (OneDrive sometimes holds a lock that blocks rmtree on the dir).
    VECTORSTORE.mkdir(parents=True, exist_ok=True)
    for child in VECTORSTORE.iterdir():
        if child.is_file() or child.is_symlink():
            try:
                child.unlink()
            except OSError as e:
                print(f"  warn: could not remove {child.name}: {e}")
        else:
            try:
                shutil.rmtree(child)
            except OSError as e:
                print(f"  warn: could not remove {child.name}: {e}")
    print(f"Vectorstore directory ready at {VECTORSTORE}")

    client = chromadb.PersistentClient(path=str(VECTORSTORE))
    glossary_col = client.create_collection(
        name="sabercast_glossary",
        metadata={"hnsw:space": "cosine", "kind": "glossary"},
    )
    players_col = client.create_collection(
        name="sabercast_player_profiles",
        metadata={"hnsw:space": "cosine", "kind": "player_profiles", "year": 2024},
    )

    oai = OpenAI(api_key=get_openai_api_key())

    # ── Glossary ────────────────────────────────────────────────────────────
    print(f"\n[1/2] Glossary: {len(GLOSSARY)} entries")
    docs = [f"{term}: {definition}" for term, definition in GLOSSARY]
    ids  = [f"glossary_{term.lower().replace(' ', '_')}" for term, _ in GLOSSARY]
    metas = [{"term": term, "kind": "glossary"} for term, _ in GLOSSARY]
    embeds = embed_batched(oai, docs)
    glossary_col.add(ids=ids, documents=docs, embeddings=embeds, metadatas=metas)
    print(f"  saved {glossary_col.count()} glossary docs")

    # ── Player profiles ─────────────────────────────────────────────────────
    archetype_csv = ARCHETYPES / "player_archetypes.csv"
    if not archetype_csv.exists():
        print(f"\n[2/2] Player profiles: SKIP — {archetype_csv.name} not yet present.")
        print("      Run pipelines/03b_harvest_archetypes.py first, then re-run this pipeline.")
        return

    print(f"\n[2/2] Player profiles from {archetype_csv.name}")
    archetypes = pd.read_csv(archetype_csv, encoding="utf-8")
    print(f"  loaded {len(archetypes)} archetype rows")

    bat = pd.read_csv(DATA_RAW / "batting_2024.csv",  encoding="utf-8")
    pit = pd.read_csv(DATA_RAW / "pitching_2024.csv", encoding="utf-8")

    profiles: list[str] = []
    pids: list[str]     = []
    metas2: list[dict]  = []
    skipped = 0
    for _, row in archetypes.iterrows():
        prof = build_player_profile(row, bat, pit)
        if prof is None:
            skipped += 1
            continue
        pids.append(f"player_{row.get('player_id','?')}")
        profiles.append(prof)
        metas2.append({
            "player_name":  str(row.get("player_name", "")),
            "player_id":    str(row.get("player_id", "")),
            "position_role": str(row.get("position_role", "")),
            "archetype":    str(row.get("archetype", "")),
            "role":         str(row.get("role") or ""),
            "trend":        str(row.get("trend", "")),
            "year":         2024,
            "kind":         "player_profile",
        })

    print(f"  built {len(profiles)} profiles ({skipped} skipped — no matching stats row)")
    if profiles:
        embeds = embed_batched(oai, profiles)
        players_col.add(ids=pids, documents=profiles, embeddings=embeds, metadatas=metas2)
        print(f"  saved {players_col.count()} player profiles")

    print("\n=== Pipeline 04 done ===")
    print(f"Vectorstore: {VECTORSTORE}")
    print(f"  collections: sabercast_glossary ({glossary_col.count()}), "
          f"sabercast_player_profiles ({players_col.count()})")
    print(f"  embedding model: {EMBED_MODEL}")


if __name__ == "__main__":
    main()
