import unittest

from livi_bridge.mapper import ChannelRule, TelemetryMapper, coerce_rule_value, merge_patch


class TelemetryMapperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mapper = TelemetryMapper.load(None)

    def test_maps_common_rpm_channel(self) -> None:
        self.assertEqual(self.mapper.map_packet({"channel": "rpm", "value": 1234}), {"rpm": 1234.0})

    def test_canonicalizes_channel_names(self) -> None:
        self.assertEqual(self.mapper.map_packet({"channel": "Coolant C", "value": 90}), {"coolantC": 90.0})

    def test_converts_mph_to_kph(self) -> None:
        patch = self.mapper.map_packet({"channel": "speedMph", "value": 60})
        self.assertEqual(round(patch["speedKph"], 3), 96.561)

    def test_maps_nested_gps_patch(self) -> None:
        self.assertEqual(self.mapper.map_packet({"channel": "gpsLat", "value": 52.5}), {"gps": {"lat": 52.5}})

    def test_shallow_merges_nested_blocks(self) -> None:
        target = {"gps": {"lat": 52.5}}
        merge_patch(target, {"gps": {"lng": 13.4}})
        self.assertEqual(target, {"gps": {"lat": 52.5, "lng": 13.4}})

    def test_applies_index_lookup_after_source_scaling(self) -> None:
        rule = ChannelRule.from_config({"field": "fuelPct", "lookup": [25, 20, 10], "scale": 0.5})
        self.assertEqual(coerce_rule_value(0, rule), 25)
        self.assertEqual(coerce_rule_value(2, rule), 20)
        self.assertEqual(coerce_rule_value(99, rule), 10)


if __name__ == "__main__":
    unittest.main()
