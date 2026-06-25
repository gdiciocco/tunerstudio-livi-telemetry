import unittest

from livi_bridge.demo import DemoTelemetryGenerator


class DemoTelemetryTest(unittest.TestCase):
    def test_demo_cycle_moves_speed_rpm_and_gear(self) -> None:
        generator = DemoTelemetryGenerator()

        idle = generator.sample(0.0)
        moving = generator.sample(18.0)
        fast = generator.sample(60.0)

        self.assertEqual(idle["gear"], "N")
        self.assertGreater(moving["speedKph"], idle["speedKph"])
        self.assertGreater(moving["rpm"], idle["rpm"])
        self.assertIsInstance(moving["gear"], int)
        self.assertGreater(fast["speedKph"], moving["speedKph"])
        self.assertGreaterEqual(fast["gear"], moving["gear"])

    def test_demo_payload_contains_livi_dashboard_fields(self) -> None:
        payload = DemoTelemetryGenerator().sample(42.0)

        for field in ["speedKph", "rpm", "gear", "coolantC", "iatC", "batteryV", "fuelPct", "mapKpa", "afr"]:
            self.assertIn(field, payload)


if __name__ == "__main__":
    unittest.main()
