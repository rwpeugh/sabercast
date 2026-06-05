"""Pipeline 01e — pull hitter batted-ball + spray profile from Baseball Savant.

Adds GB%, FB%, LD%, popup%, Pull%, Center%, Oppo% per batter per season for
2019-2024. The data lets Roster Builder reason about GIDP avoidance and
hit-toward-weak-defenders matchups, and lets Opponent Scouting describe
opposing-hitter tendencies in the threats / weaknesses / pitching-strategy
cards.

Source endpoint:
    https://baseballsavant.mlb.com/leaderboard/batted-ball?
        year=<YYYY>&player_type=batter&min=50&csv=true

Returns the top-253 qualified batters per season (Savant caps the response
server-side regardless of the ``min`` param). That's roughly the league's
qualified-hitter set -- covers every regular starter across the 30 MLB
teams. Coverage trade-offs documented in BUILD_LOG; the intentional decision
is to use this data ONLY in Roster Builder + Opponent Scouting where the
qualified-hitter pool matches the use case, and NOT in Gap Filler where
bargain-tier bench-player candidates fall outside the 253-row cap.

Run from the project root:
    python pipelines/01e_pull_batted_ball_hitters.py

Output:
    data/raw/batted_ball_hitters_<year>.csv   (one file per year, 6 files)

Idempotent. Re-running overwrites the CSV with fresh data.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR      = PROJECT_ROOT / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (compatible; sabercast-research/1.0)"
SEASONS    = list(range(2019, 2025))
URL_TMPL   = ("https://baseballsavant.mlb.com/leaderboard/batted-ball?"
              "year={year}&player_type=batter&min=50&csv=true")

# Savant uses "Last, First" -- flip to "First Last" for joins against bref
# and our existing batting CSVs (which use "First Last").
def _flip_name(savant_name: str) -> str:
    if "," in savant_name:
        last, first = [p.strip() for p in savant_name.split(",", 1)]
        return f"{first} {last}"
    return str(savant_name).strip()


@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=2, max=20))
def _pull_season(year: int) -> pd.DataFrame:
    """Fetch one season's batted-ball leaderboard as a DataFrame."""
    url = URL_TMPL.format(year=year)
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    # Savant prepends a BOM to the first column header -- pandas handles it
    # gracefully with utf-8-sig encoding.
    import io
    df = pd.read_csv(io.StringIO(r.text), encoding="utf-8-sig")
    return df


def _normalize_season(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Standardize column names + add year + flip player name.

    NB: build the output by first copying a non-scalar column from `df` to
    establish the row count, THEN add scalars like `year`. Otherwise pandas
    assigns the scalar to an empty index and the subsequent column assigns
    don't broadcast year back to all rows -- leaving the column as NaN.
    """
    out = pd.DataFrame()
    out["mlbam_id"]             = df["id"]                      # establishes len
    out["year"]                 = year                          # safe to scalar-broadcast now
    out["name_savant"]          = df["name"]
    out["name_human"]           = df["name"].astype(str).apply(_flip_name)
    out["bbe"]                  = df["bbe"]
    # Batted-ball type rates
    out["gb_rate"]              = df["gb_rate"]
    out["air_rate"]             = df["air_rate"]
    out["fb_rate"]              = df["fb_rate"]
    out["ld_rate"]              = df["ld_rate"]
    out["pu_rate"]              = df["pu_rate"]
    # Spray direction rates
    out["pull_rate"]            = df["pull_rate"]
    out["straight_rate"]        = df["straight_rate"]
    out["oppo_rate"]            = df["oppo_rate"]
    # Direction-by-trajectory rates (useful for hit-toward-weak-defender reasoning)
    out["pull_gb_rate"]         = df["pull_gb_rate"]
    out["straight_gb_rate"]     = df["straight_gb_rate"]
    out["oppo_gb_rate"]         = df["oppo_gb_rate"]
    out["pull_air_rate"]        = df["pull_air_rate"]
    out["straight_air_rate"]    = df["straight_air_rate"]
    out["oppo_air_rate"]        = df["oppo_air_rate"]
    out["snapshot_date"]        = str(date.today())
    # Final column order -- year first for readability when grep'ing the CSV
    return out[[
        "year", "mlbam_id", "name_savant", "name_human",
        "bbe",
        "gb_rate", "air_rate", "fb_rate", "ld_rate", "pu_rate",
        "pull_rate", "straight_rate", "oppo_rate",
        "pull_gb_rate", "straight_gb_rate", "oppo_gb_rate",
        "pull_air_rate", "straight_air_rate", "oppo_air_rate",
        "snapshot_date",
    ]]


def main() -> None:
    for year in SEASONS:
        print(f"pulling {year} ...", end=" ", flush=True)
        try:
            raw = _pull_season(year)
            df  = _normalize_season(raw, year)
            out_path = OUT_DIR / f"batted_ball_hitters_{year}.csv"
            df.to_csv(out_path, index=False, encoding="utf-8")
            print(f"{len(df):>3} batters  ->  {out_path.name}  "
                  f"({out_path.stat().st_size / 1024:.1f} KB)")
        except Exception as e:                                  # noqa: BLE001
            print(f"FAILED ({type(e).__name__}: {e})")
            raise
        time.sleep(0.6)   # be polite to Savant

    print()
    print("Sample row from batted_ball_hitters_2024.csv:")
    df = pd.read_csv(OUT_DIR / "batted_ball_hitters_2024.csv")
    sample = df[df["name_human"].str.contains("Judge", na=False)]
    if sample.empty:
        sample = df.head(1)
    for col in sample.columns:
        print(f"  {col:<22} {sample.iloc[0][col]}")


if __name__ == "__main__":
    main()
