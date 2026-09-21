#!/usr/bin/env python3
"""Generate the SUMO configuration for one model simulation run."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import yaml

BACKEND_ROOT = Path(__file__).resolve().parents[3]
GUI_SETTINGS_PATH = BACKEND_ROOT / "sumo" / "config" / "osm.view.xml"


def indent(element: ET.Element, level: int = 0) -> None:
    """Apply readable indentation to an XML element tree."""
    indentation = "\n" + level * "    "

    if len(element):
        if not element.text or not element.text.strip():
            element.text = indentation + "    "

        for child in element:
            indent(child, level + 1)

        if not child.tail or not child.tail.strip():
            child.tail = indentation

    if level and (not element.tail or not element.tail.strip()):
        element.tail = indentation


def resolve_project_path(path: Path) -> Path:
    """Resolve a path relative to the project root when necessary."""
    if path.is_absolute():
        return path.resolve()

    return (BACKEND_ROOT / path).resolve()


def relative_to_sumocfg(target: Path, sumocfg_path: Path) -> str:
    """
    Return a path relative to the directory containing the generated
    SUMO configuration.
    """
    return os.path.relpath(
        target.resolve(),
        start=sumocfg_path.parent.resolve(),
    )


def generate(
    config_path: Path,
    *,
    output_path: Path,
    network_path: Path,
    polygons_path: Path,
    passenger_routes_path: Path,
    pedestrian_routes_path: Path,
    parking_config_path: Path,
    detectors_path: Path | None = None,
) -> Path:
    """Generate and write the SUMO configuration file."""
    config_path = resolve_project_path(config_path)

    if not config_path.is_file():
        raise FileNotFoundError(
            f"Scenario configuration does not exist: {config_path}"
        )

    config = yaml.safe_load(
        config_path.read_text(encoding="utf-8")
    ) or {}

    simulation = config.get("simulation")
    if not isinstance(simulation, dict):
        raise ValueError(
            f"Missing or invalid 'simulation' section in {config_path}"
        )

    if "end" not in simulation:
        raise ValueError(
            f"Missing required 'simulation.end' value in {config_path}"
        )

    network_path = resolve_project_path(network_path)
    output_path = resolve_project_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    polygons_path = resolve_project_path(polygons_path)
    passenger_routes_path = resolve_project_path(passenger_routes_path)
    pedestrian_routes_path = resolve_project_path(pedestrian_routes_path)
    parking_config_path = resolve_project_path(parking_config_path)
    detectors_path = resolve_project_path(detectors_path) if detectors_path else None

    parking_config = yaml.safe_load(
        parking_config_path.read_text(encoding="utf-8")
    ) or {}

    parking_areas = parking_config.get("parking_areas", [])

    if not isinstance(parking_areas, list):
        raise ValueError(
            f"'parking_areas' must be a list in {parking_config_path}"
        )

    enabled_parking_areas = [
        parking
        for parking in parking_areas
        if parking.get("enabled", True)
    ]

    parking_additional_paths: list[Path] = []

    for parking in enabled_parking_areas:
        logical_id = parking.get("id", "<unknown>")

        additional_path = parking.get("additional_path")

        if additional_path:
            parking_additional_paths.append(
                resolve_project_path(Path(str(additional_path)))
            )
        else:
            raise ValueError(
                f"Parking area '{logical_id}' is missing "
                "'additional_path'"
            )

    gui_settings_path = GUI_SETTINGS_PATH

    required_inputs = [
        network_path,
        passenger_routes_path,
        pedestrian_routes_path,
        *parking_additional_paths,
    ]

    missing_inputs = [
        path for path in required_inputs if not path.is_file()
    ]

    if missing_inputs:
        formatted = "\n".join(
            f"  - {path}" for path in missing_inputs
        )
        raise FileNotFoundError(
            "Cannot generate SUMO configuration because these "
            f"required files are missing:\n{formatted}"
        )

    root = ET.Element(
        "configuration",
        {
            "xmlns:xsi": (
                "http://www.w3.org/2001/XMLSchema-instance"
            ),
            "xsi:noNamespaceSchemaLocation": (
                "http://sumo.dlr.de/xsd/"
                "sumoConfiguration.xsd"
            ),
        },
    )

    input_element = ET.SubElement(root, "input")

    ET.SubElement(
        input_element,
        "net-file",
        {
            "value": relative_to_sumocfg(
                network_path,
                output_path,
            )
        },
    )

    route_files = [
        relative_to_sumocfg(
            passenger_routes_path,
            output_path,
        ),
        relative_to_sumocfg(
            pedestrian_routes_path,
            output_path,
        ),
    ]

    ET.SubElement(
        input_element,
        "route-files",
        {"value": ",".join(route_files)},
    )

    additional_files = [
        relative_to_sumocfg(
            parking_path,
            output_path,
        )
        for parking_path in parking_additional_paths
    ]
    if polygons_path.is_file():
        additional_files.append(relative_to_sumocfg(polygons_path, output_path))
    if detectors_path and detectors_path.is_file():
        additional_files.append(relative_to_sumocfg(detectors_path, output_path))

    ET.SubElement(
        input_element,
        "additional-files",
        {
            "value": ",".join(additional_files)
        },
    )


    time_element = ET.SubElement(root, "time")

    ET.SubElement(
        time_element,
        "begin",
        {"value": str(simulation.get("begin", 0))},
    )

    ET.SubElement(
        time_element,
        "end",
        {"value": str(simulation["end"])},
    )

    ET.SubElement(
        time_element,
        "step-length",
        {"value": str(simulation.get("step_length", 1))},
    )

    report_element = ET.SubElement(root, "report")

    ET.SubElement(
        report_element,
        "verbose",
        {"value": "true"},
    )

    ET.SubElement(
        report_element,
        "no-step-log",
        {"value": "true"},
    )

    # GUI settings are optional for command-line SUMO, but include them
    # when the configured file exists.
    if gui_settings_path.is_file():
        gui_element = ET.SubElement(root, "gui_only")

        ET.SubElement(
            gui_element,
            "gui-settings-file",
            {
                "value": relative_to_sumocfg(
                    gui_settings_path,
                    output_path,
                )
            },
        )

    indent(root)

    ET.ElementTree(root).write(
        output_path,
        encoding="UTF-8",
        xml_declaration=True,
    )

    print(f"Wrote {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a model run's SUMO configuration."
    )

    parser.add_argument(
        "--config",
        type=Path,
        required=True,
    )

    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--polygons", type=Path, required=True)
    parser.add_argument("--passenger-routes", type=Path, required=True)
    parser.add_argument("--pedestrian-routes", type=Path, required=True)
    parser.add_argument("--parking-config", type=Path, required=True)
    parser.add_argument("--detectors", type=Path)

    arguments = parser.parse_args()
    generate(
        arguments.config,
        output_path=arguments.output,
        network_path=arguments.network,
        polygons_path=arguments.polygons,
        passenger_routes_path=arguments.passenger_routes,
        pedestrian_routes_path=arguments.pedestrian_routes,
        parking_config_path=arguments.parking_config,
        detectors_path=arguments.detectors,
    )


if __name__ == "__main__":
    main()
