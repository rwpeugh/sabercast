"""Pipeline 02 — Scrape Spotrac MLB contracts.

Pulls the main MLB contracts table from spotrac.com and saves a cleaned CSV
to data/raw/contracts.csv with columns matching the spec:
  player_name, team, position, age, contract_value, aav, years, signed_year

Sprint scope: just the headline table (top-100 contracts by total value).
This covers all position groups with enough comparables for the LLM prompt
context. Clause data and individual player pages are deferred to the post-sprint
Pipeline 02 bonus pass.

Sources tried in order:
  1. https://www.spotrac.com/mlb/contracts/    (main contracts table)

Rate limit: 2 seconds between requests, real User-Agent header.

If the scrape fails for any reason, this script writes a manual-fallback CSV
template at data/raw/contracts_manual_template.csv and exits non-zero so the
caller knows to use the manual list.
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

URL_MAIN = "https://www.spotrac.com/mlb/contracts/"


# Spotrac's team chip renders the abbreviation twice in the rendered HTML
# (icon + label), giving cells like "NYMNYM". Strip the duplicate.
def _dedupe_team(cell: str) -> str:
    cell = cell.strip()
    if len(cell) >= 4 and len(cell) % 2 == 0:
        half = len(cell) // 2
        if cell[:half] == cell[half:]:
            return cell[:half]
    return cell


def _parse_money(s: str) -> float | None:
    """'$765,000,000' -> 765000000.0; returns None if unparseable."""
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
    try:
        return int(re.sub(r"[^\d-]", "", s))
    except (ValueError, TypeError):
        return None


def fetch_main_table() -> pd.DataFrame:
    print(f"GET {URL_MAIN}")
    time.sleep(2)  # rate limit before first request as well
    r = requests.get(URL_MAIN, headers=HEADERS, timeout=30)
    r.raise_for_status()
    print(f"  HTTP {r.status_code}, {len(r.text):,} bytes")

    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError("No <table> found in Spotrac main contracts page")

    rows = table.find_all("tr")
    if len(rows) < 2:
        raise RuntimeError(f"Spotrac table has only {len(rows)} rows")

    # Parse header
    header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    print(f"  Header: {header_cells}")

    data = []
    for row in rows[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cells) < 8:
            continue
        data.append(cells[:8])

    df = pd.DataFrame(data, columns=[
        "player_name", "position", "team_raw", "age_at_signing",
        "start_year", "end_year", "years", "contract_value_raw",
    ])
    print(f"  Parsed {len(df)} contract rows")
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["team"]            = df["team_raw"].apply(_dedupe_team)
    df["age"]             = df["age_at_signing"].apply(_parse_int)
    df["signed_year"]     = df["start_year"].apply(_parse_int)
    df["years"]           = df["years"].apply(_parse_int)
    df["contract_value"]  = df["contract_value_raw"].apply(_parse_money)
    df["aav"] = df.apply(
        lambda r: r["contract_value"] / r["years"]
        if r["contract_value"] and r["years"] else None,
        axis=1,
    )
    out = df[[
        "player_name", "team", "position", "age",
        "contract_value", "aav", "years", "signed_year",
    ]].copy()
    return out


def write_manual_template() -> None:
    template = pd.DataFrame(columns=[
        "player_name", "team", "position", "age",
        "contract_value", "aav", "years", "signed_year",
    ])
    template.to_csv(DATA_RAW / "contracts_manual_template.csv", index=False, encoding="utf-8")
    print("  wrote contracts_manual_template.csv (empty schema)")


def main() -> int:
    print("=== Pipeline 02: Scrape Spotrac MLB contracts ===")
    try:
        raw = fetch_main_table()
        clean_df = clean(raw)
    except Exception as e:                              # noqa: BLE001
        print(f"\n[FAIL] Spotrac scrape error: {type(e).__name__}: {e}")
        print("Writing manual template instead. Populate by hand if needed.")
        write_manual_template()
        return 1

    out_path = DATA_RAW / "contracts.csv"
    clean_df.to_csv(out_path, index=False, encoding="utf-8")
    print(f"\nSaved {out_path.name}: {len(clean_df)} contracts")
    print("\nPosition distribution:")
    print(clean_df["position"].value_counts().to_string())
    print("\nTop 5 by AAV:")
    print(clean_df.sort_values("aav", ascending=False).head(5)
          [["player_name", "team", "position", "years", "contract_value", "aav", "signed_year"]]
          .to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
