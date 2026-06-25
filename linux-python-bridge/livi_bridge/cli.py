from __future__ import annotations

import argparse
import json
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .demo import DemoTelemetryGenerator
from .emitter import DryRunEmitter, Emitter, SocketIoEmitter
from .mapper import TelemetryMapper, merge_patch
from .serial_reader import ActiveTunerStudioSerialReader
from .tunerstudio_ini import decoder_from_tunerstudio_ini, write_generated_usbmon_config
from .usbmon import UsbMonReader, resolve_serial_usb_device
from .usbmon_decoder import FixedFrameDecoder, TunerStudioSerialDecoder


class Bridge:
    def __init__(
        self,
        mapper: TelemetryMapper,
        emitter: Emitter,
        event: str,
        listen_host: str,
        listen_port: int,
        hz: float,
        print_raw: bool,
    ) -> None:
        self.mapper = mapper
        self.emitter = emitter
        self.event = event
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.interval = 1.0 / hz
        self.print_raw = print_raw
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.pending: dict[str, Any] = {}

    def run(self) -> None:
        self.emitter.connect()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.bind((self.listen_host, self.listen_port))
            udp.settimeout(0.25)
            sender = threading.Thread(target=self._send_loop, name="livi-send-loop", daemon=True)
            sender.start()
            print(f"listening udp://{self.listen_host}:{self.listen_port}", file=sys.stderr, flush=True)

            while not self.stop_event.is_set():
                try:
                    data, _addr = udp.recvfrom(65535)
                except socket.timeout:
                    continue

                try:
                    packet = json.loads(data.decode("utf-8"))
                    if self.print_raw:
                        print(json.dumps(packet, separators=(",", ":")), file=sys.stderr, flush=True)
                    patch = self.mapper.map_packet(packet)
                except Exception as exc:
                    print(f"drop packet: {exc}", file=sys.stderr, flush=True)
                    continue

                if patch:
                    with self.lock:
                        merge_patch(self.pending, patch)

            sender.join(timeout=2.0)
            self._flush()
            self.emitter.close()

    def stop(self, *_args: object) -> None:
        self.stop_event.set()

    def _send_loop(self) -> None:
        while not self.stop_event.is_set():
            time.sleep(self.interval)
            self._flush()

    def _flush(self) -> None:
        with self.lock:
            if not self.pending:
                return
            payload = dict(self.pending)
            self.pending.clear()

        payload.setdefault("ts", int(time.time() * 1000))
        self.emitter.emit(self.event, payload)


class UsbMonBridge:
    def __init__(
        self,
        decoder: FixedFrameDecoder,
        emitter: Emitter,
        event: str,
        serial_port: Path,
        usbmon_path: Path | None,
        direction: str,
        capture_size: int,
        hz: float,
        print_raw: bool,
    ) -> None:
        self.decoder = decoder
        self.emitter = emitter
        self.event = event
        self.serial_port = serial_port
        self.usbmon_path = usbmon_path
        self.direction = direction
        self.capture_size = capture_size
        self.interval = 1.0 / hz
        self.print_raw = print_raw
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.pending: dict[str, Any] = {}

    def run(self) -> None:
        self.emitter.connect()
        device = resolve_serial_usb_device(self.serial_port)
        selected_usbmon = self.usbmon_path or device.usbmon_path
        print(
            f"listening {selected_usbmon} for {self.serial_port} "
            f"(bus={device.busnum}, dev={device.devnum}, direction={self.direction})",
            file=sys.stderr,
            flush=True,
        )

        with UsbMonReader(
            device=device,
            capture_size=self.capture_size,
            usbmon_path=selected_usbmon,
            direction=self.direction,
        ) as reader:
            sender = threading.Thread(target=self._send_loop, name="livi-send-loop", daemon=True)
            sender.start()
            while not self.stop_event.is_set():
                try:
                    payload = reader.read_event()
                except InterruptedError:
                    continue

                if not reader._matches(payload):
                    continue
                if self.print_raw:
                    direction = "in" if payload.is_input else "out"
                    print(f"{direction} {payload.data.hex()}", file=sys.stderr, flush=True)

                try:
                    if hasattr(self.decoder, "decode_usbmon_event"):
                        patches = self.decoder.decode_usbmon_event(payload)
                    elif payload.is_input:
                        patches = self.decoder.decode_bytes(payload.data)
                    else:
                        patches = []
                except Exception as exc:
                    print(f"drop usbmon payload: {exc}", file=sys.stderr, flush=True)
                    continue

                if patches:
                    with self.lock:
                        for patch in patches:
                            merge_patch(self.pending, patch)

            sender.join(timeout=2.0)
            if hasattr(self.decoder, "flush"):
                for patch in self.decoder.flush():
                    with self.lock:
                        merge_patch(self.pending, patch)
            self._flush()
            self.emitter.close()

    def stop(self, *_args: object) -> None:
        self.stop_event.set()

    def _send_loop(self) -> None:
        while not self.stop_event.is_set():
            time.sleep(self.interval)
            self._flush()

    def _flush(self) -> None:
        with self.lock:
            if not self.pending:
                return
            payload = dict(self.pending)
            self.pending.clear()

        payload.setdefault("ts", int(time.time() * 1000))
        self.emitter.emit(self.event, payload)


