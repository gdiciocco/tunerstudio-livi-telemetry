from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livi_bridge.schema import validate_field_path
from livi_bridge.tunerstudio_ini import generate_usbmon_config_from_field_map


def load_field_map(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"{path} is empty")

        fieldnames = {name.strip(): name for name in reader.fieldnames}
        livi_key = fieldnames.get("livi_field")
        tunerstudio_key = fieldnames.get("tunerstudio_field")
        if livi_key is None or tunerstudio_key is None:
            raise ValueError("TSV must contain columns: livi_field, tunerstudio_field")

        field_map: dict[str, str] = {}
        for line_number, row in enumerate(reader, start=2):
            livi_field = (row.get(livi_key) or "").strip()
            tunerstudio_field = (row.get(tunerstudio_key) or "").strip()
            if not livi_field:
                continue
            try:
                validate_field_path(livi_field)
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
            field_map[livi_field] = tunerstudio_field

    return field_map


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    project_root = default_project_root()
    parser = argparse.ArgumentParser(
        description="Update the LIVI usbmon JSON from a livi_field/tunerstudio_field TSV map."
    )
    parser.add_argument(
        "--field-map",
        type=Path,
        default=project_root / "livi-tunerstudio-field-map.tsv",
        help="TSV with columns livi_field and tunerstudio_field.",
    )
    parser.add_argument(
        "--tunerstudio-ini",
        type=Path,
        required=True,
        help="TunerStudio mainController.ini used to resolve offsets and scaling.",
    )
    parser.add_argument(
        "--custom-ini",
        type=Path,
        action="append",
        default=[],
        help="Additional custom.ini file with calculated OutputChannels. Can be used more than once.",
    )
    parser.add_argument(
        "--inc-dir",
        type=Path,
        action="append",
        default=[],
        help="Directory containing .inc lookup tables referenced by custom.ini. Can be used more than once.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=project_root / "generated-usbmon-from-mainController.json",
        help="Output JSON file to update.",
    )
    parser.add_argument(
        "--endian",
        choices=["big", "little"],
        default="little",
        help="Endian for binary scalar values.",
    )
    args = parser.parse_args(argv)

    field_map = load_field_map(args.field_map)
    config, warnings = generate_usbmon_config_from_field_map(
        ini_path=args.tunerstudio_ini,
        field_map=field_map,
        endian=args.endian,
        custom_ini_paths=args.custom_ini,
        inc_dirs=args.inc_dir,
    )
    args.output.write_text(json.dumps(config, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"wrote {len(config['usbmon']['fields'])} fields to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
