#!/usr/bin/env python3
"""Analyze parking-search duration output."""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd


def main(path: Path) -> None:
    df = pd.read_csv(path)
    valid = pd.to_numeric(df["search_time"], errors="coerce").dropna()
    if valid.empty:
        print("No valid search_time values found.")
        return
    print("Vehicles:", len(df))
    print("Rerouted vehicles:", (pd.to_numeric(df["num_parking_changes"], errors="coerce") > 0).sum())
    print("Mean search time:", valid.mean())
    print("Median search time:", valid.median())
    print("95th percentile:", valid.quantile(0.95))
    print("Max search time:", valid.max())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="output/runtime/synthetic_test/search_times.csv")
    args = parser.parse_args()
    main(Path(args.path))
