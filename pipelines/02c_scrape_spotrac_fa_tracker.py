"""Pipeline 02c — Scrape Spotrac's per-offseason free agent tracker pages.

Why this exists: pipelines/02_scrape_spotrac.py pulls Spotrac's TOP-100 contracts
table (sorted by total value). That's biased toward big stars and misses the
mid-tier signings ($1-15M AAV) that make up most of the actual offseason
market. For the gap-fill correlation test (does filling a Sabercast-flagged
gap correlate with wins improvement?), we need broader coverage.

Spotrac's FA tracker pages at:
    https://www.spotrac.com/mlb/free-agents/_/year/YYYY
list every free agent who became eligible in the YYYY-1 / YYYY offseason. Each
page typically yields 150-200 signed-FA rows. Across 2019-2026 we get ~1000-1500
total rows; after deduping against contracts.csv and filtering to signed deals
we expect ~500-800 net-new contracts.

The scraped data is saved to a SEPARATE file:
    data/raw/contracts_extended.csv

so the original contracts.csv stays byte-stable. This preserves the published
Entry 15 fine-tune MAE numbers ($4.30M baseline / $3.09M ex-Ohtani) — those
analyses key off random.sample(seed=42) against the original 115-contract pool.

The new gap-fill test (eval/gap_fill_test.py) reads BOTH contracts.csv and
contracts_extended.csv to maximize sample size at each (year, team, position).

Schema (matches contracts.csv where possible):
    player_name, team, position, age, contract_value, aav, years, signed_year, source

`age` is NaN for FA-tracker rows (Spotrac's FA pages don't surface age in the
main table). The `source` column distinguishes spotrac_main (existing top-100)
from spotrac_fa_tracker (new) and manual_curation (from 02b).
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
DATA_RAW.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Spotrac year_param maps to the SEASON the FA contract takes effect for.
# So /year/2024 = FAs from the 2023-24 offseason who play in the 2024 season.
# Our existing contracts.csv signed_year matches this convention (Ohtani's
# Dec-2023 contract has signed_year=2024).
YEARS_TO_PULL = list(range(2019, 2027))   # 2019-2026 inclusive

OUT_PATH = DATA_RAW / "contracts_extended.csv"


def _parse_money(s: str) -> float | None:
    if not s:
        return None
    digits = re.sub(r"[^\d.]", "", s)
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _parse_int(s: str) -> int | None:
    if not s:
        return None
    try:
        return int(re.sub(r"[^\d-]", "", s))
    except (ValueError, TypeError):
        return None


# Spotrac's "From" / "To" columns use 3-letter team codes that mostly match
# ours. Common variants:
SPOTRAC_TEAM_NORMALIZE = {
    "WSH": "WSH",
    "WAS": "WSH",
    "AZ":  "ARI",
    "CHW": "CWS",
    "TBR": "TB",
    "SDP": "SD",
    "SFG": "SF",
    "KCR": "KC",
    "JPN": None,   # international origin — not a US team
    "KBO": None,
    "MEX": None,
    "DOM": None,
    "VEN": None,
    "CUB": None,
}


def _normalize_team(raw: str) -> str | None:
    """Return a clean 3-letter team abbrev, or None for non-US origins / blank."""
    s = (raw or "").strip()
    if not s:
        return None
    if s in SPOTRAC_TEAM_NORMALIZE:
        return SPOTRAC_TEAM_NORMALIZE[s]
    # 3-letter team codes pass through unchanged
    if len(s) <= 4 and s.isalpha():
        return s.upper()
    return None


def _clean_player(raw: str) -> str:
    """Strip Spotrac's 'QO' (qualifying offer) marker that appears appended to
    the player name in the FA tracker table."""
    s = (raw or "").strip()
    s = re.sub(r"QO$", "", s).strip()
    return s


def fetch_year(year: int) -> pd.DataFrame:
    url = f"https://www.spotrac.com/mlb/free-agents/_/year/{year}"
    print(f"  GET {url}")
    time.sleep(2)   # courteous rate limit
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        raise RuntimeError(f"No table found in {url}")
    # The main signed-FA table is always the first one; sub-tables show
    # unsigned / retired FAs and have different column structures.
    main = tables[0]
    rows = main.find_all("tr")
    if len(rows) < 2:
        return pd.DataFrame()

    # Header: From, _, To, Player, Pos, Yrs, Value, AAV
    data: list[dict] = []
    for tr in rows[1:]:
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(cells) < 8:
            continue
        from_team, _arrow, to_team, player, position, years, value, aav = cells[:8]
        to_norm = _normalize_team(to_team)
        if to_norm is None:
            # Unsigned, retired, or international destination — skip
            continue
        data.append({
            "player_name":    _clean_player(player),
            "team":           to_norm,
            "from_team":      _normalize_team(from_team),
            "position":       (position or "").strip(),
            "age":            None,   # not in FA tracker table
            "contract_value": _parse_money(value),
            "aav":            _parse_money(aav),
            "years":          _parse_int(years),
            "signed_year":    year,
            "source":         "spotrac_fa_tracker",
        })
    df = pd.DataFrame(data)
    print(f"    parsed {len(df)} signed FA rows")
    return df


def main() -> None:
    print(f"=== Pipeline 02c: scrape Spotrac FA tracker, {YEARS_TO_PULL[0]}-{YEARS_TO_PULL[-1]} ===")
    frames: list[pd.DataFrame] = []
    for year in YEARS_TO_PULL:
        try:
            df = fetch_year(year)
            frames.append(df)
        except Exception as e:                              # noqa: BLE001
            print(f"    [FAIL] {type(e).__name__}: {e}")

    if not frames:
        raise SystemExit("No data scraped — aborting before overwriting output.")

    combined = pd.concat(frames, ignore_index=True)
    print(f"\nTotal scraped: {len(combined)} signed FA rows across {len(YEARS_TO_PULL)} offseasons")
    print(f"  Year distribution:")
    print(combined["signed_year"].value_counts().sort_index().to_string())
    print(f"  Position distribution:")
    print(combined["position"].value_counts().to_string())

    # Cross-check against original contracts.csv: dedupe by (player_name, signed_year)
    original = pd.read_csv(DATA_RAW / "contracts.csv", encoding="utf-8")
    original_keys = set(zip(original["player_name"].astype(str), original["signed_year"]))
    combined["already_in_original"] = combined.apply(
        lambda r: (str(r["player_name"]), r["signed_year"]) in original_keys, axis=1,
    )
    n_new = (~combined["already_in_original"]).sum()
    n_dup = combined["already_in_original"].sum()
    print(f"\n  Overlap with contracts.csv: {n_dup} already-known players (will be excluded)")
    print(f"  NET-NEW signings in contracts_extended.csv: {n_new}")

    new_rows = combined[~combined["already_in_original"]].drop(
        columns=["already_in_original"]
    ).reset_index(drop=True)
    new_rows.to_csv(OUT_PATH, index=False, encoding="utf-8")
    print(f"\nSaved {OUT_PATH} ({len(new_rows)} rows × {len(new_rows.columns)} cols)")


if __name__ == "__main__":
    main()
