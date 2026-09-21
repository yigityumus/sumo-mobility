#!/usr/bin/env python3
"""Allow passenger vehicles wherever delivery vehicles are allowed."""

from __future__ import annotations

import argparse
import gzip
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import BinaryIO


def is_gzip_path(path: Path) -> bool:
    """Return True even for temporary names such as file.xml.gz.tmp."""
    return ".gz" in path.suffixes


def open_input(path: Path) -> BinaryIO:
    if is_gzip_path(path):
        return gzip.open(path, "rb")
    return path.open("rb")


def open_output(path: Path) -> BinaryIO:
    path.parent.mkdir(parents=True, exist_ok=True)

    if is_gzip_path(path):
        return gzip.open(path, "wb", compresslevel=9)
    return path.open("wb")


def default_output_path(input_path: Path) -> Path:
    name = input_path.name

    if name.endswith(".net.xml.gz"):
        output_name = (
            name[: -len(".net.xml.gz")]
            + ".passenger.net.xml.gz"
        )
    elif name.endswith(".net.xml"):
        output_name = (
            name[: -len(".net.xml")]
            + ".passenger.net.xml"
        )
    else:
        output_name = name + ".passenger"

    return input_path.with_name(output_name)


def update_permissions(
    input_path: Path,
    output_path: Path,
) -> tuple[int, int, int]:
    """
    Add passenger permission wherever delivery is permitted.

    Returns:
        total_changed, external_changed, internal_changed
    """
    parser = ET.XMLParser(
        target=ET.TreeBuilder(insert_comments=True)
    )

    with open_input(input_path) as input_file:
        tree = ET.parse(input_file, parser=parser)

    changed_total = 0
    changed_external = 0
    changed_internal = 0

    for lane in tree.iterfind(".//lane"):
        lane_id = lane.get("id", "")
        changed = False

        allow_value = lane.get("allow")
        if allow_value:
            allowed = allow_value.split()

            if "delivery" in allowed and "passenger" not in allowed:
                delivery_index = allowed.index("delivery")
                allowed.insert(delivery_index, "passenger")
                lane.set("allow", " ".join(allowed))
                changed = True

        disallow_value = lane.get("disallow")
        if disallow_value:
            disallowed = disallow_value.split()

            # Delivery is permitted, but passenger is explicitly blocked.
            if (
                "passenger" in disallowed
                and "delivery" not in disallowed
            ):
                disallowed.remove("passenger")

                if disallowed:
                    lane.set("disallow", " ".join(disallowed))
                else:
                    lane.attrib.pop("disallow", None)

                changed = True

        if changed:
            changed_total += 1

            if lane_id.startswith(":"):
                changed_internal += 1
            else:
                changed_external += 1

    with open_output(output_path) as output_file:
        tree.write(
            output_file,
            encoding="UTF-8",
            xml_declaration=True,
        )

    return changed_total, changed_external, changed_internal


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Add passenger permission to every SUMO lane that "
            "allows delivery vehicles."
        )
    )
    parser.add_argument(
        "network",
        type=Path,
        help="Input SUMO .net.xml or .net.xml.gz file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Output network path. Defaults to a "
            "*.passenger.net.xml[.gz] file."
        ),
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help=(
            "Replace the input network after creating a .bak backup."
        ),
    )
    args = parser.parse_args()

    input_path = args.network.expanduser().resolve()

    if not input_path.is_file():
        raise FileNotFoundError(
            f"Network file not found: {input_path}"
        )

    if args.in_place and args.output is not None:
        raise ValueError(
            "Use either --in-place or --output, not both."
        )

    if args.in_place:
        backup_path = input_path.with_name(
            input_path.name + ".bak"
        )

        if backup_path.exists():
            raise FileExistsError(
                f"Backup already exists: {backup_path}\n"
                "Remove or rename it before running again."
            )

        temporary_path = input_path.with_name(
            input_path.name + ".tmp"
        )

        total, external, internal = update_permissions(
            input_path,
            temporary_path,
        )

        shutil.copy2(input_path, backup_path)
        temporary_path.replace(input_path)

        output_path = input_path
        print(f"Backup: {backup_path}")
    else:
        output_path = (
            args.output.expanduser().resolve()
            if args.output is not None
            else default_output_path(input_path)
        )

        total, external, internal = update_permissions(
            input_path,
            output_path,
        )

    print(f"Wrote: {output_path}")
    print(f"Changed lanes: {total}")
    print(f"  External lanes: {external}")
    print(f"  Internal lanes: {internal}")


if __name__ == "__main__":
    main()
