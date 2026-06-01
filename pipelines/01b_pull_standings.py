"""Pipeline 01b — Pull MLB team standings (wins per team) for specified years.

The correlation study needs per-team wins for both the predictor year (current
season wins as autocorrelation baseline) and the next year (the actual target
the gap_score is trying to predict).

The original correlation_study.py pulls standings internally during a run; this
helper script pre-caches 2018 + 2025 so the extended-range correlation has
contiguous coverage:
  - 2018 wins: needed as autocorrelation baseline for 2019 prediction rows
  - 2025 wins: needed to use 2024 stats as a predictor of 2025 outcomes (the
    extra year that turns the 150-row correlation into a 180-row correlation)

Usage:
    python pipelines/01b_pull_standings.py 2018 2025

Output: data/raw/standings_{year}.csv — one row per team with columns
  team_abbr, wins, losses, division
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
from pybaseball import standings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
DATA_RAW.mkdir(parents=True, exist_ok=True)

# bref full team name -> 3-letter abbr used elsewhere in the repo
NAME_TO_ABBR: dict[str, str] = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles":    "BAL", "Boston Red Sox":  "BOS",
    "Chicago Cubs":         "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds":      "CIN", "Cleveland Indians": "CLE",
    "Cleveland Guardians":  "CLE", "Colorado Rockies": "COL",
    "Detroit Tigers":       "DET", "Houston Astros":   "HOU",
    "Kansas City Royals":   "KC",  "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers":  "LAD", "Miami Marlins":    "MIA",
    "Milwaukee Brewers":    "MIL", "Minnesota Twins":  "MIN",
    "New York Mets":        "NYM", "New York Yankees": "NYY",
    "Oakland Athletics":    "OAK", "Athletics":        "OAK",  # 2025+ name change
    "Philadelphia Phillies":"PHI", "Pittsburgh Pirates": "PIT",
    "San Diego Padres":     "SD",  "San Francisco Giants": "SF",
    "Seattle Mariners":     "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays":       "TB",  "Texas Rangers":    "TEX",
    "Toronto Blue Jays":    "TOR", "Washington Nationals": "WSH",
}


def pull_year(year: int) -> int:
    out_path = DATA_RAW / f"standings_{year}.csv"
    if out_path.exists():
        df = pd.read_csv(out_path, encoding="utf-8")
        print(f"  [SKIP] standings_{year}.csv already on disk ({len(df)} rows)")
        return len(df)

    print(f"\n--- Pulling {year} standings ---")
    # standings() returns a list of DataFrames (one per division)
    divisions = standings(year)
    rows: list[dict] = []
    for div_df in divisions:
        # bref returns either a name col called "Tm" or "Team"
        name_col = next((c for c in ("Tm", "Team") if c in div_df.columns), None)
        if name_col is None:
            print(f"    [WARN] could not find team column in division; cols={list(div_df.columns)}")
            continue
        for _, r in div_df.iterrows():
            full_name = str(r[name_col]).strip()
            # Strip bref's playoff seed marker like "Houston Astros*" or "(W)"
            cleaned = full_name.rstrip(" *").split(" (")[0].strip()
            abbr    = NAME_TO_ABBR.get(cleaned)
            if abbr is None:
                # Fuzzy try: strip trailing " *"
                abbr = NAME_TO_ABBR.get(cleaned.replace(" *", ""))
            if abbr is None:
                print(f"    [WARN] unmapped team name: '{full_name}' / '{cleaned}'")
                continue
            wins   = int(r.get("W", 0))
            losses = int(r.get("L", 0))
            rows.append({
                "team_abbr": abbr,
                "team_name": cleaned,
                "wins":      wins,
                "losses":    losses,
            })

    out = pd.DataFrame(rows).sort_values("team_abbr").reset_index(drop=True)
    out.to_csv(out_path, index=False, encoding="utf-8")
    print(f"  saved {out_path.name} ({len(out)} teams)")
    print(out.to_string(index=False))
    return len(out)


def main() -> None:
    years = [int(y) for y in sys.argv[1:]] if len(sys.argv) > 1 else [2018, 2025]
    print(f"=== Pipeline 01b: pull standings for {years} ===")
    for year in years:
        pull_year(year)
        time.sleep(2)  # courteous rate limit between years


if __name__ == "__main__":
    main()
