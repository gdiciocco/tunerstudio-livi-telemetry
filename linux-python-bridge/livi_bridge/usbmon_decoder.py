from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mapper import ChannelRule, TelemetryMapper, coerce_rule_value, merge_patch


TYPE_FORMATS = {
    "u8": "B",
    "i8": "b",
    "u16": "H",
    "i16": "h",
    "u32": "I",
    "i32": "i",
    "float32": "f",
    "float64": "d",
}


@dataclass(frozen=True)
class BinaryFieldRule:
    offset: int
    data_type: str
    rule: ChannelRule
    bit: int | None = None
    endian: str | None = None

    @staticmethod
    def from_config(config: dict[str, Any], default_endian: str) -> "BinaryFieldRule":
        data_type = str(config.get("type", "u16"))
        if data_type not in TYPE_FORMATS:
            raise ValueError(f"Unsupported usbmon field type: {data_type}")
        rule_config = dict(config)
        binary_offset = int(rule_config.pop("offset"))
        rule_config.pop("type", None)
        rule_config.pop("bit", None)
        rule_config.pop("endian", None)
        if "value_offset" in rule_config:
            rule_config["offset"] = rule_config.pop("value_offset")
        return BinaryFieldRule(
            offset=binary_offset,
            data_type=data_type,
            bit=config.get("bit"),
            endian=config.get("endian", default_endian),
            rule=ChannelRule.from_config(rule_config),
        )


class FixedFrameDecoder:
    def __init__(
        self,
        frame_length: int,
        fields: list[BinaryFieldRule],
        sync: bytes = b"",
    ) -> None:
        if frame_length <= 0:
            raise ValueError("frame_length must be greater than zero")
        self.frame_length = frame_length
        self.fields = fields
        self.sync = sync
        self.buffer = bytearray()

    @classmethod
    def load(cls, config_path: Path):
        with config_path.open("r", encoding="utf-8") as handle:
            root = json.load(handle)
        config = root.get("usbmon", root)
        decoder_name = config.get("decoder", "fixed_frame")

        endian = str(config.get("endian", "big"))
        fields = [
            BinaryFieldRule.from_config(field_config, endian)
            for field_config in config.get("fields", [])
        ]
        if decoder_name == "tunerstudio_serial":
            return TunerStudioSerialDecoder(frame_length=int(config["frame_length"]), fields=fields)
        if decoder_name != "fixed_frame":
            raise ValueError(f"Unsupported usbmon decoder: {decoder_name}")

        sync_text = str(config.get("sync", ""))
        sync = bytes.fromhex(sync_text) if sync_text else b""
        return cls(frame_length=int(config["frame_length"]), fields=fields, sync=sync)

    def decode_bytes(self, data: bytes) -> list[dict[str, Any]]:
        self.buffer.extend(data)
        patches: list[dict[str, Any]] = []

        while True:
            if self.sync:
                sync_index = self.buffer.find(self.sync)
                if sync_index < 0:
                    keep = max(0, len(self.sync) - 1)
                    if len(self.buffer) > keep:
                        del self.buffer[:-keep]
                    break
                if sync_index > 0:
                    del self.buffer[:sync_index]

            if len(self.buffer) < self.frame_length:
                break

            frame = bytes(self.buffer[: self.frame_length])
            del self.buffer[: self.frame_length]
            patch = self._decode_frame(frame)
            if patch:
                patches.append(patch)

        return patches

    def _decode_frame(self, frame: bytes) -> dict[str, Any]:
        return decode_frame_fields(frame, self.fields)

    @staticmethod
    def _read_raw(frame: bytes, field: BinaryFieldRule) -> Any:
        endian_prefix = ">" if field.endian == "big" else "<"
        fmt = endian_prefix + TYPE_FORMATS[field.data_type]
        return struct.unpack_from(fmt, frame, field.offset)[0]


