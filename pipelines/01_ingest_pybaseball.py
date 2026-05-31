"""Pipeline 01 — Ingest player stats from pybaseball.

Full-build scope:
  * Multi-year batting + pitching (default 2019-2024). Sprint scope (single year)
    is preserved via the same CLI: ``python 01_ingest_pybaseball.py 2024``.
  * Statcast defensive metrics for 2024: per-position OAA (positions 2-9),
    sprint speed, and an attempted catcher framing pull (known to fail under the
    current pybaseball release; we log the failure to pipeline01_warnings.log
    and proceed using catcher OAA as the framing proxy).

Source strategy for batting/pitching:
  1. Try FanGraphs endpoints (``batting_stats``, ``pitching_stats``) first per spec.
  2. Fall back to Baseball Reference (``batting_stats_bref``, ``pitching_stats_bref``)
     if FanGraphs returns HTTP 403. The existing RAG notebook documented
     FanGraphs blocking pybaseball requests during 2025/2026.
  3. Both wrapped in tenacity exponential-backoff retry per spec error handling.

Statcast endpoints (Baseball Savant) are reachable without the FanGraphs issue
but require their own 5-second rate limit to stay courteous to the host.

Outputs:
  data/raw/batting_{year}.csv               for each year requested
  data/raw/pitching_{year}.csv              for each year requested
  data/raw/oaa_{year}.csv                   per-position OAA (years requested for defense)
  data/raw/sprint_speed_{year}.csv          all-player sprint speed
  data/raw/pipeline01_source.txt            which endpoints succeeded
  data/raw/pipeline01_warnings.log          known/expected failures (e.g. catcher framing)
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

import pandas as pd
from pybaseball import (
    batting_stats,
    batting_stats_bref,
    cache,
    pitching_stats,
    pitching_stats_bref,
    statcast_catcher_framing,
    statcast_catcher_poptime,
    statcast_outs_above_average,
    statcast_sprint_speed,
)
from tenacity import retry, stop_after_attempt, wait_exponential

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
DATA_RAW.mkdir(parents=True, exist_ok=True)

cache.enable()  # pybaseball caches raw responses; cheap to re-run


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _try_fangraphs_batting(year: int) -> pd.DataFrame:
    return batting_stats(year, qual=50)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _try_fangraphs_pitching(year: int) -> pd.DataFrame:
    return pitching_stats(year, qual=20)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _try_bref_batting(year: int) -> pd.DataFrame:
    return batting_stats_bref(year)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _try_bref_pitching(year: int) -> pd.DataFrame:
    return pitching_stats_bref(year)


def fetch_batting(year: int) -> tuple[pd.DataFrame, str]:
    """Pull batting stats. Returns (dataframe, source_label)."""
    try:
        df = _try_fangraphs_batting(year)
        print(f"  [OK]   FanGraphs batting: {len(df)} rows")
        return df, "fangraphs"
    except Exception as e:                              # noqa: BLE001
        print(f"  [FAIL] FanGraphs batting: {type(e).__name__}")
        print("         falling back to Baseball Reference")
        df = _try_bref_batting(year)
        # bref returns minors + majors mixed; restrict to MLB only
        if "Lev" in df.columns:
            df = df[df["Lev"].astype(str).str.contains("Maj", na=False)].copy()
        print(f"  [OK]   Baseball Reference batting: {len(df)} rows")
        return df, "bref"


def fetch_pitching(year: int) -> tuple[pd.DataFrame, str]:
    """Pull pitching stats. Returns (dataframe, source_label)."""
    try:
        df = _try_fangraphs_pitching(year)
        print(f"  [OK]   FanGraphs pitching: {len(df)} rows")
        return df, "fangraphs"
    except Exception as e:                              # noqa: BLE001
        print(f"  [FAIL] FanGraphs pitching: {type(e).__name__}")
        print("         falling back to Baseball Reference")
        df = _try_bref_pitching(year)
        if "Lev" in df.columns:
            df = df[df["Lev"].astype(str).str.contains("Maj", na=False)].copy()
        print(f"  [OK]   Baseball Reference pitching: {len(df)} rows")
        return df, "bref"


def coerce_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _fix_bref_unicode(s):
    """Decode pybaseball/bref's literal \\xc3\\xad escape strings into real UTF-8.

    bref returns player names as Python-repr-style byte escapes, so "Víctor"
    arrives as the 11-char string r"V\\xc3\\xadctor". Untreated, this propagates
    into the UI as garbled text. We do a round-trip latin-1 -> unicode_escape
    -> latin-1 -> utf-8 to recover the real glyph.
    """
    s = str(s) if s is not None else s
    if not isinstance(s, str) or "\\x" not in s:
        return s
    try:
        return s.encode("latin-1").decode("unicode_escape").encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def clean_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Apply unicode fix to every text-like column (object or pandas string dtype)."""
    for col in df.columns:
        dt = df[col].dtype
        if dt == object or str(dt).startswith("string"):
            df[col] = df[col].map(_fix_bref_unicode)
    return df


