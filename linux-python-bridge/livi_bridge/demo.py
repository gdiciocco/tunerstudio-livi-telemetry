from __future__ import annotations

import math


class DemoTelemetryGenerator:
    def __init__(self, cycle_seconds: float = 90.0, max_speed_kph: float = 125.0) -> None:
        if cycle_seconds <= 0:
            raise ValueError("cycle_seconds must be greater than zero")
        if max_speed_kph <= 0:
            raise ValueError("max_speed_kph must be greater than zero")
        self.cycle_seconds = cycle_seconds
        self.max_speed_kph = max_speed_kph

    def sample(self, elapsed_seconds: float) -> dict[str, float | int | str | bool]:
        phase = elapsed_seconds % self.cycle_seconds
        speed = self._speed_for_phase(phase)
        previous_speed = self._speed_for_phase((phase - 0.25) % self.cycle_seconds)
        acceleration = (speed - previous_speed) / 0.25
        gear = self._gear_for_speed(speed)
        rpm = self._rpm_for_speed(speed, gear, elapsed_seconds, acceleration)
        load = self._load(speed, acceleration)
        baro = 99.0
        map_kpa = self._map_kpa(speed, load)
        coolant = min(92.0, 55.0 + elapsed_seconds * 0.08 + 3.0 * math.sin(elapsed_seconds / 37.0))
        iat = 27.0 + 5.0 * load + 2.0 * math.sin(elapsed_seconds / 11.0)
        oil = min(98.0, 45.0 + elapsed_seconds * 0.11 + 2.0 * math.sin(elapsed_seconds / 29.0))

        return {
            "speedKph": round(speed, 1),
            "rpm": round(rpm),
            "gear": gear,
            "coolantC": round(coolant, 1),
            "oilC": round(oil, 1),
            "iatC": round(iat, 1),
            "ambientC": 24.0,
            "batteryV": round(13.8 + 0.15 * math.sin(elapsed_seconds / 5.0), 2),
            "fuelPct": round(max(0.0, 78.0 - elapsed_seconds * 0.006), 1),
            "mapKpa": round(map_kpa, 1),
            "baroKpa": baro,
            "boostKpa": round(max(0.0, map_kpa - baro), 1),
            "afr": round(self._afr(load, acceleration, speed), 2),
            "steeringDeg": round(6.0 * math.sin(elapsed_seconds / 3.5), 1),
            "parkingBrake": speed < 0.5 and phase < 3.0,
            "nightMode": False,
        }

    def _speed_for_phase(self, phase: float) -> float:
        timeline = [
            (0.0, 0.0),
            (6.0, 0.0),
            (20.0, 48.0),
            (34.0, 48.0),
            (54.0, self.max_speed_kph),
            (68.0, self.max_speed_kph),
            (84.0, 0.0),
            (90.0, 0.0),
        ]
        scaled_phase = phase * 90.0 / self.cycle_seconds

        for (start_t, start_v), (end_t, end_v) in zip(timeline, timeline[1:]):
            if start_t <= scaled_phase <= end_t:
                if end_t == start_t:
                    return end_v
                amount = (scaled_phase - start_t) / (end_t - start_t)
                eased = amount * amount * (3.0 - 2.0 * amount)
                return start_v + (end_v - start_v) * eased
        return 0.0

    @staticmethod
    def _gear_for_speed(speed_kph: float) -> int | str:
        if speed_kph < 1.0:
            return "N"
        if speed_kph < 16.0:
            return 1
        if speed_kph < 34.0:
            return 2
        if speed_kph < 58.0:
            return 3
        if speed_kph < 86.0:
            return 4
        if speed_kph < 118.0:
            return 5
        return 6

    @staticmethod
    def _rpm_for_speed(speed_kph: float, gear: int | str, elapsed_seconds: float, acceleration: float) -> float:
        if not isinstance(gear, int):
            return 850.0 + 35.0 * math.sin(elapsed_seconds * 2.0)
        kph_per_1000rpm = {1: 8.0, 2: 15.0, 3: 23.0, 4: 32.0, 5: 42.0, 6: 52.0}[gear]
        rpm = speed_kph / kph_per_1000rpm * 1000.0
        rpm += max(0.0, acceleration) * 18.0
        return max(950.0, min(6500.0, rpm))

    @staticmethod
    def _load(speed_kph: float, acceleration: float) -> float:
        if speed_kph < 1.0:
            return 0.18
        return max(0.12, min(1.0, 0.35 + acceleration / 18.0 + speed_kph / 260.0))

    @staticmethod
    def _map_kpa(speed_kph: float, load: float) -> float:
        if speed_kph < 1.0:
            return 38.0
        return 38.0 + load * 118.0

    @staticmethod
    def _afr(load: float, acceleration: float, speed_kph: float) -> float:
        if speed_kph > 2.0 and acceleration < -2.0:
            return 16.8
        if load > 0.72:
            return 12.6
        if load > 0.45:
            return 13.5
        return 14.6
