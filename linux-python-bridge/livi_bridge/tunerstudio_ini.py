from __future__ import annotations

import json
import re
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .defaults import DEFAULT_CHANNEL_MAP
from .mapper import canonical_channel
from .usbmon_decoder import BinaryFieldRule, FixedFrameDecoder


TS_TYPE_MAP = {
    "U08": "u8",
    "S08": "i8",
    "U16": "u16",
    "S16": "i16",
    "U32": "u32",
    "S32": "i32",
    "F32": "float32",
    "FLOAT": "float32",
}


INI_LIVI_OVERRIDES: dict[str, dict[str, Any]] = {
    "batteryVoltage": {"field": "batteryV"},
    "coolantRaw": {"field": "coolantC", "value_offset": -40.0},
    "iatRaw": {"field": "iatC", "value_offset": -40.0},
    "vss": {"field": "speedKph"},
    "baro": {"field": "baroKpa"},
}


@dataclass(frozen=True)
class IniOutputScalar:
    name: str
    ts_type: str
    offset: int
    units: str
    scale: float
    translate: float


@dataclass(frozen=True)
class IniCalculatedChannel:
    name: str
    source: str
    scale: float
    translate: float
    units: str = ""
    lookup_file: str | None = None


@dataclass(frozen=True)
class _LinearValue:
    coefficients: dict[str, float]
    constant: float = 0.0

    @staticmethod
    def constant_value(value: float) -> "_LinearValue":
        return _LinearValue({}, value)

    @staticmethod
    def variable(name: str) -> "_LinearValue":
        return _LinearValue({name: 1.0}, 0.0)

    def add(self, other: "_LinearValue", sign: float = 1.0) -> "_LinearValue":
        coefficients = dict(self.coefficients)
        for name, value in other.coefficients.items():
            coefficients[name] = coefficients.get(name, 0.0) + value * sign
            if coefficients[name] == 0.0:
                del coefficients[name]
        return _LinearValue(coefficients, self.constant + other.constant * sign)

    def multiply_constant(self, factor: float) -> "_LinearValue":
        return _LinearValue({name: value * factor for name, value in self.coefficients.items()}, self.constant * factor)


def decoder_from_tunerstudio_ini(
    ini_path: Path,
    endian: str = "little",
    include_unmapped: bool = False,
) -> FixedFrameDecoder:
    config = generate_usbmon_config_from_ini(ini_path, endian=endian, include_unmapped=include_unmapped)
    fields = [
        BinaryFieldRule.from_config(field_config, str(config["usbmon"].get("endian", "big")))
        for field_config in config["usbmon"]["fields"]
    ]
    return FixedFrameDecoder(frame_length=int(config["usbmon"]["frame_length"]), fields=fields)


def generate_usbmon_config_from_ini(
    ini_path: Path,
    endian: str = "little",
    include_unmapped: bool = False,
) -> dict[str, Any]:
    text = ini_path.read_text(encoding="latin-1")
    section = _extract_section(text, "OutputChannels")
    frame_length = _extract_och_block_size(section)
    scalars = list(_parse_output_scalars(section))
    calculated_by_source = _calculated_livi_rules_by_source(section, scalars)
    fields: list[dict[str, Any]] = []

    for scalar in scalars:
        data_type = TS_TYPE_MAP.get(scalar.ts_type.upper())
        if data_type is None:
            continue

        livi_rule = calculated_by_source.get(scalar.name) or _livi_rule_for_scalar(scalar, include_unmapped)
        if livi_rule is None:
            continue

        field_config: dict[str, Any] = {
            "offset": scalar.offset,
            "type": data_type,
            "field": livi_rule["field"],
        }
        if scalar.scale != 1.0:
            field_config["scale"] = scalar.scale
        if scalar.translate != 0.0:
            field_config["value_offset"] = scalar.translate
        if "value_offset" in livi_rule:
            field_config["value_offset"] = field_config.get("value_offset", 0.0) + float(livi_rule["value_offset"])
        if "transform" in livi_rule:
            field_config["transform"] = livi_rule["transform"]
        if "round" in livi_rule:
            field_config["round"] = livi_rule["round"]
        fields.append(field_config)

    return {
        "usbmon": {
            "decoder": "tunerstudio_serial",
            "frame_length": frame_length,
            "endian": endian,
            "fields": fields,
            "source_ini": str(ini_path),
        }
    }


