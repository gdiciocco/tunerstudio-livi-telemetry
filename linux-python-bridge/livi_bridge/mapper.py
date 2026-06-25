from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .defaults import DEFAULT_CHANNEL_MAP
from .schema import BOOLEAN_FIELDS, STRING_ENUM_FIELDS, validate_field_path


def canonical_channel(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


@dataclass(frozen=True)
class ChannelRule:
    field: str
    transform: str = "identity"
    scale: float = 1.0
    offset: float = 0.0
    round_digits: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    truthy_threshold: float = 0.5
    enum: dict[str, Any] | None = None
    lookup: list[Any] | None = None

    @staticmethod
    def from_config(config: dict[str, Any]) -> "ChannelRule":
        field = str(config["field"])
        validate_field_path(field)
        enum = config.get("enum")
        if enum is not None:
            enum = {str(k): v for k, v in dict(enum).items()}
        lookup = config.get("lookup")
        if lookup is not None:
            lookup = list(lookup)
        return ChannelRule(
            field=field,
            transform=str(config.get("transform", "identity")),
            scale=float(config.get("scale", 1.0)),
            offset=float(config.get("offset", 0.0)),
            round_digits=config.get("round"),
            min_value=config.get("min"),
            max_value=config.get("max"),
            truthy_threshold=float(config.get("truthy_threshold", 0.5)),
            enum=enum,
            lookup=lookup,
        )


class TelemetryMapper:
    def __init__(self, rules: dict[str, ChannelRule]) -> None:
        self._rules = rules

    @classmethod
    def load(cls, config_path: Path | None) -> "TelemetryMapper":
        raw_rules: dict[str, dict[str, Any]] = dict(DEFAULT_CHANNEL_MAP)
        if config_path is not None:
            with config_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            raw_rules.update(loaded.get("channels", {}))

        rules: dict[str, ChannelRule] = {}
        for channel, rule_config in raw_rules.items():
            rules[channel] = ChannelRule.from_config(rule_config)
            rules[canonical_channel(channel)] = rules[channel]
        return cls(rules)

    def map_packet(self, packet: dict[str, Any]) -> dict[str, Any]:
        channel = packet.get("channel")
        if not isinstance(channel, str):
            return {}

        rule = self._rules.get(channel) or self._rules.get(canonical_channel(channel))
        if rule is None:
            return {}

        value = coerce_rule_value(packet.get("value"), rule)
        if value is None:
            return {}

        return self._to_patch(rule.field, value)

    @staticmethod
    def _gear_value(numeric: float) -> int | str:
        rounded = int(round(numeric))
        if rounded == -1:
            return "R"
        if rounded == 0:
            return "N"
        return rounded

    @staticmethod
    def _turn_value(numeric: float) -> str:
        rounded = int(round(numeric))
        if rounded == 1:
            return "left"
        if rounded == 2:
            return "right"
        return "none"

    @staticmethod
    def _to_patch(field: str, value: Any) -> dict[str, Any]:
        if "." not in field:
            return {field: value}
        parent, child = field.split(".", 1)
        return {parent: {child: value}}


def merge_patch(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key].update(value)
        else:
            target[key] = value


def coerce_rule_value(raw: Any, rule: ChannelRule) -> Any:
    if rule.enum is not None:
        key = str(int(raw)) if isinstance(raw, float) and raw.is_integer() else str(raw)
        if key in rule.enum:
            return rule.enum[key]

    numeric = float(raw)
    if rule.lookup is not None:
        if not rule.lookup:
            return None
        index_value = numeric * rule.scale + rule.offset
        index = max(0, min(len(rule.lookup) - 1, int(index_value)))
        return rule.lookup[index]

    value: Any
    match rule.transform:
        case "identity":
            value = numeric
        case "f_to_c":
            value = (numeric - 32.0) * 5.0 / 9.0
        case "mph_to_kph":
            value = numeric * 1.609344
        case "kph_to_ms":
            value = numeric / 3.6
        case "ms_to_kph":
            value = numeric * 3.6
        case "psi_to_kpa":
            value = numeric * 6.8947572932
        case "bool":
            value = numeric >= rule.truthy_threshold
        case "gear":
            value = TelemetryMapper._gear_value(numeric)
        case "turn":
            value = TelemetryMapper._turn_value(numeric)
        case _:
            raise ValueError(f"Unknown transform: {rule.transform}")

    if isinstance(value, (int, float)) and not isinstance(value, bool) and rule.transform not in {"gear", "turn"}:
        value = value * rule.scale + rule.offset
        if rule.min_value is not None:
            value = max(value, float(rule.min_value))
        if rule.max_value is not None:
            value = min(value, float(rule.max_value))
        if rule.round_digits is not None:
            value = round(value, int(rule.round_digits))

    if rule.field in BOOLEAN_FIELDS and not isinstance(value, bool):
        value = bool(value)
    if rule.field in STRING_ENUM_FIELDS and not isinstance(value, str):
        value = str(value)
    return value
