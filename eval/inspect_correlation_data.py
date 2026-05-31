"""Examine the correlation_table.csv to understand why r is near zero."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

df = pd.read_csv(ROOT / "eval/results/correlation_table.csv", encoding="utf-8")
print(f"N rows: {len(df)}")
print(f"Years:  {sorted(df['year'].unique())}")
print()

print("Gap score distribution:")
print(f"  min   : {df['gap_score'].min():.2f}")
print(f"  q25   : {df['gap_score'].quantile(0.25):.2f}")
print(f"  median: {df['gap_score'].median():.2f}")
print(f"  q75   : {df['gap_score'].quantile(0.75):.2f}")
print(f"  max   : {df['gap_score'].max():.2f}")
print(f"  std   : {df['gap_score'].std():.2f}")
print()

print("Wins distribution:")
print(f"  min   : {df['next_year_wins'].min()}")
print(f"  median: {df['next_year_wins'].median()}")
print(f"  max   : {df['next_year_wins'].max()}")
print(f"  std   : {df['next_year_wins'].std():.2f}")
print()

print("Top gap position frequency (all years pooled):")
print(df["top_gap_position"].value_counts().to_string())
print()

print("Top-10 hits in expected direction (high gap + low wins):")
m = df.assign(score=df["gap_score"] - df["next_year_wins"] / 5).sort_values("score", ascending=False)
print(m.head(10)[["year", "team", "gap_score", "next_year_wins", "top_gap_position"]].to_string(index=False))
print()
print("Top-10 misses (high gap + high wins — anti-correlation):")
m = df.assign(score=df["gap_score"] + df["next_year_wins"] / 5).sort_values("score", ascending=False)
print(m.head(10)[["year", "team", "gap_score", "next_year_wins", "top_gap_position"]].to_string(index=False))