class DemoBridge:
    def __init__(
        self,
        generator: DemoTelemetryGenerator,
        emitter: Emitter,
        event: str,
        hz: float,
        duration: float | None,
    ) -> None:
        self.generator = generator
        self.emitter = emitter
        self.event = event
        self.interval = 1.0 / hz
        self.duration = duration
        self.stop_event = threading.Event()

    def run(self) -> None:
        self.emitter.connect()
        start = time.monotonic()
        print("streaming demo telemetry", file=sys.stderr, flush=True)
        try:
            while not self.stop_event.is_set():
                elapsed = time.monotonic() - start
                if self.duration is not None and elapsed >= self.duration:
                    break
                payload = self.generator.sample(elapsed)
                payload["ts"] = int(time.time() * 1000)
                self.emitter.emit(self.event, payload)
                time.sleep(self.interval)
        finally:
            self.emitter.close()

    def stop(self, *_args: object) -> None:
        self.stop_event.set()


class SerialBridge:
    def __init__(
        self,
        reader: ActiveTunerStudioSerialReader,
        emitter: Emitter,
        event: str,
        poll_interval: float,
    ) -> None:
        self.reader = reader
        self.emitter = emitter
        self.event = event
        self.poll_interval = poll_interval
        self.stop_event = threading.Event()

    def run(self) -> None:
        self.emitter.connect()
        print(
            f"polling {self.reader.serial_port} at {self.reader.baud} baud "
            f"(read_size={self.reader.read_size})",
            file=sys.stderr,
            flush=True,
        )
        try:
            with self.reader.open() as port:
                while not self.stop_event.is_set():
                    started = time.monotonic()
                    try:
                        payload = self.reader.read_once(port)
                    except TimeoutError as exc:
                        print(f"serial timeout: {exc}", file=sys.stderr, flush=True)
                        payload = {}
                    except Exception as exc:
                        print(f"drop serial poll: {exc}", file=sys.stderr, flush=True)
                        payload = {}

                    if payload:
                        payload.setdefault("ts", int(time.time() * 1000))
                        self.emitter.emit(self.event, payload)

                    elapsed = time.monotonic() - started
                    delay = max(0.0, self.poll_interval - elapsed)
                    if delay:
                        self.stop_event.wait(delay)
        finally:
            self.emitter.close()

    def stop(self, *_args: object) -> None:
        self.stop_event.set()


