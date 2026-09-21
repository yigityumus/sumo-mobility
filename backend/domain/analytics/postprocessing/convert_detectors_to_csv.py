#!/usr/bin/env python3
"""
Convert SUMO detector outputs (XML) to CSV.

Supports common SUMO additional-output formats such as:
- Induction loops (E1): <interval .../> records
- Lane-area detectors (E2): <interval .../> records
- Entry/exit detectors (E3): <interval .../> records

Usage (from project root):
  python postprocessing/convert_detectors_to_csv.py

Optional:
  python postprocessing/convert_detectors_to_csv.py --in-dir output/detectors --out-dir output/detectors
  python postprocessing/convert_detectors_to_csv.py --e1 E1.xml --e2 E2.xml --e3 E3.xml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

import pandas as pd


def parse_intervals(xml_path: Path) -> pd.DataFrame:
    """
    Parse all <interval ...> elements into a DataFrame.
    Keeps all attributes as columns.
    Adds:
      - source_file
      - record_type (the interval tag name; usually 'interval')
    """
    if not xml_path.exists():
        raise FileNotFoundError(f"Missing file: {xml_path}")

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        raise ValueError(f"Could not parse XML: {xml_path}\n{e}") from e

    root = tree.getroot()

    rows: list[dict] = []

    # Most SUMO detector outputs store measurements in <interval .../>
    for elem in root.iter():
        if elem.tag != "interval":
            continue

        row = dict(elem.attrib)

        # Normalize common detector id keys (varies by output type / SUMO version)
        # Some outputs use 'id', some use 'detector', some embed ids differently.
        if "detector_id" not in row:
            if "id" in row:
                row["detector_id"] = row["id"]
            elif "detector" in row:
                row["detector_id"] = row["detector"]
            # else: leave detector_id absent; still useful if file has single detector

        # Try to coerce begin/end if present
        # We'll coerce numerics later too, but begin/end are especially common.
        row["source_file"] = xml_path.name
        row["record_type"] = elem.tag

        rows.append(row)

    if not rows:
        # Some SUMO outputs can use different tags, but E1/E2/E3 use interval.
        # If this triggers, upload a sample file and I’ll adapt the parser.
        raise ValueError(
            f"No <interval> elements found in {xml_path}. "
            "This file may not be a standard E1/E2/E3 detector output."
        )

    df = pd.DataFrame(rows)

    # Convert numeric-looking columns to numbers (best effort)
    for col in df.columns:
        if col in ("source_file", "record_type"):
            continue
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass

    # Prefer consistent ordering if columns exist
    preferred = [c for c in ["detector_id", "begin", "end", "source_file"] if c in df.columns]
    remaining = [c for c in df.columns if c not in preferred]
    df = df[preferred + remaining]

    return df


def convert_one(xml_path: Path, csv_path: Path) -> None:
    df = parse_intervals(xml_path)

    # Common helpful sort (if these fields exist)
    sort_cols = [c for c in ["detector_id", "begin", "end"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, kind="mergesort")

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    print(f"Wrote {csv_path} ({len(df)} rows)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert SUMO detector XML outputs to CSV.")
    parser.add_argument("--in-dir", type=str, default="output/detectors",
                        help="Directory containing detector XML outputs (default: output/detectors)")
    parser.add_argument("--out-dir", type=str, default="output/detectors",
                        help="Directory to write CSVs to (default: output/detectors)")

    # Allow explicit filenames if you prefer
    parser.add_argument("--e1", type=str, default="E1.xml", help="E1 XML filename (default: E1.xml)")
    parser.add_argument(
        "--e2",
        type=str,
        default="e2_pedestrians.xml",
        help="Pedestrian E2 XML filename (default: e2_pedestrians.xml)",
    )
    parser.add_argument("--e3", type=str, default="E3.xml", help="E3 XML filename (default: E3.xml)")

    args = parser.parse_args()

    in_dir = Path(args.in_dir)
    out_dir = Path(args.out_dir)

    e1_xml = in_dir / args.e1
    e2_xml = in_dir / args.e2
    e3_xml = in_dir / args.e3

    # Output names
    e1_csv = out_dir / (Path(args.e1).stem + ".csv")
    e2_csv = out_dir / (Path(args.e2).stem + ".csv")
    e3_csv = out_dir / (Path(args.e3).stem + ".csv")

    # Convert what exists; fail clearly if neither exists
    converted_any = False
    if e1_xml.exists():
        convert_one(e1_xml, e1_csv)
        converted_any = True
    else:
        print(f"Skip: {e1_xml} not found")

    if e2_xml.exists():
        convert_one(e2_xml, e2_csv)
        converted_any = True
    else:
        print(f"Skip: {e2_xml} not found")

    if e3_xml.exists():
        convert_one(e3_xml, e3_csv)
        converted_any = True
    else:
        print(f"Skip: {e3_xml} not found")

    if not converted_any:
        print(
            f"No detector XML files found in {in_dir}. "
            f"Expected {args.e1}, {args.e2}, and/or {args.e3}."
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
