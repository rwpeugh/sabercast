"""Pipeline 01f — pull per-pitcher pitch arsenal stats from Baseball Savant.

Adds, for each (pitcher, pitch_type, season) combination: usage%, BA / SLG /
wOBA allowed, expected stats (est_ba / est_slg / est_woba), whiff%, k%,
hard-hit%. Lets Roster Builder describe what a probable starter throws and
how each pitch performs, and lets Opponent Scouting characterize each top
pitcher's go-to weapons + hittable pitches.

Source endpoint:
    https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats?
        year=<YYYY>&min=100&csv=true

Returns ~600 rows per season = one row per (pitcher, pitch_type) where the
pitcher threw that pitch at least ~100 times. ~316 unique pitchers per
year, covering all rotation members plus established relievers across all
30 teams. Coverage is full for both Roster Builder's probable-starter use
case and Opponent Scouting's top-5 staff. Like Pipeline 01e, we deliberately
DO NOT use this in Gap Filler -- the same coverage-gap concern applies to
mid-tier FA pitchers.

Run from the project root:
    python pipelines/01f_pull_pitcher_arsenal.py

Output:
    data/raw/pitch_arsenal_<year>.csv   (one file per year, 6 files)
"""
from __future__ import annotations

import io
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
URL_TMPL   = ("https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats?"
              "year={year}&min=100&csv=true")


def _flip_name(savant_name: str) -> str:
    """'Cole, Gerrit' -> 'Gerrit Cole'."""
    if "," in savant_name:
        last, first = [p.strip() for p in savant_name.split(",", 1)]
        return f"{first} {last}"
    return str(savant_name).strip()


@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=2, max=20))
def _pull_season(year: int) -> pd.DataFrame:
    """Fetch one season's pitch-arsenal-stats leaderboard as a DataFrame."""
    url = URL_TMPL.format(year=year)
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), encoding="utf-8-sig")


def _normalize_season(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Standardize column names + add year + flip pitcher name."""
    out = pd.DataFrame()
    out["mlbam_id"]            = df["player_id"]                # establishes len
    out["year"]                = year
    out["name_savant"]         = df["last_name, first_name"]
    out["name_human"]          = df["last_name, first_name"].astype(str).apply(_flip_name)
    out["team"]                = df["team_name_alt"]
    out["pitch_type"]          = df["pitch_type"]               # e.g. "FF", "SL"
    out["pitch_name"]          = df["pitch_name"]               # e.g. "4-Seam Fastball"
    out["pitches_thrown"]      = df["pitches"]
    out["pitch_usage_pct"]     = df["pitch_usage"]              # percent (0-100, NOT a decimal)
    out["pa_against"]          = df["pa"]
    # Actual results vs this pitch
    out["ba"]                  = df["ba"]
    out["slg"]                 = df["slg"]
    out["woba"]                = df["woba"]
    # Whiff / strikeout / put-away effectiveness
    out["whiff_pct"]           = df["whiff_percent"]
    out["k_pct"]               = df["k_percent"]
    out["put_away_pct"]        = df["put_away"]
    # Expected results (quality of contact, regression-resistant)
    out["est_ba"]              = df["est_ba"]
    out["est_slg"]             = df["est_slg"]
    out["est_woba"]            = df["est_woba"]
    out["hard_hit_pct"]        = df["hard_hit_percent"]
    out["run_value_per_100"]   = df["run_value_per_100"]
    out["snapshot_date"]       = str(date.today())
    return out[[
        "year", "mlbam_id", "name_savant", "name_human", "team",
        "pitch_type", "pitch_name", "pitches_thrown", "pitch_usage_pct",
        "pa_against",
        "ba", "slg", "woba", "whiff_pct", "k_pct", "put_away_pct",
        "est_ba", "est_slg", "est_woba", "hard_hit_pct",
        "run_value_per_100",
        "snapshot_date",
    ]]


def main() -> None:
    for year in SEASONS:
        print(f"pulling {year} ...", end=" ", flush=True)
        try:
            raw = _pull_season(year)
            df  = _normalize_season(raw, year)
            out_path = OUT_DIR / f"pitch_arsenal_{year}.csv"
            df.to_csv(out_path, index=False, encoding="utf-8")
            n_pitchers = df["mlbam_id"].nunique()
            print(f"{len(df):>4} (pitcher x pitch_type) rows "
                  f"= {n_pitchers} unique pitchers  ->  {out_path.name}  "
                  f"({out_path.stat().st_size / 1024:.1f} KB)")
        except Exception as e:                                  # noqa: BLE001
            print(f"FAILED ({type(e).__name__}: {e})")
            raise
        time.sleep(0.6)

    print()
    print("Sample -- Gerrit Cole's 2024 arsenal:")
    df = pd.read_csv(OUT_DIR / "pitch_arsenal_2024.csv")
    cole = df[df["name_human"].str.contains("Gerrit Cole", na=False)]
    if not cole.empty:
        cols = ["pitch_name", "pitch_usage_pct", "pa_against",
                "ba", "slg", "woba", "whiff_pct", "est_ba", "est_slg"]
        print(cole[cols].to_string(index=False))


if __name__ == "__main__":
    main()
