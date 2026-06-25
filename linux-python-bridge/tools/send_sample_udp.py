#!/usr/bin/env python3
from __future__ import annotations

import json
import socket
import time


def send(channel: str, value: float, host: str = "127.0.0.1", port: int = 8765) -> None:
    packet = {
        "source": "tunerstudio",
        "type": "outputChannel",
        "ecu": "sample",
        "channel": channel,
        "value": value,
        "ts": int(time.time() * 1000),
    }
    data = json.dumps(packet, separators=(",", ":")).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.sendto(data, (host, port))


def main() -> None:
    send("rpm", 2100)
    send("speedKph", 72)
    send("clt", 88)
    send("batt", 13.8)
    send("gpsLat", 52.5)
    send("gpsLng", 13.4)


if __name__ == "__main__":
    main()

