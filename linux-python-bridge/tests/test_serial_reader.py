import unittest

from livi_bridge.serial_reader import ActiveTunerStudioSerialReader, SerialReadCommand
from livi_bridge.usbmon_decoder import BinaryFieldRule, TunerStudioSerialDecoder


class FakeSerialPort:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.requests: list[bytes] = []

    def transact(self, request: bytes) -> bytes:
        self.requests.append(request)
        return self.response


class SerialReaderTest(unittest.TestCase):
    def test_read_command_matches_usbmon_dump_shape(self) -> None:
        command = SerialReadCommand(offset=0, count=121, can_id=0, page=0x30).to_bytes()

        self.assertEqual(command, bytes.fromhex("00077200300000790000000000"))

    def test_active_reader_decodes_tunerstudio_response(self) -> None:
        fields = [
            BinaryFieldRule.from_config({"offset": 14, "type": "u16", "field": "rpm"}, "little"),
            BinaryFieldRule.from_config({"offset": 104, "type": "u16", "field": "speedKph"}, "little"),
            BinaryFieldRule.from_config({"offset": 106, "type": "u8", "field": "gear", "transform": "gear"}, "little"),
        ]
        decoder = TunerStudioSerialDecoder(frame_length=130, fields=fields)
        frame = bytearray(130)
        frame[14:16] = (3200).to_bytes(2, "little")
        frame[104:106] = (88).to_bytes(2, "little")
        frame[106] = 3
        response_payload = b"\x00" + bytes(frame)
        response = len(response_payload).to_bytes(2, "big") + response_payload + b"crc!"
        port = FakeSerialPort(response)

        reader = ActiveTunerStudioSerialReader(
            serial_port="/dev/ttyUSB0",  # type: ignore[arg-type]
            decoder=decoder,
            baud=115200,
            timeout=0.5,
            read_size=130,
            can_id=0,
            page=0x30,
        )

        self.assertEqual(reader.read_once(port), {"rpm": 3200.0, "speedKph": 88.0, "gear": "3"})
        self.assertEqual(port.requests, [SerialReadCommand(offset=0, count=130).to_bytes()])


if __name__ == "__main__":
    unittest.main()
