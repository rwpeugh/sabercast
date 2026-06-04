"""Pipeline 01d — pull pitcher handedness from the MLB Stats API.

The Baseball Reference pitching CSV that Pipeline 01 produces does not carry
a "Throws" column. To support platoon-aware lineup ordering in the Roster
Builder when a probable starter is selected, we need each pitcher's throwing
hand (L/R/S). The MLB Stats API exposes this as ``pitchHand.code`` on every
active player and requires no authentication.

We pull every active player for each season in our backtest range
(2019-2024), filter to pitchers, and save name + throws + bats + birthDate +
mlbam_id + season to ``data/raw/player_handedness.csv``. The deduped result
covers everyone who pitched in MLB during the backtest window, which is what
the Roster Builder consumes.

Why not Lahman? The pybaseball Lahman wrapper points at a stale zip URL
that 404s as of mid-2026. The Chadwick Bureau GitHub repo has also been
reorganised. The MLB Stats API is the authoritative source anyway — this is
MLB's own data, real-time, free, and stable.

Why include bats? It's free in the same payload and is useful for the
Roster Builder's own hitter platoon decisions if we ever wire that up.

Run from the project root:
    python pipelines/01d_pull_handedness.py

Output:
    data/raw/player_handedness.csv

Idempotent. Re-running overwrites the CSV with fresh data.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR      = PROJECT_ROOT / "data" / "raw"
OUT_PATH     = OUT_DIR / "player_handedness.csv"

# MLB Stats API endpoint. sportId=1 = MLB.
URL = "https://statsapi.mlb.com/api/v1/sports/1/players"

# Season range — matches the rest of our pipeline (2019 through current).
SEASONS = list(range(2019, 2025))


@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=2, max=20))
def _pull_season(season: int) -> list[dict]:
    """Pull every active player for one season. Returns the raw `people` list."""
    r = requests.get(URL, params={"season": season}, timeout=30)
    r.raise_for_status()
    return r.json().get("people", [])


def _normalize_rows(people: list[dict], season: int) -> list[dict]:
    """Extract pitcher rows with the columns we need."""
    rows = []
    for p in people:
        pos = (p.get("primaryPosition") or {}).get("abbreviation", "")
        if pos != "P":
            continue
        hand = (p.get("pitchHand") or {}).get("code")
        if not hand:
            continue
        rows.append({
            "season":     season,
            "mlbam_id":   p.get("id"),
            "name":       p.get("fullName"),
            "throws":     hand,                                # R / L / S
            "bats":       (p.get("batSide") or {}).get("code", ""),
            "birth_date": p.get("birthDate", ""),
            "debut":      p.get("mlbDebutDate", ""),
        })
    return rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    for season in SEASONS:
        print(f"pulling {season} …", end=" ", flush=True)
        people = _pull_season(season)
        season_rows = _normalize_rows(people, season)
        all_rows.extend(season_rows)
        print(f"{len(season_rows)} pitchers")
        # Be polite to the public API
        time.sleep(0.5)

    if not all_rows:
        raise SystemExit("no rows returned — API may be down or rate-limited")

    df = pd.DataFrame(all_rows)
    # Dedupe on mlbam_id, keeping the most recent season's record. Throws is
    # stable across a career (one row per pitcher per career), so this is just
    # a final-row pick that makes the CSV easy to grep manually.
    df = df.sort_values(["mlbam_id", "season"]).drop_duplicates(
        subset=["mlbam_id"], keep="last"
    )
    df = df.sort_values("name").reset_index(drop=True)

    df.to_csv(OUT_PATH, index=False, encoding="utf-8")
    print()
    print(f"saved {OUT_PATH}  ·  {len(df):,} pitchers")
    print(f"throws distribution:\n{df['throws'].value_counts().to_string()}")
    print(f"file size: {OUT_PATH.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