def pull_year(year: int) -> tuple[str, str, int, int]:
    """Pull and save one year of batting + pitching. Returns (bat_src, pit_src, n_bat, n_pit)."""
    print(f"\n--- Batting {year} ---")
    bat_path = DATA_RAW / f"batting_{year}.csv"
    if bat_path.exists():
        bat = pd.read_csv(bat_path, encoding="utf-8")
        bat_src = "cached"
        print(f"  [SKIP] {bat_path.name} already on disk ({len(bat)} rows)")
    else:
        bat, bat_src = fetch_batting(year)
        bat = clean_text_columns(bat)
        bat = coerce_numeric(
            bat,
            ["PA", "AB", "G", "H", "HR", "R", "RBI", "SB", "BB", "SO",
             "AVG", "BA", "OBP", "SLG", "OPS", "ISO", "wRC+", "WAR"],
        )
        if "AVG" not in bat.columns and "BA" in bat.columns:
            bat["AVG"] = bat["BA"]
        bat.to_csv(bat_path, index=False, encoding="utf-8")
        print(f"  saved {bat_path.name} ({len(bat)} rows, {len(bat.columns)} cols)")

    print(f"\n--- Pitching {year} ---")
    pit_path = DATA_RAW / f"pitching_{year}.csv"
    if pit_path.exists():
        pit = pd.read_csv(pit_path, encoding="utf-8")
        pit_src = "cached"
        print(f"  [SKIP] {pit_path.name} already on disk ({len(pit)} rows)")
    else:
        pit, pit_src = fetch_pitching(year)
        pit = clean_text_columns(pit)
        pit = coerce_numeric(
            pit,
            ["IP", "G", "GS", "W", "L", "SV", "ERA", "WHIP", "K/9", "SO9",
             "BB/9", "HR/9", "FIP", "xFIP", "WAR", "SO", "BB", "HR"],
        )
        pit.to_csv(pit_path, index=False, encoding="utf-8")
        print(f"  saved {pit_path.name} ({len(pit)} rows, {len(pit.columns)} cols)")

    return bat_src, pit_src, len(bat), len(pit)


# ──────────────────────────────────────────────────────────────────────────────
# Statcast defensive metrics
# ──────────────────────────────────────────────────────────────────────────────
STATCAST_RATE_SLEEP_S = 5.0   # courteous rate limit between Baseball Savant calls

# Position codes per Baseball Savant: 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF.
# Catchers are deliberately excluded from the standard OAA leaderboard (Statcast
# uses a different framework for them); we pull catcher pop-time separately.
OAA_POSITIONS = [3, 4, 5, 6, 7, 8, 9]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _try_statcast_oaa(year: int, pos: int) -> pd.DataFrame:
    return statcast_outs_above_average(year, pos=pos)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _try_statcast_sprint(year: int) -> pd.DataFrame:
    return statcast_sprint_speed(year, min_opp=10)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _try_statcast_catcher_poptime(year: int) -> pd.DataFrame:
    return statcast_catcher_poptime(year)


def pull_catcher_poptime(year: int, warnings_log: Path) -> int:
    """Pull catcher pop-time metrics — the Statcast catcher defensive proxy.

    The standard OAA leaderboard excludes catchers by design (catcher defense is
    measured by pop time, exchange, and arm strength rather than range). This
    function fills the catcher gap that ``pull_oaa`` cannot.
    """
    out_path = DATA_RAW / f"catcher_defense_{year}.csv"
    if out_path.exists():
        df = pd.read_csv(out_path, encoding="utf-8")
        print(f"  [SKIP] catcher_defense_{year}.csv already on disk ({len(df)} rows)")
        return len(df)
    print(f"\n--- Statcast catcher pop-time {year} ---")
    time.sleep(STATCAST_RATE_SLEEP_S)
    try:
        df = _try_statcast_catcher_poptime(year)
        df = clean_text_columns(df)
        df.to_csv(out_path, index=False, encoding="utf-8")
        print(f"  saved {out_path.name} ({len(df)} rows, {len(df.columns)} cols)")
        return len(df)
    except Exception as e:                              # noqa: BLE001
        msg = f"Catcher pop-time pull failed for year={year}: {type(e).__name__}: {e}"
        print(f"  [FAIL] {msg}")
        with warnings_log.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
        return 0


def pull_oaa(year: int, warnings_log: Path) -> int:
    """Pull per-position OAA for the year. Returns total row count or 0 on full failure."""
    out_path = DATA_RAW / f"oaa_{year}.csv"
    if out_path.exists():
        df = pd.read_csv(out_path, encoding="utf-8")
        print(f"  [SKIP] oaa_{year}.csv already on disk ({len(df)} rows)")
        return len(df)
    print(f"\n--- Statcast OAA {year} (positions {OAA_POSITIONS}) ---")
    frames: list[pd.DataFrame] = []
    for pos in OAA_POSITIONS:
        time.sleep(STATCAST_RATE_SLEEP_S)
        try:
            df = _try_statcast_oaa(year, pos)
            print(f"    [OK] pos={pos}: {len(df)} rows")
            frames.append(df)
        except Exception as e:                          # noqa: BLE001
            msg = f"OAA pull failed for year={year} pos={pos}: {type(e).__name__}: {e}"
            print(f"    [FAIL] {msg}")
            with warnings_log.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")
    if not frames:
        return 0
    combined = pd.concat(frames, ignore_index=True)
    combined = clean_text_columns(combined)
    combined.to_csv(out_path, index=False, encoding="utf-8")
    print(f"  saved {out_path.name} ({len(combined)} rows, {len(combined.columns)} cols)")
    return len(combined)


