#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livi_bridge.tunerstudio_ini import decoder_from_tunerstudio_ini
from livi_bridge.usbmon import UsbMonEvent
from livi_bridge.usbmon_decoder import FixedFrameDecoder


USBMON_HEADER = struct.Struct("<QBBBBHbbqiiII8s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay a binary /dev/usbmon dump through the LIVI decoder.")
    parser.add_argument("dump", type=Path, help="Binary usbmon dump captured from /dev/usbmonN.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path, help="usbmon JSON config.")
    source.add_argument("--tunerstudio-ini", type=Path, help="TunerStudio mainController.ini.")
    parser.add_argument("--bus", type=int, help="USB bus number to filter.")
    parser.add_argument("--dev", type=int, help="USB device number to filter.")
    parser.add_argument("--limit", type=int, default=20, help="Number of decoded payloads to print.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    decoder = (
        decoder_from_tunerstudio_ini(args.tunerstudio_ini)
        if args.tunerstudio_ini is not None
        else FixedFrameDecoder.load(args.config)
    )

    data = args.dump.read_bytes()
    offset = 0
    decoded = 0
    while offset + USBMON_HEADER.size <= len(data):
        header = USBMON_HEADER.unpack_from(data, offset)
        _id, type_byte, xfer_type, epnum, devnum, busnum, _fs, _fd, ts_sec, ts_usec, status, length, len_cap, _setup = header
        payload = data[offset + USBMON_HEADER.size : offset + USBMON_HEADER.size + len_cap]
        offset += USBMON_HEADER.size + len_cap

        if args.bus is not None and busnum != args.bus:
            continue
        if args.dev is not None and devnum != args.dev:
            continue
        if xfer_type != 3 or not payload:
            continue

        event = UsbMonEvent(chr(type_byte), xfer_type, epnum, devnum, busnum, status, length, len_cap, ts_sec, ts_usec, payload)
        if event.is_input:
            if event.event_type != "C" or event.status != 0:
                continue
        elif event.event_type != "S":
            continue

        if hasattr(decoder, "decode_usbmon_event"):
            patches = decoder.decode_usbmon_event(event)
        elif event.is_input:
            patches = decoder.decode_bytes(payload)
        else:
            patches = []

        for patch in patches:
            print(json.dumps(patch, separators=(",", ":"), sort_keys=True))
            decoded += 1
            if decoded >= args.limit:
                return 0

    if hasattr(decoder, "flush"):
        for patch in decoder.flush():
            print(json.dumps(patch, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
