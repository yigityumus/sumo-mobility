#!/usr/bin/env python3
"""Build a SUMO network from a local OpenStreetMap file."""

from __future__ import annotations

import argparse
import gzip
import shutil
import subprocess
from pathlib import Path
import os

from .passenger_permissions import update_permissions


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SUPPORTED_OSM_SUFFIXES = (
    ".osm.xml.gz",
    ".osm.gz",
    ".osm.xml",
    ".osm",
)


POLY_TYPEMAP_FILENAME = "osmPolyconvert.typ.xml"


def find_default_poly_typemap() -> Path:
    """Locate SUMO's default OSM polygon typemap."""

    candidates: list[Path] = []

    sumo_home = os.environ.get("SUMO_HOME")

    if sumo_home:
        home = Path(sumo_home).expanduser()

        candidates.extend(
            [
                home / "data" / "typemap" / POLY_TYPEMAP_FILENAME,
                home
                / "share"
                / "sumo"
                / "data"
                / "typemap"
                / POLY_TYPEMAP_FILENAME,
            ]
        )

    polyconvert = shutil.which("polyconvert")

    if polyconvert:
        executable = Path(polyconvert).resolve()

        for parent in executable.parents:
            candidates.extend(
                [
                    parent
                    / "data"
                    / "typemap"
                    / POLY_TYPEMAP_FILENAME,
                    parent
                    / "share"
                    / "sumo"
                    / "data"
                    / "typemap"
                    / POLY_TYPEMAP_FILENAME,
                ]
            )

    candidates.append(
        Path("/usr/share/sumo/data/typemap")
        / POLY_TYPEMAP_FILENAME
    )

    checked: set[Path] = set()

    for candidate in candidates:
        candidate = candidate.resolve()

        if candidate in checked:
            continue

        checked.add(candidate)

        if candidate.is_file():
            return candidate

    checked_paths = "\n".join(
        f"  - {candidate}"
        for candidate in sorted(checked)
    )

    raise FileNotFoundError(
        "Could not find SUMO's default polygon typemap.\n"
        f"Expected file: {POLY_TYPEMAP_FILENAME}\nChecked:\n"
        f"{checked_paths}\n\n"
        "Set SUMO_HOME or pass --poly-typemap explicitly."
    )


def get_source_name(osm_file: Path) -> str:
    """Return the filename without its OSM-specific extension."""

    filename = osm_file.name
    lowercase_filename = filename.lower()

    for suffix in SUPPORTED_OSM_SUFFIXES:
        if lowercase_filename.endswith(suffix):
            source_name = filename[: -len(suffix)]

            if not source_name:
                raise ValueError(
                    f"Could not determine source name from: {filename}"
                )

            return source_name

    raise ValueError(
        "Unsupported OSM filename. Expected one of: "
        ".osm, .osm.xml, .osm.gz, or .osm.xml.gz"
    )


def require_program(name: str) -> str:
    executable = shutil.which(name)

    if executable is None:
        raise RuntimeError(
            f"Required SUMO program was not found in PATH: {name}"
        )

    return executable