def parse_int_auto(text: str) -> int:
    return int(text, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bridge TunerStudio telemetry to f-io/LIVI.")
    parser.add_argument("--source", choices=["udp", "usbmon", "serial", "demo"], default="udp", help="Telemetry source mode.")
    parser.add_argument("--listen-host", default="127.0.0.1", help="UDP host for the TunerStudio plugin.")
    parser.add_argument("--listen-port", type=int, default=8765, help="UDP port for the TunerStudio plugin.")
    parser.add_argument("--livi-url", default="ws://127.0.0.1:4000", help="LIVI Socket.IO URL.")
    parser.add_argument("--event", default="telemetry:push", help="Socket.IO event name.")
    parser.add_argument("--config", type=Path, help="Optional channel mapping JSON file.")
    parser.add_argument("--serial-port", type=Path, help="Serial port, for example /dev/ttyUSB0.")
    parser.add_argument("--usbmon-config", type=Path, help="Binary frame map for --source usbmon or --source serial.")
    parser.add_argument("--tunerstudio-ini", type=Path, help="TunerStudio mainController.ini to derive the realtime binary frame map.")
    parser.add_argument("--ini-endian", choices=["big", "little"], default="little", help="Endian for scalar values parsed from --tunerstudio-ini.")
    parser.add_argument("--dump-generated-usbmon-config", type=Path, help="Write the usbmon JSON generated from --tunerstudio-ini and exit.")
    parser.add_argument("--usbmon-device", type=Path, help="Override usbmon device, for example /dev/usbmon1.")
    parser.add_argument("--usbmon-direction", choices=["in", "out", "both"], default="both", help="USB bulk direction to decode.")
    parser.add_argument("--usbmon-capture-size", type=int, default=4096, help="Maximum captured bytes per usbmon event.")
    parser.add_argument("--serial-baud", type=int, default=115200, help="Baud rate for --source serial.")
    parser.add_argument("--serial-timeout", type=float, default=0.5, help="Serial read timeout in seconds for --source serial.")
    parser.add_argument("--serial-read-size", type=int, default=121, help="Bytes requested per TunerStudio realtime read in --source serial.")
    parser.add_argument("--serial-can-id", type=parse_int_auto, default=0, help="TunerStudio CAN id byte for active serial reads, decimal or 0xNN.")
    parser.add_argument("--serial-page", type=parse_int_auto, default=0x30, help="TunerStudio realtime page byte for active serial reads, decimal or 0xNN.")
    parser.add_argument("--serial-poll-interval", type=float, help="Seconds between active serial polls. Defaults to 1 / --hz.")
    parser.add_argument("--demo-cycle-seconds", type=float, default=90.0, help="Driving-cycle length for --source demo.")
    parser.add_argument("--demo-max-speed-kph", type=float, default=125.0, help="Maximum simulated speed for --source demo.")
    parser.add_argument("--demo-duration", type=float, help="Stop demo mode after this many seconds.")
    parser.add_argument("--hz", type=float, default=20.0, help="Maximum Socket.IO emit rate.")
    parser.add_argument("--dry-run", action="store_true", help="Print LIVI payloads instead of connecting to LIVI.")
    parser.add_argument("--print-raw", action="store_true", help="Print raw source packets/bytes to stderr.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    emitter: Emitter = DryRunEmitter() if args.dry_run else SocketIoEmitter(args.livi_url)

    if args.source == "demo":
        bridge = DemoBridge(
            generator=DemoTelemetryGenerator(
                cycle_seconds=args.demo_cycle_seconds,
                max_speed_kph=args.demo_max_speed_kph,
            ),
            emitter=emitter,
            event=args.event,
            hz=args.hz,
            duration=args.demo_duration,
        )
    elif args.source == "usbmon":
        if args.usbmon_config is None and args.tunerstudio_ini is None:
            parser.error("--source usbmon requires --usbmon-config or --tunerstudio-ini")
        if args.usbmon_config is not None and args.tunerstudio_ini is not None:
            parser.error("Use either --usbmon-config or --tunerstudio-ini, not both")
        if args.dump_generated_usbmon_config is not None:
            if args.tunerstudio_ini is None:
                parser.error("--dump-generated-usbmon-config requires --tunerstudio-ini")
            write_generated_usbmon_config(args.tunerstudio_ini, args.dump_generated_usbmon_config, endian=args.ini_endian)
            print(f"wrote {args.dump_generated_usbmon_config}", file=sys.stderr)
            return 0
        if args.serial_port is None:
            parser.error("--source usbmon requires --serial-port")

        decoder = (
            decoder_from_tunerstudio_ini(args.tunerstudio_ini, endian=args.ini_endian)
            if args.tunerstudio_ini is not None
            else FixedFrameDecoder.load(args.usbmon_config)
        )
        bridge = UsbMonBridge(
            decoder=decoder,
            emitter=emitter,
            event=args.event,
            serial_port=args.serial_port,
            usbmon_path=args.usbmon_device,
            direction=args.usbmon_direction,
            capture_size=args.usbmon_capture_size,
            hz=args.hz,
            print_raw=args.print_raw,
        )
    elif args.source == "serial":
        if args.usbmon_config is None and args.tunerstudio_ini is None:
            parser.error("--source serial requires --usbmon-config or --tunerstudio-ini")
        if args.usbmon_config is not None and args.tunerstudio_ini is not None:
            parser.error("Use either --usbmon-config or --tunerstudio-ini, not both")
        if args.serial_port is None:
            parser.error("--source serial requires --serial-port")

        decoder = (
            decoder_from_tunerstudio_ini(args.tunerstudio_ini, endian=args.ini_endian)
            if args.tunerstudio_ini is not None
            else FixedFrameDecoder.load(args.usbmon_config)
        )
        if not isinstance(decoder, TunerStudioSerialDecoder):
            parser.error("--source serial requires a tunerstudio_serial decoder")

        poll_interval = args.serial_poll_interval if args.serial_poll_interval is not None else 1.0 / args.hz
        bridge = SerialBridge(
            reader=ActiveTunerStudioSerialReader(
                serial_port=args.serial_port,
                decoder=decoder,
                baud=args.serial_baud,
                timeout=args.serial_timeout,
                read_size=args.serial_read_size,
                can_id=args.serial_can_id,
                page=args.serial_page,
                print_raw=args.print_raw,
            ),
            emitter=emitter,
            event=args.event,
            poll_interval=poll_interval,
        )
    else:
        mapper = TelemetryMapper.load(args.config)
        bridge = Bridge(
            mapper=mapper,
            emitter=emitter,
            event=args.event,
            listen_host=args.listen_host,
            listen_port=args.listen_port,
            hz=args.hz,
            print_raw=args.print_raw,
        )

    signal.signal(signal.SIGINT, bridge.stop)
    signal.signal(signal.SIGTERM, bridge.stop)

    try:
        bridge.run()
    except Exception as exc:
        print(f"bridge failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
