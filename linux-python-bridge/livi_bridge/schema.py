from __future__ import annotations

from typing import Final

TOP_LEVEL_FIELDS: Final[set[str]] = {
    "ts",
    "speedKph",
    "rpm",
    "gear",
    "steeringDeg",
    "reverse",
    "lights",
    "highBeam",
    "hazards",
    "turn",
    "parkingBrake",
    "coolantC",
    "oilC",
    "transmissionC",
    "iatC",
    "ambientC",
    "batteryV",
    "fuelPct",
    "rangeKm",
    "fuelRateLph",
    "consumptionLPer100Km",
    "consumptionAvgLPer100Km",
    "batteryCapacityKwh",
    "batteryLevelKwh",
    "mapKpa",
    "baroKpa",
    "boostKpa",
    "lambda",
    "afr",
    "odometerKm",
    "odometerTripKm",
    "drivingStatus",
    "ambientLux",
    "nightMode",
    "gps",
    "can",
}

GPS_FIELDS: Final[set[str]] = {
    "lat",
    "lng",
    "alt",
    "heading",
    "speedMs",
    "accuracyM",
    "satellites",
    "fixTs",
}

CAN_FIELDS: Final[set[str]] = {"id", "data", "bus"}

BOOLEAN_FIELDS: Final[set[str]] = {
    "reverse",
    "lights",
    "highBeam",
    "hazards",
    "parkingBrake",
    "nightMode",
}

STRING_ENUM_FIELDS: Final[set[str]] = {"gear", "turn"}


def validate_field_path(path: str) -> None:
    parts = path.split(".")
    if len(parts) == 1:
        if path not in TOP_LEVEL_FIELDS:
            raise ValueError(f"Unsupported LIVI telemetry field: {path}")
        if path in {"gps", "can"}:
            raise ValueError(f"Use a nested field such as {path}.lat")
        return

    if len(parts) != 2:
        raise ValueError(f"Unsupported nested telemetry field: {path}")

    parent, child = parts
    if parent == "gps" and child in GPS_FIELDS:
        return
    if parent == "can" and child in CAN_FIELDS:
        return
    raise ValueError(f"Unsupported nested telemetry field: {path}")

