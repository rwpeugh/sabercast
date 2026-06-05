"""Pipeline 02d -- pull per-team committed payroll totals from Spotrac.

Why this pipeline exists. Pipeline 02 (Spotrac top-contracts scrape) and 02c
(Spotrac FA tracker) together produce ~1,254 contracts skewed toward the
high-AAV end. When the Gap Filler tries to compute a team's committed payroll
by summing those rows, it under-counts reality by ~50-60% because the dataset
misses league-minimum, pre-arbitration, and most arb-eligible players.

This pipeline goes around the problem by pulling Spotrac's own per-team
PAYROLL TOTAL directly from their team payroll pages -- one authoritative
number per team that already includes every player on the active roster
(plus retained payroll for traded/released players). The team payroll
pages are derived from Spotrac's full database, which is what we don't
have a clean ingest for.

Source page format:
    https://www.spotrac.com/mlb/<team-slug>/payroll/_/year/<YYYY>/
Each page renders a section labelled "YYYY Active Roster Payroll" with a
dollar figure beside it. We capture both that number and the smaller
"YYYY Retained Payroll" (money still owed to traded/released players),
sum them, and save to ``data/raw/team_payrolls_<year>.csv``.

The Gap Filler's ``compute_committed_payroll`` will prefer this CSV
when present and fall back to summing the per-contract data when not.

Run from the project root:
    python pipelines/02d_pull_team_payrolls.py 2025
    python pipelines/02d_pull_team_payrolls.py 2024   # historical

Idempotent. Re-running overwrites the CSV.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR      = PROJECT_ROOT / "data" / "raw"

USER_AGENT = "Mozilla/5.0 (compatible; sabercast-research/1.0)"


# Map MLB team abbreviation -> Spotrac URL slug.
SPOTRAC_SLUGS: dict[str, str] = {
    "ARI": "arizona-diamondbacks",  "ATL": "atlanta-braves",
    "BAL": "baltimore-orioles",     "BOS": "boston-red-sox",
    "CHC": "chicago-cubs",          "CWS": "chicago-white-sox",
    "CIN": "cincinnati-reds",       "CLE": "cleveland-guardians",
    "COL": "colorado-rockies",      "DET": "detroit-tigers",
    "HOU": "houston-astros",        "KC":  "kansas-city-royals",
    "LAA": "los-angeles-angels",    "LAD": "los-angeles-dodgers",
    "MIA": "miami-marlins",         "MIL": "milwaukee-brewers",
    "MIN": "minnesota-twins",       "NYM": "new-york-mets",
    "NYY": "new-york-yankees",      "OAK": "athletics",   # rebranded -- no city slug
    "PHI": "philadelphia-phillies", "PIT": "pittsburgh-pirates",
    "SD":  "san-diego-padres",      "SEA": "seattle-mariners",
    "SF":  "san-francisco-giants",  "STL": "st-louis-cardinals",
    "TB":  "tampa-bay-rays",        "TEX": "texas-rangers",
    "TOR": "toronto-blue-jays",     "WSH": "washington-nationals",
}


def _parse_dollar(s: str) -> int:
    """'$165,596,493' -> 165_596_493. Returns 0 on parse failure."""
    if not s:
        return 0
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0


@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=2, max=20))
def _pull_team(team_abbr: str, slug: str, year: int) -> dict:
    """Fetch and parse one team page. Returns row dict."""
    url = f"https://www.spotrac.com/mlb/{slug}/payroll/_/year/{year}/"
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(separator="\n")

    # Capture ALL "(amount) YEAR <Label>" triples on the page, then pick the
    # ones whose label exactly matches "Active Roster Payroll" /
    # "Retained Payroll" for the requested year. The page also lists
    # 26-man / luxury-tax payrolls and historical years -- we ignore those.
    triples = re.findall(r"(\$[\d,]+)\s*\n+\s*(\d{4})\s+([\w\s]+?Payroll)", text)
    active = 0
    retained = 0
    for amount_str, yr_str, label in triples:
        if int(yr_str) != year:
            continue
        label = label.strip()
        if label.lower() == "active roster payroll" and active == 0:
            active = _parse_dollar(amount_str)
        elif label.lower() == "retained payroll" and retained == 0:
            retained = _parse_dollar(amount_str)

    return {
        "team_abbr":           team_abbr,
        "year":                year,
        "active_payroll":      active,
        "retained_payroll":    retained,
        "committed_total":     active + retained,
        "source_url":          url,
        "snapshot_date":       str(date.today()),
    }


def main() -> None:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    out_path = OUT_DIR / f"team_payrolls_{year}.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    for team_abbr, slug in SPOTRAC_SLUGS.items():
        print(f"  {team_abbr:<3}  fetching ...", end=" ", flush=True)
        try:
            row = _pull_team(team_abbr, slug, year)
            rows.append(row)
            print(f"active=${row['active_payroll']/1e6:>6.1f}M  "
                  f"retained=${row['retained_payroll']/1e6:>4.1f}M  "
                  f"total=${row['committed_total']/1e6:>6.1f}M")
        except Exception as e:                                  # noqa: BLE001
            print(f"FAILED ({type(e).__name__}: {e})")
            rows.append({
                "team_abbr": team_abbr, "year": year,
                "active_payroll": 0, "retained_payroll": 0,
                "committed_total": 0,
                "source_url": f"https://www.spotrac.com/mlb/{slug}/payroll/_/year/{year}/",
                "snapshot_date": str(date.today()),
            })
        # Be polite to Spotrac
        time.sleep(0.6)

    df = pd.DataFrame(rows).sort_values("team_abbr").reset_index(drop=True)
    df.to_csv(out_path, index=False, encoding="utf-8")
    print()
    print(f"saved {out_path}  ({len(df)} teams)")
    print(f"file size: {out_path.stat().st_size / 1024:.1f} KB")

    # Sanity print -- top 5 by committed payroll
    print("\nTop 5 committed-payroll teams (sanity check):")
    for _, r in df.nlargest(5, "committed_total").iterrows():
        print(f"   {r['team_abbr']:<3}  ${r['committed_total']/1e6:>6.1f}M")


if __name__ == "__main__":
    main()