def generate_usbmon_config_from_field_map(
    ini_path: Path,
    field_map: dict[str, str],
    endian: str = "little",
    custom_ini_paths: Sequence[Path] = (),
    inc_dirs: Sequence[Path] = (),
) -> tuple[dict[str, Any], list[str]]:
    text = ini_path.read_text(encoding="latin-1")
    section = _extract_section(text, "OutputChannels")
    custom_sections = [
        _extract_section(custom_path.read_text(encoding="latin-1"), "OutputChannels")
        for custom_path in custom_ini_paths
    ]
    frame_length = _extract_och_block_size(section)
    scalars = list(_parse_output_scalars(section))
    for custom_section in custom_sections:
        scalars.extend(_parse_output_scalars(custom_section))
    scalar_by_name = {scalar.name: scalar for scalar in scalars}
    calculated_by_name = {channel.name: channel for channel in _parse_calculated_channels(section)}
    for custom_section in custom_sections:
        calculated_by_name.update({channel.name: channel for channel in _parse_calculated_channels(custom_section)})
    lookup_dirs = _default_inc_dirs(ini_path, custom_ini_paths, inc_dirs)
    fields: list[dict[str, Any]] = []
    warnings: list[str] = []

    for livi_field, tunerstudio_field in field_map.items():
        if not tunerstudio_field:
            continue
        field_config = _field_config_for_tunerstudio_channel(
            livi_field=livi_field,
            tunerstudio_field=tunerstudio_field,
            scalar_by_name=scalar_by_name,
            calculated_by_name=calculated_by_name,
            lookup_dirs=lookup_dirs,
        )
        if field_config is None:
            warnings.append(f"{livi_field}: unable to resolve TunerStudio channel '{tunerstudio_field}'")
            continue
        fields.append(field_config)

    return (
        {
            "usbmon": {
                "decoder": "tunerstudio_serial",
                "frame_length": frame_length,
                "endian": endian,
                "fields": fields,
                "source_ini": str(ini_path),
            }
        },
        warnings,
    )


