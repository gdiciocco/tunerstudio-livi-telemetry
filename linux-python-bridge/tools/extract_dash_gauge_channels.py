from __future__ import annotations

import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True)
class GaugeChannel:
    output_channel: str
    title: str


def extract_gauge_channels(path: Path) -> list[GaugeChannel]:
    tree = ET.parse(path)
    root = tree.getroot()
    namespace = _namespace(root.tag)
    dash_comp_name = _qualified("dashComp", namespace)
    output_channel_name = _qualified("OutputChannel", namespace)
    title_name = _qualified("Title", namespace)
    pairs: list[GaugeChannel] = []

    for dash_comp in root.iter(dash_comp_name):
        if dash_comp.get("type") != "Gauge":
            continue
        output_channel = _child_text(dash_comp, output_channel_name)
        title = _child_text(dash_comp, title_name)
        if output_channel or title:
            pairs.append(GaugeChannel(output_channel=output_channel, title=title))

    return pairs


def write_pairs(pairs: list[GaugeChannel], handle: TextIO, output_format: str) -> None:
    if output_format == "tsv":
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["OutputChannel", "Title"])
        for pair in pairs:
            writer.writerow([pair.output_channel, pair.title])
        return

    for pair in pairs:
        handle.write(f"{pair.output_channel}: {pair.title}\n")


def _namespace(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1 : tag.index("}")]
    return ""


def _qualified(name: str, namespace: str) -> str:
    return f"{{{namespace}}}{name}" if namespace else name


def _child_text(parent: ET.Element, child_name: str) -> str:
    child = parent.find(child_name)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract OutputChannel/Title pairs from TunerStudio Gauge dashComp elements."
    )
    parser.add_argument("dash_file", type=Path, help="TunerStudio .dsh/.xml dashboard file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file. Defaults to stdout.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "tsv"],
        default="text",
        help="Output format. text writes 'OutputChannel: Title'.",
    )
    args = parser.parse_args(argv)

    pairs = extract_gauge_channels(args.dash_file)
    if args.output is None:
        write_pairs(pairs, sys.stdout, args.format)
    else:
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            write_pairs(pairs, handle, args.format)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
