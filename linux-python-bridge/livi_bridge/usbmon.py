from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path


USBMON_XFER_BULK = 3
USB_DIR_IN = 0x80


@dataclass(frozen=True)
class UsbDeviceRef:
    serial_port: Path
    busnum: int
    devnum: int
    usbmon_path: Path
    sysfs_device: Path


@dataclass(frozen=True)
class UsbMonEvent:
    event_type: str
    xfer_type: int
    epnum: int
    devnum: int
    busnum: int
    status: int
    length: int
    len_cap: int
    ts_sec: int
    ts_usec: int
    data: bytes

    @property
    def is_input(self) -> bool:
        return bool(self.epnum & USB_DIR_IN)

    @property
    def endpoint(self) -> int:
        return self.epnum & 0x0F


class UsbMonPacket(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint64),
        ("type", ctypes.c_ubyte),
        ("xfer_type", ctypes.c_ubyte),
        ("epnum", ctypes.c_ubyte),
        ("devnum", ctypes.c_ubyte),
        ("busnum", ctypes.c_uint16),
        ("flag_setup", ctypes.c_byte),
        ("flag_data", ctypes.c_byte),
        ("ts_sec", ctypes.c_int64),
        ("ts_usec", ctypes.c_int32),
        ("status", ctypes.c_int32),
        ("length", ctypes.c_uint32),
        ("len_cap", ctypes.c_uint32),
        ("setup_or_iso", ctypes.c_ubyte * 8),
    ]


class MonGetArg(ctypes.Structure):
    _fields_ = [
        ("hdr", ctypes.c_void_p),
        ("data", ctypes.c_void_p),
        ("alloc", ctypes.c_size_t),
    ]


def resolve_serial_usb_device(serial_port: str | Path, sys_class_tty: Path = Path("/sys/class/tty")) -> UsbDeviceRef:
    serial_path = Path(serial_port).resolve()
    tty_name = serial_path.name
    tty_device = (sys_class_tty / tty_name / "device").resolve()

    for candidate in [tty_device, *tty_device.parents]:
        bus_file = candidate / "busnum"
        dev_file = candidate / "devnum"
        if bus_file.is_file() and dev_file.is_file():
            busnum = int(bus_file.read_text(encoding="ascii").strip(), 10)
            devnum = int(dev_file.read_text(encoding="ascii").strip(), 10)
            return UsbDeviceRef(
                serial_port=serial_path,
                busnum=busnum,
                devnum=devnum,
                usbmon_path=Path(f"/dev/usbmon{busnum}"),
                sysfs_device=candidate,
            )

    raise RuntimeError(f"Cannot resolve USB bus/device from serial port {serial_port}")


class UsbMonReader:
    def __init__(
        self,
        device: UsbDeviceRef,
        capture_size: int = 4096,
        usbmon_path: Path | None = None,
        direction: str = "in",
    ) -> None:
        self.device = device
        self.capture_size = capture_size
        self.usbmon_path = usbmon_path or device.usbmon_path
        self.direction = direction
        self._fd: int | None = None

    def __enter__(self) -> "UsbMonReader":
        self.open()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def open(self) -> None:
        self._fd = os.open(self.usbmon_path, os.O_RDONLY)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def read_event(self) -> UsbMonEvent:
        if self._fd is None:
            raise RuntimeError("UsbMonReader is not open")

        record = os.read(self._fd, ctypes.sizeof(UsbMonPacket) + self.capture_size)
        if len(record) < ctypes.sizeof(UsbMonPacket):
            raise InterruptedError("short usbmon record")

        header = UsbMonPacket.from_buffer_copy(record[: ctypes.sizeof(UsbMonPacket)])
        data_len = min(int(header.len_cap), self.capture_size, max(0, len(record) - ctypes.sizeof(UsbMonPacket)))
        return UsbMonEvent(
            event_type=chr(header.type),
            xfer_type=int(header.xfer_type),
            epnum=int(header.epnum),
            devnum=int(header.devnum),
            busnum=int(header.busnum),
            status=int(header.status),
            length=int(header.length),
            len_cap=int(header.len_cap),
            ts_sec=int(header.ts_sec),
            ts_usec=int(header.ts_usec),
            data=record[ctypes.sizeof(UsbMonPacket) : ctypes.sizeof(UsbMonPacket) + data_len],
        )

    def matching_payloads(self):
        while True:
            event = self.read_event()
            if not self._matches(event):
                continue
            yield event.data

    def _matches(self, event: UsbMonEvent) -> bool:
        if event.xfer_type != USBMON_XFER_BULK:
            return False
        if event.busnum != self.device.busnum or event.devnum != self.device.devnum:
            return False
        if not event.data:
            return False

        if event.is_input:
            if event.event_type != "C" or event.status != 0:
                return False
        else:
            if event.event_type != "S":
                return False

        if self.direction == "in":
            return event.is_input
        if self.direction == "out":
            return not event.is_input
        return self.direction == "both"


def mon_iocx_getx() -> int:
    return _iow(0x92, 10, ctypes.sizeof(MonGetArg))


def _iow(ioc_type: int, nr: int, size: int) -> int:
    ioc_nrbits = 8
    ioc_typebits = 8
    ioc_sizebits = 14
    ioc_nrshift = 0
    ioc_typeshift = ioc_nrshift + ioc_nrbits
    ioc_sizeshift = ioc_typeshift + ioc_typebits
    ioc_dirshift = ioc_sizeshift + ioc_sizebits
    ioc_write = 1
    return (ioc_write << ioc_dirshift) | (ioc_type << ioc_typeshift) | (nr << ioc_nrshift) | (size << ioc_sizeshift)
