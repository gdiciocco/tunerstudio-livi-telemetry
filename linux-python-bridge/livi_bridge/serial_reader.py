from __future__ import annotations

import os
import select
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mapper import merge_patch
from .usbmon_decoder import TunerStudioSerialDecoder

try:
    import termios
except ImportError:  # pragma: no cover - active serial mode is POSIX-only.
    termios = None  # type: ignore[assignment]


def _baud_rates() -> dict[int, int]:
    if termios is None:
        return {}
    return {
        9600: termios.B9600,
        19200: termios.B19200,
        38400: termios.B38400,
        57600: termios.B57600,
        115200: termios.B115200,
        230400: getattr(termios, "B230400", termios.B115200),
        460800: getattr(termios, "B460800", termios.B115200),
        921600: getattr(termios, "B921600", termios.B115200),
    }


@dataclass(frozen=True)
class SerialReadCommand:
    offset: int
    count: int
    can_id: int = 0
    page: int = 0x30

    def to_bytes(self) -> bytes:
        payload = bytes(
            [
                ord("r"),
                self.can_id & 0xFF,
                self.page & 0xFF,
                self.offset & 0xFF,
                (self.offset >> 8) & 0xFF,
                self.count & 0xFF,
                (self.count >> 8) & 0xFF,
            ]
        )
        # This mirrors the packets observed in the usbmon dump:
        # u16 payload length, payload, 4 CRC bytes. Speeduino-style serial
        # realtime reads accept zero CRC bytes for this command family.
        return len(payload).to_bytes(2, "big") + payload + b"\x00\x00\x00\x00"


@dataclass
class _SerialDecoderEvent:
    event_type: str
    is_input: bool
    data: bytes
    xfer_type: int = 3
    status: int = 0


class PosixSerialPort:
    def __init__(self, path: Path, baud: int, timeout: float) -> None:
        self.path = path
        self.baud = baud
        self.timeout = timeout
        self.fd: int | None = None
        self._previous_attrs: list[Any] | None = None

    def __enter__(self) -> "PosixSerialPort":
        if sys.platform == "win32":
            raise RuntimeError("Active serial mode is intended for Linux/POSIX systems")
        if termios is None:
            raise RuntimeError("Active serial mode requires termios")
        baud_rates = _baud_rates()
        if self.baud not in baud_rates:
            raise ValueError(f"Unsupported baud rate: {self.baud}")

        self.fd = os.open(str(self.path), os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self._previous_attrs = termios.tcgetattr(self.fd)
        attrs = termios.tcgetattr(self.fd)
        speed = baud_rates[self.baud]

        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
        attrs[3] = 0
        attrs[4] = speed
        attrs[5] = speed
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        os.set_blocking(self.fd, False)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.fd is not None and self._previous_attrs is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSANOW, self._previous_attrs)
            except termios.error:
                pass
        if self.fd is not None:
            os.close(self.fd)
        self.fd = None

    def transact(self, request: bytes) -> bytes:
        if self.fd is None:
            raise RuntimeError("Serial port is not open")
        self._write_all(request)
        header = self._read_exact(2)
        declared = int.from_bytes(header, "big")
        if declared <= 0:
            raise TimeoutError("Serial response declared zero bytes")
        body = self._read_exact(declared)
        crc = self._read_exact(4)
        return header + body + crc

    def _write_all(self, data: bytes) -> None:
        if self.fd is None:
            raise RuntimeError("Serial port is not open")
        offset = 0
        deadline = time.monotonic() + self.timeout
        while offset < len(data):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out writing to {self.path}")
            _read, ready, _error = select.select([], [self.fd], [], remaining)
            if not ready:
                continue
            offset += os.write(self.fd, data[offset:])

    def _read_exact(self, count: int) -> bytes:
        deadline = time.monotonic() + self.timeout
        data = bytearray()
        while len(data) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out reading {count} bytes from {self.path}")
            ready, _write, _error = select.select([self.fd], [], [], remaining)
            if not ready:
                continue
            chunk = os.read(self.fd, count - len(data))
            if not chunk:
                continue
            data.extend(chunk)
        return bytes(data)


class ActiveTunerStudioSerialReader:
    def __init__(
        self,
        serial_port: Path,
        decoder: TunerStudioSerialDecoder,
        baud: int,
        timeout: float,
        read_size: int,
        can_id: int,
        page: int,
        print_raw: bool = False,
    ) -> None:
        if read_size <= 0:
            raise ValueError("read_size must be greater than zero")
        self.serial_port = serial_port
        self.decoder = decoder
        self.baud = baud
        self.timeout = timeout
        self.read_size = read_size
        self.can_id = can_id
        self.page = page
        self.print_raw = print_raw

    def read_once(self, port: PosixSerialPort) -> dict[str, Any]:
        pending: dict[str, Any] = {}
        for offset in range(0, self.decoder.frame_length, self.read_size):
            count = min(self.read_size, self.decoder.frame_length - offset)
            command = SerialReadCommand(offset=offset, count=count, can_id=self.can_id, page=self.page).to_bytes()
            if self.print_raw:
                print(f"serial out {command.hex()}", file=sys.stderr, flush=True)
            self.decoder.decode_usbmon_event(_SerialDecoderEvent("S", False, command))
            response = port.transact(command)
            if self.print_raw:
                print(f"serial in  {response.hex()}", file=sys.stderr, flush=True)
            self.decoder.decode_usbmon_event(_SerialDecoderEvent("C", True, response))
            for patch in self.decoder.flush():
                merge_patch(pending, patch)
        return pending

    def open(self) -> PosixSerialPort:
        return PosixSerialPort(path=self.serial_port, baud=self.baud, timeout=self.timeout)