def ensure_output_is_safe(path: Path, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(
            f"Output already exists: {path}\n"
            "Use --force to replace existing files."
        )


def copy_osm_as_gzip(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    if source.suffix.lower() == ".gz":
        shutil.copy2(source, destination)
        return

    with source.open("rb") as input_file:
        with gzip.open(destination, "wb") as output_file:
            shutil.copyfileobj(input_file, output_file)


def run_command(command: list[str]) -> None:
    print()
    print("Running:")
    print(" ".join(command))

    subprocess.run(
        command,
        check=True,
        cwd=PROJECT_ROOT,
    )


def build_network(
    osm_file: Path,
    *,
    force: bool,
    with_polygons: bool,
    poly_typemap: Path | None,
    network_output: Path,
    osm_output: Path,
    polygon_output: Path | None = None,
    allow_passenger_on_delivery: bool = False,
) -> None:
    osm_file = osm_file.expanduser().resolve()

    if not osm_file.is_file():
        raise FileNotFoundError(f"OSM file not found: {osm_file}")

    source_name = get_source_name(osm_file)

    osm_output = osm_output.expanduser().resolve()
    network_output = network_output.expanduser().resolve()

    generate_polygons = with_polygons or poly_typemap is not None
    if generate_polygons and polygon_output is None:
        raise ValueError("--polygon-output is required when generating polygons.")
    if polygon_output is not None:
        polygon_output = polygon_output.expanduser().resolve()

    resolved_poly_typemap: Path | None = None

    if generate_polygons:
        if poly_typemap is not None:
            resolved_poly_typemap = poly_typemap.expanduser().resolve()

            if not resolved_poly_typemap.is_file():
                raise FileNotFoundError(
                    f"Polygon typemap not found: "
                    f"{resolved_poly_typemap}"
                )
        else:
            resolved_poly_typemap = find_default_poly_typemap()

    netconvert = require_program("netconvert")

    if generate_polygons:
        require_program("polyconvert")

    ensure_output_is_safe(osm_output, force)
    ensure_output_is_safe(network_output, force)

    if generate_polygons:
        ensure_output_is_safe(polygon_output, force)

    osm_output.parent.mkdir(parents=True, exist_ok=True)
    network_output.parent.mkdir(parents=True, exist_ok=True)
    if generate_polygons:
        polygon_output.parent.mkdir(parents=True, exist_ok=True)

    copy_osm_as_gzip(
        source=osm_file,
        destination=osm_output,
    )

    network_command = [
        netconvert,
        "--osm-files",
        str(osm_output),
        "--output-file",
        str(network_output),
        "--geometry.remove",
        "--ramps.guess",
        "--junctions.join",
        "--tls.guess-signals",
        "--tls.discard-simple",
        "--tls.join",
        "--tls.default-type",
        "actuated",
        "--osm.sidewalks",
        "--crossings.guess",
        "--osm.turn-lanes",
        "--output.street-names",
    ]

    run_command(network_command)

    if allow_passenger_on_delivery:
        temporary_network = network_output.with_name(network_output.name + ".tmp")
        total, external, internal = update_permissions(
            network_output,
            temporary_network,
        )
        temporary_network.replace(network_output)
        print(
            "Enabled passenger access on delivery lanes: "
            f"{total} changed ({external} external, {internal} internal)."
        )

    if generate_polygons:
        polyconvert = require_program("polyconvert")

        assert resolved_poly_typemap is not None

        polygon_command = [
            polyconvert,
            "--net-file",
            str(network_output),
            "--osm-files",
            str(osm_output),
            "--type-file",
            str(resolved_poly_typemap),
            "--prune.in-net",
            "--output-file",
            str(polygon_output),
        ]

        run_command(polygon_command)

    print()
    print("Network build completed.")
    print(f"Source name:      {source_name}")
    print(f"OSM source:       {osm_output}")
    print(f"SUMO network:     {network_output}")

    if generate_polygons:
        print(f"SUMO polygons:    {polygon_output}")
        print(f"Polygon typemap:  {resolved_poly_typemap}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a SUMO network from an OSM file."
    )

    parser.add_argument(
        "osm_file",
        type=Path,
        help="Input .osm, .osm.xml, .osm.gz, or .osm.xml.gz file.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace files generated previously from the same OSM name.",
    )

    parser.add_argument(
        "--poly-typemap",
        type=Path,
        help=(
            "Use a custom SUMO polygon typemap. "
            "Providing this option also enables polygon generation."
        ),
    )

    parser.add_argument(
        "--with-polygons",
        action="store_true",
        help=(
            "Generate an OSM polygon file using SUMO's default "
            "osmPolyconvert.typ.xml typemap."
        ),
    )

    parser.add_argument("--network-output", type=Path, required=True)
    parser.add_argument("--polygon-output", type=Path)
    parser.add_argument("--osm-output", type=Path, required=True)
    parser.add_argument(
        "--allow-passenger-on-delivery",
        action="store_true",
        help="Allow passenger vehicles on OSM service lanes imported as delivery-only.",
    )

    arguments = parser.parse_args()

    build_network(
        arguments.osm_file,
        force=arguments.force,
        poly_typemap=arguments.poly_typemap,
        with_polygons=arguments.with_polygons,
        network_output=arguments.network_output,
        polygon_output=arguments.polygon_output,
        osm_output=arguments.osm_output,
        allow_passenger_on_delivery=arguments.allow_passenger_on_delivery,
    )


if __name__ == "__main__":
    main()
