import struct
import tempfile
import unittest
import ctypes
from dataclasses import dataclass
from pathlib import Path

from livi_bridge.usbmon import UsbMonPacket, resolve_serial_usb_device
from livi_bridge.usbmon_decoder import BinaryFieldRule, FixedFrameDecoder, TunerStudioSerialDecoder


@dataclass
class FakeUsbEvent:
    event_type: str
    is_input: bool
    data: bytes
    xfer_type: int = 3
    status: int = 0


class UsbmonDecoderTest(unittest.TestCase):
    def test_usbmon_stream_header_is_48_bytes(self) -> None:
        self.assertEqual(ctypes.sizeof(UsbMonPacket), 48)

    def test_decodes_fixed_big_endian_frame(self) -> None:
        fields = [
            BinaryFieldRule.from_config({"offset": 0, "type": "u16", "field": "rpm"}, "big"),
            BinaryFieldRule.from_config(
                {"offset": 2, "type": "u16", "field": "speedKph", "scale": 0.1, "round": 1},
                "big",
            ),
            BinaryFieldRule.from_config({"offset": 4, "type": "u8", "field": "lights", "bit": 0, "transform": "bool"}, "big"),
        ]
        decoder = FixedFrameDecoder(frame_length=8, fields=fields)
        frame = struct.pack(">HHBxxx", 2100, 735, 0b00000001)

        patches = decoder.decode_bytes(frame)

        self.assertEqual(patches, [{"rpm": 2100.0, "speedKph": 73.5, "lights": True}])

    def test_resolves_serial_port_to_usbmon_device_from_sysfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            serial = root / "dev" / "ttyUSB0"
            serial.parent.mkdir()
            serial.write_text("", encoding="ascii")
            sys_tty = root / "sys" / "class" / "tty"
            device = sys_tty / "ttyUSB0" / "device"
            device.mkdir(parents=True)
            (device / "busnum").write_text("3\n", encoding="ascii")
            (device / "devnum").write_text("7\n", encoding="ascii")

            resolved = resolve_serial_usb_device(serial, sys_tty)

        self.assertEqual(resolved.busnum, 3)
        self.assertEqual(resolved.devnum, 7)
        self.assertEqual(resolved.usbmon_path.as_posix(), "/dev/usbmon3")

    def test_tunerstudio_serial_decoder_uses_out_command_alignment(self) -> None:
        fields = [
            BinaryFieldRule.from_config({"offset": 14, "type": "u16", "field": "rpm"}, "little"),
            BinaryFieldRule.from_config({"offset": 104, "type": "u16", "field": "speedKph"}, "little"),
            BinaryFieldRule.from_config({"offset": 106, "type": "u8", "field": "gear", "transform": "gear"}, "little"),
        ]
        decoder = TunerStudioSerialDecoder(frame_length=130, fields=fields)
        frame = bytearray(130)
        frame[14:16] = (100).to_bytes(2, "little")
        frame[104:106] = (92).to_bytes(2, "little")
        frame[106] = 1
        # TunerStudio packet: 2-byte payload length, 'r', CAN/page bytes,
        # 2-byte little-endian offset, 2-byte little-endian count, 4-byte crc.
        command = bytes.fromhex("00077200300000790000000000")
        # TunerStudio response packet: 2-byte payload length, status byte,
        # data bytes, 4-byte crc. Split it across URBs as usbmon often does.
        response_payload = b"\x00" + bytes(frame[:121])
        response = len(response_payload).to_bytes(2, "big") + response_payload + b"crc!"

        self.assertEqual(decoder.decode_usbmon_event(FakeUsbEvent("S", False, command)), [])
        self.assertEqual(decoder.decode_usbmon_event(FakeUsbEvent("C", True, response[:37])), [])
        self.assertEqual(decoder.decode_usbmon_event(FakeUsbEvent("C", True, response[37:])), [])
        patches = decoder.decode_usbmon_event(FakeUsbEvent("S", False, command))

        self.assertEqual(patches, [{"rpm": 100.0, "speedKph": 92.0, "gear": "1"}])


if __name__ == "__main__":
    unittest.main()
