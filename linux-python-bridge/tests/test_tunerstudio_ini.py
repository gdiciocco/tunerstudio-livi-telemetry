import tempfile
import unittest
from pathlib import Path

from livi_bridge.tunerstudio_ini import generate_usbmon_config_from_field_map, generate_usbmon_config_from_ini


class TunerStudioIniTest(unittest.TestCase):
    def test_generates_usbmon_config_from_output_channels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp) / "mainController.ini"
            ini.write_text(
                """
[MegaTune]
signature = test

[OutputChannels]
  ochGetCommand    = "r\\$tsCanId\\x30%2o%2c"
  ochBlockSize     =  130
  rpm              = scalar,   U16,    14, "rpm",    1.000, 0.000
  vss              = scalar,   U16,   104, "km/h",   1.000, 0.000
  gear             = scalar,   U08,   106, "",       1.000, 0.000
  coolantRaw       = scalar,   U08,     7, "C",      1.000, 0.000
  iatRaw           = scalar,   U08,     6, "C",      1.000, 0.000
  batteryVoltage   = scalar,   U08,     9, "V",      0.100, 0.000
#if CELSIUS
  coolant          = { coolantRaw - 40 }
  iat              = { iatRaw - 40 }
#else
  coolant          = { (coolantRaw - 40) * 1.8 + 32 }
  iat              = { (iatRaw - 40) * 1.8 + 32 }
#endif

[Datalog]
  entry = rpm, "RPM", int, "%d"
""",
                encoding="latin-1",
            )

            config = generate_usbmon_config_from_ini(ini)

        fields = config["usbmon"]["fields"]
        by_field = {field["field"]: field for field in fields}
        self.assertEqual(config["usbmon"]["decoder"], "tunerstudio_serial")
        self.assertEqual(config["usbmon"]["endian"], "little")
        self.assertEqual(config["usbmon"]["frame_length"], 130)
        self.assertEqual(by_field["rpm"]["offset"], 14)
        self.assertEqual(by_field["rpm"]["type"], "u16")
        self.assertEqual(by_field["speedKph"]["offset"], 104)
        self.assertEqual(by_field["gear"]["offset"], 106)
        self.assertEqual(by_field["coolantC"]["value_offset"], -40.0)
        self.assertEqual(by_field["iatC"]["value_offset"], -40.0)
        self.assertEqual(by_field["batteryV"]["scale"], 0.1)

    def test_uses_calculated_celsius_aliases_for_raw_temperature_channels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp) / "mainController.ini"
            ini.write_text(
                """
[OutputChannels]
  ochBlockSize = 130
  coolantRaw   = scalar, U08, 7, "C", 1.000, 0.000
  iatRaw       = scalar, U08, 6, "C", 1.000, 0.000
#if CELSIUS
  coolant      = { coolantRaw - 40 }
  iat          = { iatRaw - 40 }
#else
  coolant      = { (coolantRaw - 40) * 1.8 + 32 }
  iat          = { (iatRaw - 40) * 1.8 + 32 }
#endif
""",
                encoding="latin-1",
            )

            config = generate_usbmon_config_from_ini(ini)

        by_field = {field["field"]: field for field in config["usbmon"]["fields"]}
        self.assertEqual(by_field["coolantC"]["offset"], 7)
        self.assertEqual(by_field["coolantC"]["value_offset"], -40.0)
        self.assertNotIn("scale", by_field["coolantC"])
        self.assertEqual(by_field["iatC"]["offset"], 6)
        self.assertEqual(by_field["iatC"]["value_offset"], -40.0)
        self.assertNotIn("scale", by_field["iatC"])

    def test_generates_usbmon_config_from_livi_field_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp) / "mainController.ini"
            ini.write_text(
                """
[OutputChannels]
  ochBlockSize = 130
  map          = scalar, U16, 4, "kpa", 1.000, 0.000
  coolantRaw   = scalar, U08, 7, "C",   1.000, 0.000
  gear         = scalar, U08, 106, "",  1.000, 0.000
#if CELSIUS
  coolant      = { coolantRaw - 40 }
#else
  coolant      = { (coolantRaw - 40) * 1.8 + 32 }
#endif
""",
                encoding="latin-1",
            )

            config, warnings = generate_usbmon_config_from_field_map(
                ini,
                {
                    "mapKpa": "map",
                    "coolantC": "coolant",
                    "gear": "gear",
                    "afr": "missingChannel",
                    "rpm": "",
                },
            )

        self.assertEqual(warnings, ["afr: unable to resolve TunerStudio channel 'missingChannel'"])
        by_field = {field["field"]: field for field in config["usbmon"]["fields"]}
        self.assertEqual(by_field["mapKpa"]["offset"], 4)
        self.assertEqual(by_field["coolantC"]["offset"], 7)
        self.assertEqual(by_field["coolantC"]["value_offset"], -40.0)
        self.assertEqual(by_field["gear"]["offset"], 106)
        self.assertEqual(by_field["gear"]["transform"], "gear")
        self.assertNotIn("rpm", by_field)

    def test_generates_usbmon_config_from_custom_ini_formula_and_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ini = root / "projectCfg" / "mainController.ini"
            custom_ini = root / "projectCfg" / "custom.ini"
            inc_dir = root / "inc"
            ini.parent.mkdir()
            inc_dir.mkdir()
            ini.write_text(
                """
[OutputChannels]
  ochBlockSize = 130
  auxin_gauge0 = scalar, U16, 42, "",    1.000, 0.000
  oilPressure  = scalar, U08, 108, "PSI", 1.000, 0.000
""",
                encoding="latin-1",
            )
            custom_ini.write_text(
                """
[OutputChannels]
  benzina        = {table( auxin_gauge0, "benzina.inc" )}, "L"
  oilPressureBAR = {oilPressure / 14.504 - 1}, "BAR"
""",
                encoding="latin-1",
            )
            (inc_dir / "benzina.inc").write_text(
                """
DB 25
DB 24
DB 10
""",
                encoding="latin-1",
            )

            config, warnings = generate_usbmon_config_from_field_map(
                ini,
                {
                    "fuelPct": "benzina",
                    "oilC": "oilPressureBAR",
                },
                custom_ini_paths=[custom_ini],
            )

        self.assertEqual(warnings, [])
        by_field = {field["field"]: field for field in config["usbmon"]["fields"]}
        self.assertEqual(by_field["fuelPct"]["offset"], 42)
        self.assertEqual(by_field["fuelPct"]["type"], "u16")
        self.assertEqual(by_field["fuelPct"]["lookup"], [100, 96, 40])
        self.assertEqual(by_field["oilC"]["offset"], 108)
        self.assertAlmostEqual(by_field["oilC"]["scale"], 1 / 14.504)
        self.assertEqual(by_field["oilC"]["value_offset"], -1.0)


if __name__ == "__main__":
    unittest.main()