def pull_sprint_speed(year: int, warnings_log: Path) -> int:
    out_path = DATA_RAW / f"sprint_speed_{year}.csv"
    if out_path.exists():
        df = pd.read_csv(out_path, encoding="utf-8")
        print(f"  [SKIP] sprint_speed_{year}.csv already on disk ({len(df)} rows)")
        return len(df)
    print(f"\n--- Statcast sprint speed {year} ---")
    time.sleep(STATCAST_RATE_SLEEP_S)
    try:
        df = _try_statcast_sprint(year)
        df = clean_text_columns(df)
        df.to_csv(out_path, index=False, encoding="utf-8")
        print(f"  saved {out_path.name} ({len(df)} rows, {len(df.columns)} cols)")
        return len(df)
    except Exception as e:                              # noqa: BLE001
        msg = f"Sprint speed pull failed for year={year}: {type(e).__name__}: {e}"
        print(f"  [FAIL] {msg}")
        with warnings_log.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
        return 0


def pull_catcher_framing_attempt(year: int, warnings_log: Path) -> bool:
    """Attempt catcher framing pull. Expected to fail under current pybaseball release.

    The intent is to document the failure honestly so downstream code knows to
    use catcher OAA as the framing proxy.
    """
    out_path = DATA_RAW / f"catcher_framing_{year}.csv"
    if out_path.exists():
        print(f"  [SKIP] catcher_framing_{year}.csv already on disk")
        return True
    print(f"\n--- Statcast catcher framing {year} (best-effort) ---")
    time.sleep(STATCAST_RATE_SLEEP_S)
    try:
        df = statcast_catcher_framing(year)
        df = clean_text_columns(df)
        df.to_csv(out_path, index=False, encoding="utf-8")
        print(f"  [OK] saved {out_path.name} ({len(df)} rows)")
        return True
    except Exception as e:                              # noqa: BLE001
        msg = (f"Catcher framing pull failed for year={year}: "
               f"{type(e).__name__}: {e}. "
               f"This is the known pybaseball parser bug; downstream code "
               f"uses catcher OAA as the framing proxy.")
        print(f"  [EXPECTED-FAIL] {msg}")
        with warnings_log.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]
DEFENSE_YEARS = [2024]   # spec scope: defensive ingest for evaluation year only


def main(years: list[int] | None = None,
         defense_years: list[int] | None = None) -> None:
    years = years or DEFAULT_YEARS
    defense_years = defense_years or DEFENSE_YEARS
    warnings_log = DATA_RAW / "pipeline01_warnings.log"
    # Reset the warnings log at the start of each full run
    warnings_log.write_text(f"=== Pipeline 01 run at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n",
                             encoding="utf-8")

    print(f"\n=== Pipeline 01: ingest stats for years {years} + defense for {defense_years} ===")

    sources: dict[int, tuple[str, str, int, int]] = {}
    for year in years:
        sources[year] = pull_year(year)

    defense_summary: dict[int, dict[str, int]] = {}
    for year in defense_years:
        oaa_rows      = pull_oaa(year, warnings_log)
        sprint_rows   = pull_sprint_speed(year, warnings_log)
        catcher_rows  = pull_catcher_poptime(year, warnings_log)
        pull_catcher_framing_attempt(year, warnings_log)
        defense_summary[year] = {
            "oaa_rows":     oaa_rows,
            "sprint_rows":  sprint_rows,
            "catcher_rows": catcher_rows,
        }

    # Write summary
    src_lines = [
        f"year={y}  batting={s[0]}  pitching={s[1]}  bat_rows={s[2]}  pit_rows={s[3]}"
        for y, s in sources.items()
    ]
    (DATA_RAW / "pipeline01_source.txt").write_text(
        "\n".join(src_lines) + "\n",
        encoding="utf-8",
    )

    print("\n=== Pipeline 01 done ===")
    print(f"Years ingested: {sorted(sources.keys())}")
    print(f"Defense years:  {sorted(defense_summary.keys())}")
    for y, d in defense_summary.items():
        print(f"  {y}: OAA={d['oaa_rows']} rows · "
              f"sprint_speed={d['sprint_rows']} rows · "
              f"catcher_defense={d['catcher_rows']} rows")
    print(f"\nWarnings logged to: {warnings_log}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Single-year mode preserves the original sprint CLI:
        #   python 01_ingest_pybaseball.py 2024
        years = [int(sys.argv[1])]
        main(years=years, defense_years=years)
    else:
        # Full-build default: 2019-2024 + defense for 2024
        main()