def write_generated_usbmon_config(ini_path: Path, output_path: Path, endian: str = "little") -> None:
    config = generate_usbmon_config_from_ini(ini_path, endian=endian)
    output_path.write_text(json.dumps(config, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _field_config_for_tunerstudio_channel(
    livi_field: str,
    tunerstudio_field: str,
    scalar_by_name: dict[str, IniOutputScalar],
    calculated_by_name: dict[str, IniCalculatedChannel],
    lookup_dirs: Sequence[Path] = (),
) -> dict[str, Any] | None:
    resolved = _resolve_tunerstudio_channel(tunerstudio_field, scalar_by_name, calculated_by_name)
    if resolved is None:
        return None
    scalar, scale, value_offset, lookup_file, units = resolved

    data_type = TS_TYPE_MAP.get(scalar.ts_type.upper())
    if data_type is None or scalar.units.lower() == "bits":
        return None

    field_config: dict[str, Any] = {
        "offset": scalar.offset,
        "type": data_type,
        "field": livi_field,
    }
    total_scale = scalar.scale * scale
    total_offset = scalar.translate * scale + value_offset
    if total_scale != 1.0:
        field_config["scale"] = total_scale
    if total_offset != 0.0:
        field_config["value_offset"] = total_offset
    if lookup_file is not None:
        table_values = _read_inc_table(lookup_file, lookup_dirs)
        if table_values is None:
            return None
        table_values = _convert_lookup_for_livi_field(livi_field, table_values, units)
        field_config["lookup"] = table_values

    transform = _default_transform_for_livi_field(livi_field)
    if transform is not None:
        field_config["transform"] = transform

    return field_config


def _resolve_tunerstudio_channel(
    channel_name: str,
    scalar_by_name: dict[str, IniOutputScalar],
    calculated_by_name: dict[str, IniCalculatedChannel],
    seen: set[str] | None = None,
) -> tuple[IniOutputScalar, float, float, str | None, str] | None:
    if seen is None:
        seen = set()
    if channel_name in seen:
        return None
    seen.add(channel_name)

    scalar = scalar_by_name.get(channel_name)
    if scalar is not None:
        return scalar, 1.0, 0.0, None, scalar.units

    calculated = calculated_by_name.get(channel_name)
    if calculated is None:
        return None

    resolved = _resolve_tunerstudio_channel(calculated.source, scalar_by_name, calculated_by_name, seen)
    if resolved is None:
        return None
    scalar, source_scale, source_translate, source_lookup, source_units = resolved
    if calculated.lookup_file is not None and source_lookup is not None:
        return None
    scale = source_scale * calculated.scale
    translate = source_translate * calculated.scale + calculated.translate
    return scalar, scale, translate, calculated.lookup_file or source_lookup, calculated.units or source_units


def _default_inc_dirs(ini_path: Path, custom_ini_paths: Sequence[Path], inc_dirs: Sequence[Path]) -> list[Path]:
    candidates: list[Path] = []
    for path in inc_dirs:
        candidates.append(path)
    for path in (ini_path, *custom_ini_paths):
        parent = path.parent
        candidates.append(parent)
        candidates.append(parent / "inc")
        candidates.append(parent.parent / "inc")

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _read_inc_table(lookup_file: str, lookup_dirs: Sequence[Path]) -> list[Any] | None:
    path = Path(lookup_file)
    if not path.is_absolute():
        for directory in lookup_dirs:
            candidate = directory / lookup_file
            if candidate.exists():
                path = candidate
                break
        else:
            return None
    if not path.exists():
        return None

    values: list[Any] = []
    for raw_line in path.read_text(encoding="latin-1").splitlines():
        line = _strip_comment(raw_line).strip()
        if not line:
            continue
        match = re.match(r"(?i)^DB\s+(.+)$", line)
        if not match:
            continue
        for token in re.split(r"[,\s]+", match.group(1).strip()):
            if not token:
                continue
            values.append(_parse_table_value(token))
    return values


def _parse_table_value(token: str) -> Any:
    try:
        return int(token, 0)
    except ValueError:
        value = float(token)
    return int(value) if value.is_integer() else value


def _convert_lookup_for_livi_field(livi_field: str, values: list[Any], units: str) -> list[Any]:
    if livi_field != "fuelPct" or units.lower() not in {"l", "lt", "liter", "liters", "litre", "litres", "litri"}:
        return values

    numeric_values = [float(value) for value in values]
    capacity = max(numeric_values, default=0.0)
    if capacity <= 0.0:
        return values
    return [_clean_number(value * 100.0 / capacity) for value in numeric_values]


def _clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _default_transform_for_livi_field(livi_field: str) -> str | None:
    if livi_field == "gear":
        return "gear"
    if livi_field == "turn":
        return "turn"
    if livi_field in {"reverse", "lights", "highBeam", "hazards", "parkingBrake", "nightMode"}:
        return "bool"
    return None


def _livi_rule_for_scalar(scalar: IniOutputScalar, include_unmapped: bool) -> dict[str, Any] | None:
    if scalar.units.lower() == "bits":
        return None

    if scalar.name in INI_LIVI_OVERRIDES:
        return INI_LIVI_OVERRIDES[scalar.name]

    default = DEFAULT_CHANNEL_MAP.get(scalar.name) or DEFAULT_CHANNEL_MAP.get(canonical_channel(scalar.name))
    if default is not None:
        return dict(default)

    if include_unmapped:
        return {"field": scalar.name}
    return None


def _calculated_livi_rules_by_source(section: str, scalars: list[IniOutputScalar]) -> dict[str, dict[str, Any]]:
    scalar_names = {scalar.name for scalar in scalars}
    rules: dict[str, dict[str, Any]] = {}

    for channel in _parse_calculated_channels(section):
        if channel.source not in scalar_names or channel.source in rules:
            continue
        default = DEFAULT_CHANNEL_MAP.get(channel.name) or DEFAULT_CHANNEL_MAP.get(canonical_channel(channel.name))
        if default is None:
            continue
        rule = dict(default)
        if channel.scale != 1.0:
            rule["scale"] = float(rule.get("scale", 1.0)) * channel.scale
        if channel.translate != 0.0:
            rule["value_offset"] = float(rule.get("value_offset", 0.0)) + channel.translate
        rules[channel.source] = rule

    return rules


def _parse_calculated_channels(section: str):
    active_section = _select_known_preprocessor_branches(section, {"CELSIUS": True})
    for raw_line in active_section.splitlines():
        line = _strip_comment(raw_line).strip()
        if not line or "=" not in line:
            continue
        name, definition = line.split("=", 1)
        name = name.strip()
        parts = _split_ini_csv(definition)
        if not parts or parts[0].strip().lower().startswith("scalar"):
            continue
        units = _parse_calculated_units(parts)
        expression = _extract_braced_expression(parts[0])
        if expression is None:
            continue
        table_channel = _parse_table_expression(expression)
        if table_channel is not None:
            source, lookup_file = table_channel
            yield IniCalculatedChannel(name=name, source=source, scale=1.0, translate=0.0, units=units, lookup_file=lookup_file)
            continue
        linear = _parse_linear_expression(expression)
        if linear is None or len(linear.coefficients) != 1:
            continue
        source, scale = next(iter(linear.coefficients.items()))
        yield IniCalculatedChannel(name=name, source=source, scale=scale, translate=linear.constant, units=units)


def _parse_calculated_units(parts: list[str]) -> str:
    if len(parts) < 2:
        return ""
    return _unquote(parts[1].strip())


def _parse_table_expression(expression: str) -> tuple[str, str] | None:
    match = re.fullmatch(r'\s*table\s*\(\s*([A-Za-z_]\w*)\s*,\s*"([^"]+)"\s*\)\s*', expression)
    if not match:
        return None
    return match.group(1), match.group(2)


def _select_known_preprocessor_branches(text: str, symbols: dict[str, bool]) -> str:
    output: list[str] = []
    stack: list[tuple[bool, bool, bool]] = []
    active = True

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#if "):
            symbol = stripped[4:].strip()
            parent_active = active
            if symbol in symbols:
                if_active = parent_active and symbols[symbol]
                else_active = parent_active and not symbols[symbol]
            else:
                if_active = parent_active
                else_active = parent_active
            stack.append((parent_active, if_active, else_active))
            active = if_active
            continue
        if stripped.startswith("#else") and stack:
            parent_active, _if_active, else_active = stack[-1]
            active = parent_active and else_active
            continue
        if stripped.startswith("#endif") and stack:
            parent_active, _if_active, _else_active = stack.pop()
            active = parent_active
            continue
        if active:
            output.append(line)

    return "\n".join(output)


def _extract_braced_expression(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None

    depth = 0
    for index, char in enumerate(stripped):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[1:index].strip()
    return None


def _parse_linear_expression(expression: str) -> _LinearValue | None:
    try:
        node = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None
    return _linear_from_ast(node.body)


def _linear_from_ast(node: ast.AST) -> _LinearValue | None:
    if isinstance(node, ast.Name):
        return _LinearValue.variable(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return _LinearValue.constant_value(float(node.value))
    if isinstance(node, ast.UnaryOp):
        value = _linear_from_ast(node.operand)
        if value is None:
            return None
        if isinstance(node.op, ast.USub):
            return value.multiply_constant(-1.0)
        if isinstance(node.op, ast.UAdd):
            return value
        return None
    if isinstance(node, ast.BinOp):
        left = _linear_from_ast(node.left)
        right = _linear_from_ast(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left.add(right)
        if isinstance(node.op, ast.Sub):
            return left.add(right, sign=-1.0)
        if isinstance(node.op, ast.Mult):
            if not left.coefficients:
                return right.multiply_constant(left.constant)
            if not right.coefficients:
                return left.multiply_constant(right.constant)
            return None
        if isinstance(node.op, ast.Div):
            if right.coefficients or right.constant == 0.0:
                return None
            return left.multiply_constant(1.0 / right.constant)
    return None


def _extract_section(text: str, name: str) -> str:
    header = re.compile(rf"^\s*\[{re.escape(name)}\]\s*$", re.MULTILINE)
    match = header.search(text)
    if not match:
        raise ValueError(f"Missing [{name}] section")

    next_header = re.compile(r"^\s*\[[^\]]+\]\s*$", re.MULTILINE)
    next_match = next_header.search(text, match.end())
    end = next_match.start() if next_match else len(text)
    return text[match.end() : end]


def _extract_och_block_size(section: str) -> int:
    match = re.search(r"^\s*ochBlockSize\s*=\s*(\d+)", section, re.MULTILINE)
    if not match:
        raise ValueError("Missing ochBlockSize in [OutputChannels]")
    return int(match.group(1))


def _parse_output_scalars(section: str):
    for raw_line in section.splitlines():
        line = _strip_comment(raw_line).strip()
        if not line or "=" not in line:
            continue
        name, definition = line.split("=", 1)
        parts = _split_ini_csv(definition)
        if len(parts) < 6 or parts[0].strip().lower() != "scalar":
            continue

        ts_type = parts[1].strip().upper()
        offset = _parse_int(parts[2])
        scale = _parse_float(parts[4], default=1.0)
        translate = _parse_float(parts[5], default=0.0)
        if offset is None or scale is None or translate is None:
            continue

        yield IniOutputScalar(
            name=name.strip(),
            ts_type=ts_type,
            offset=offset,
            units=_unquote(parts[3].strip()),
            scale=scale,
            translate=translate,
        )


def _strip_comment(line: str) -> str:
    in_quote = False
    brace_depth = 0
    bracket_depth = 0
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif char == ";" and brace_depth == 0 and bracket_depth == 0:
            return line[:index]
    return line


def _split_ini_csv(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    in_quote = False
    brace_depth = 0
    bracket_depth = 0
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif char == "," and brace_depth == 0 and bracket_depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return parts


def _parse_int(text: str) -> int | None:
    try:
        return int(text.strip(), 0)
    except ValueError:
        return None


def _parse_float(text: str, default: float | None = None) -> float | None:
    stripped = text.strip()
    if stripped.startswith("{"):
        return default
    try:
        return float(stripped)
    except ValueError:
        return default


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text
