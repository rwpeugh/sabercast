"""Pipeline 01c — Pull bWAR (Baseball Reference WAR) for batters and pitchers.

bWAR is the wins-above-replacement metric maintained by Baseball Reference. It
is the standard quantitative measure of a player's total contribution to wins
(positive vs the freely-available "replacement-level" player). Team WAR (sum
across the roster) is one of the strongest single predictors of next-year team
wins in professional projection systems.

Source: pybaseball.bwar_bat() and bwar_pitch() pull from Baseball Reference's
war_daily_bat / war_daily_pitch archive — a single historical file going back
to 1871. No rate limit. No FanGraphs dependency (which is HTTP 403'd for us).

Why bWAR and not fWAR:
  * fWAR (FanGraphs) is conceptually similar but uses different defensive
    inputs (UZR vs Rdrs). For team-level aggregation the two metrics correlate
    strongly (~0.9); either would serve our purpose.
  * FanGraphs is blocked for our pybaseball requests, so fWAR is not retrievable
    in this environment. bWAR is the equivalent metric we CAN obtain.

Outputs:
  data/raw/bwar_bat_archive.csv     (player-season hitting WAR, 2018+)
  data/raw/bwar_pitch_archive.csv   (player-season pitching WAR, 2018+)

The archives are filtered to year_ID >= 2018 to keep the files small (~5K
batting rows + ~3K pitching rows per year × 8 years). Going back to 2018 covers
the autocorrelation-baseline year and the 6-year correlation window.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
from pybaseball import bwar_bat, bwar_pitch, cache

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
DATA_RAW.mkdir(parents=True, exist_ok=True)

cache.enable()

MIN_YEAR = 2018   # autocorrelation baseline needs 2018; main study spans 2019-2025


def pull(label: str, fn, out_path: Path) -> int:
    if out_path.exists():
        df = pd.read_csv(out_path, encoding="utf-8")
        print(f"  [SKIP] {out_path.name} already on disk ({len(df):,} rows)")
        return len(df)
    print(f"\n--- {label} ---")
    t0 = time.time()
    df = fn()
    print(f"  raw: {len(df):,} rows · {len(df.columns)} cols · "
          f"year range {df['year_ID'].min()}–{df['year_ID'].max()}  "
          f"({time.time()-t0:.1f}s)")
    df = df[df["year_ID"] >= MIN_YEAR].copy()
    df.to_csv(out_path, index=False, encoding="utf-8")
    print(f"  saved {out_path.name} ({len(df):,} rows after MIN_YEAR={MIN_YEAR} filter)")
    return len(df)


def main() -> None:
    print(f"=== Pipeline 01c: pull bWAR archives (year_ID >= {MIN_YEAR}) ===")
    bat_rows = pull("bwar_bat (offensive bWAR)", bwar_bat,
                    DATA_RAW / "bwar_bat_archive.csv")
    pit_rows = pull("bwar_pitch (pitching bWAR)", bwar_pitch,
                    DATA_RAW / "bwar_pitch_archive.csv")
    print(f"\n=== Pipeline 01c done ===")
    print(f"  batting rows kept:  {bat_rows:,}")
    print(f"  pitching rows kept: {pit_rows:,}")


if __name__ == "__main__":
    main()