class TunerStudioSerialDecoder:
    def __init__(self, frame_length: int, fields: list[BinaryFieldRule]) -> None:
        if frame_length <= 0:
            raise ValueError("frame_length must be greater than zero")
        self.frame_length = frame_length
        self.fields = fields
        self.required_length = max((field.offset + struct.calcsize(TYPE_FORMATS[field.data_type]) for field in fields), default=0)
        self.block = bytearray(frame_length)
        self.valid_ranges: list[tuple[int, int]] = []
        self.pending_segment: _PendingSegment | None = None
        self.emitted_current_block = False

    def decode_usbmon_event(self, event: Any) -> list[dict[str, Any]]:
        if event.xfer_type != 3:
            return []

        if event.is_input:
            if event.event_type != "C" or event.status != 0:
                return []
            return self._consume_input(event.data)

        if event.event_type != "S":
            return []
        command = self._parse_read_command(event.data)
        if command is None:
            return []
        patches = self._finalize_pending_segment()
        offset, count = command
        if offset == 0:
            self.block = bytearray(self.frame_length)
            self.valid_ranges = []
            self.emitted_current_block = False
        self.pending_segment = _PendingSegment(offset=offset, count=count, data=bytearray())
        return patches

    def decode_bytes(self, data: bytes) -> list[dict[str, Any]]:
        # Fallback for pre-extracted serial streams: drop a leading status byte
        # or TunerStudio length/status envelope if present, then decode only
        # when enough frame bytes are available.
        data = self._extract_response_data(data)
        if len(data) < self.required_length:
            return []
        return [decode_frame_fields(data[: self.frame_length], self.fields)]

    def flush(self) -> list[dict[str, Any]]:
        return self._finalize_pending_segment()

    def _consume_input(self, data: bytes) -> list[dict[str, Any]]:
        if self.pending_segment is None or not data:
            return []
        self.pending_segment.data.extend(data)
        return []

    def _finalize_pending_segment(self) -> list[dict[str, Any]]:
        if self.pending_segment is None:
            return []

        segment = self.pending_segment
        self.pending_segment = None
        segment_data = self._extract_response_data(bytes(segment.data))
        usable_count = min(segment.count, len(segment_data), max(0, self.frame_length - segment.offset))
        if usable_count <= 0:
            return []

        self.block[segment.offset : segment.offset + usable_count] = segment_data[:usable_count]
        self.valid_ranges.append((segment.offset, segment.offset + usable_count))

        if self.emitted_current_block or not self._has_required_data():
            return []

        self.emitted_current_block = True
        return [decode_frame_fields(bytes(self.block), self.fields)]

    def _has_required_data(self) -> bool:
        if self.required_length == 0:
            return False
        covered_until = 0
        for start, end in sorted(self.valid_ranges):
            if start > covered_until:
                return False
            covered_until = max(covered_until, end)
            if covered_until >= self.required_length:
                return True
        return False

    @staticmethod
    def _parse_read_command(data: bytes) -> tuple[int, int] | None:
        payload = data
        if len(data) >= 6:
            declared = int.from_bytes(data[:2], "big")
            if 0 < declared <= len(data) - 6:
                payload = data[2 : 2 + declared]

        if len(payload) < 7 or payload[0] != ord("r"):
            return None
        offset = int.from_bytes(payload[3:5], "little")
        count = int.from_bytes(payload[5:7], "little")
        return offset, count

    @staticmethod
    def _extract_response_data(data: bytes) -> bytes:
        if not data:
            return b""

        if len(data) >= 7:
            declared = int.from_bytes(data[:2], "big")
            # TunerStudio/Speeduino packets are length-prefixed:
            #   u16 length, payload(status + bytes), u32 crc
            # The dump can be truncated during capture, so accept packets
            # once the declared payload is present, even if CRC is absent.
            if 0 < declared <= len(data) - 2:
                payload = data[2 : 2 + declared]
                if payload and payload[0] == 0:
                    return payload[1:]
                return b""

        # Fallback for callers that already stripped the length prefix.
        if data[0] == 0:
            return data[1:]
        return data


@dataclass
class _PendingSegment:
    offset: int
    count: int
    data: bytearray


def decode_frame_fields(frame: bytes, fields: list[BinaryFieldRule]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for field in fields:
        raw = FixedFrameDecoder._read_raw(frame, field)
        if field.bit is not None:
            raw = (int(raw) >> int(field.bit)) & 1
        value = coerce_rule_value(raw, field.rule)
        merge_patch(patch, TelemetryMapper._to_patch(field.rule.field, value))
    return patch
