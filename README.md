# TunerStudio / TSDash to f-io LIVI telemetry bridge

Telemetry bridge for sending engine and vehicle data from **TunerStudio** or **TSDash** to an **[f-io/LIVI](https://github.com/f-io/LIVI)** dashboard.

Italian documentation is available here: [README.it.md](README.it.md).

This project provides two main integration paths:

1. **Linux console application**: the preferred and most developed path, especially for **TSDash**, because TSDash does not support TunerStudio plugins. It can passively read existing USB serial traffic through `/dev/usbmon`, or receive UDP packets from the plugin.
2. **TunerStudio Java plugin**: useful when running full TunerStudio, which can load Java plugins. The plugin works, but it has received less field testing and development attention than the Linux console path.

The project also includes a **demo mode** that sends plausible driving telemetry to LIVI without an ECU, TunerStudio, TSDash, or a serial connection.

## What It Does

- Converts TunerStudio-style channels such as `rpm`, `vss`, `coolant`, `iat`, `map`, and `afr` into LIVI telemetry fields such as `rpm`, `speedKph`, `coolantC`, `iatC`, `mapKpa`, and `afr`.
- Sends Socket.IO/WebSocket `telemetry:push` events to LIVI.
- Can derive a usbmon decoding map from a TunerStudio `mainController.ini`.
- Can observe an already-running TunerStudio/TSDash serial session without opening the serial port or writing to the ECU.
- Includes helper tools for LIVI/TunerStudio field mapping, TunerStudio dashboard extraction, `custom.ini` formulas, and `.inc` lookup tables.

## Which Mode Should I Use?

| Situation | Recommended mode |
| --- | --- |
| You use TSDash on Linux | Linux console with `--source usbmon` |
| You want the bridge itself to talk to the ECU serial port | Linux console with `--source serial` |
| You use full TunerStudio and want a built-in integration | TunerStudio plugin in `direct` mode |
| You use full TunerStudio but want the Linux app to handle mapping and LIVI output | TunerStudio plugin in `bridge` mode + Linux console with `--source udp` |
| You only want to make the LIVI dashboard move | Linux console with `--source demo` |
| You are debugging unstable or implausible values | Linux console with `--dry-run --print-raw` |

## Data Paths

TunerStudio plugin in direct mode:

```text
TunerStudio -> Java plugin -> LIVI
```

TunerStudio plugin in bridge mode:

```text
TunerStudio -> Java plugin -> UDP -> Linux console -> LIVI
```

TSDash or TunerStudio without plugins, passive read-only capture:

```text
TSDash/TunerStudio <-> USB serial ECU -> /dev/usbmon -> Linux console -> LIVI
```

Active serial polling without TunerStudio/TSDash:

```text
Linux console -> USB serial ECU -> realtime reads -> LIVI
```

Demo mode:

```text
Linux console -> simulated telemetry -> LIVI
```

## Requirements

For the Linux console application:

- Linux.
- Python 3.10 or newer.
- Network access to the machine where LIVI is running.
- `sudo` permissions for usbmon mode on most Linux distributions.

For the TunerStudio plugin:

- Full TunerStudio, not TSDash.
- Java as provided by or available to TunerStudio.
- The real `TunerStudioPluginAPI.jar` if you want to rebuild the plugin.

Note for less experienced users: commands shown in `bash` blocks are meant to be run in a terminal. If a tutorial or shell prompt shows a leading `$`, do not copy the `$` itself.

## Install The Linux Console

Open a terminal and enter the console application folder:

```bash
cd linux-python-bridge
```

Create an isolated Python environment. This keeps the bridge dependencies separate from the rest of the system:

```bash
python3 -m venv .venv
```

Activate it:

```bash
. .venv/bin/activate
```

When the environment is active, your shell prompt often starts with `(.venv)`.

Install the bridge:

```bash
pip install -e .
```

Check that the command is available:

```bash
tunerstudio-livi-bridge --help
```

If the command is not found, make sure `.venv` is active.

## Demo Mode

Demo mode is the best first test. It does not need an ECU, serial port, TunerStudio, or TSDash.

Replace `livi.local` with the hostname or IP address of the machine where LIVI is listening:

```bash
tunerstudio-livi-bridge \
  --source demo \
  --livi-url ws://livi.local:4000 \
  --hz 20
```

To see what would be sent without connecting to LIVI:

```bash
tunerstudio-livi-bridge \
  --source demo \
  --dry-run \
  --demo-duration 5 \
  --hz 5
```

In dry-run mode you should see JSON lines printed in the terminal. This is useful before connecting to a real dashboard.

## TSDash / usbmon Mode

This is the main mode for TSDash.

TSDash does not load TunerStudio plugins. Instead, the Linux console observes the existing USB serial communication that TSDash is already using. It does not open the serial port and does not write to the ECU; it only reads from `/dev/usbmon`.

### 1. Enable usbmon

On many Linux distributions you need:

```bash
sudo modprobe usbmon
```

Check that usbmon devices exist:

```bash
ls /dev/usbmon*
```

You should see files such as `/dev/usbmon0`, `/dev/usbmon1`, and so on.

### 2. Find The Serial Port

The serial port usually looks like one of these:

```text
/dev/ttyUSB0
/dev/ttyACM0
```

Use the same serial port that TSDash or TunerStudio uses to communicate with the ECU.

### 3. Start With A TunerStudio INI File

The easiest and safest option is to pass the TunerStudio project `mainController.ini`. The bridge uses it to understand where the output channels are located in the serial data.

Example:

```bash
sudo tunerstudio-livi-bridge \
  --source usbmon \
  --serial-port /dev/ttyUSB0 \
  --tunerstudio-ini ~/TunerStudioProjects/ExampleProject/projectCfg/mainController.ini \
  --livi-url ws://livi.local:4000
```

If you do not know where the INI file is, look inside the TunerStudio project folder. It is commonly under:

```text
TunerStudioProjects/ProjectName/projectCfg/mainController.ini
```

### 4. Test In Dry-Run First

Before sending anything to LIVI, print the payloads:

```bash
sudo tunerstudio-livi-bridge \
  --source usbmon \
  --serial-port /dev/ttyUSB0 \
  --tunerstudio-ini ~/TunerStudioProjects/ExampleProject/projectCfg/mainController.ini \
  --dry-run \
  --print-raw
```

If the values look plausible, remove `--dry-run --print-raw` and add `--livi-url`.

### 5. Export The Generated Config

To inspect or edit the map generated from the INI:

```bash
tunerstudio-livi-bridge \
  --source usbmon \
  --tunerstudio-ini ~/TunerStudioProjects/ExampleProject/projectCfg/mainController.ini \
  --dump-generated-usbmon-config generated-usbmon-map.json \
  --dry-run
```

You can then run from that JSON file:

```bash
sudo tunerstudio-livi-bridge \
  --source usbmon \
  --serial-port /dev/ttyUSB0 \
  --usbmon-config generated-usbmon-map.json \
  --livi-url ws://livi.local:4000
```

## Active Serial Mode

Active serial mode is for cases where you want the Linux console to talk directly to the ECU, without TunerStudio or TSDash running on that serial port.

It emulates the realtime output-channel reads observed in the usbmon dump: it sends TunerStudio-style `r` read commands, receives length-prefixed realtime responses, decodes the output-channel block, and sends LIVI payloads like the other modes.

Important: unlike usbmon mode, this mode opens the serial port and writes to it. Do not use it at the same time as TunerStudio or TSDash on the same serial device.

Use this mode when the Linux box running the bridge is the only program talking to the ECU. If TSDash or TunerStudio is already connected, use `--source usbmon` instead so the bridge only observes the existing traffic.

The serial exchange uses the same framed shape used by the observed TunerStudio traffic:

```text
2-byte payload length + command payload + 4-byte CRC32
```

For the default realtime read, the bridge sends commands like this:

```text
serial out 000772003000007900b9476445
```

The final four bytes are the CRC32. Older development builds used zero CRC bytes; current firmware may reject that with a short status response such as `000182d1b40d81`, where `0x82` is the ECU error status. The bridge now uses CRC32 by default.

Example using a TunerStudio INI:

```bash
tunerstudio-livi-bridge \
  --source serial \
  --serial-port /dev/ttyUSB0 \
  --tunerstudio-ini ~/TunerStudioProjects/ExampleProject/projectCfg/mainController.ini \
  --livi-url ws://livi.local:4000
```

Start with dry-run if you are not sure:

```bash
tunerstudio-livi-bridge \
  --source serial \
  --serial-port /dev/ttyUSB0 \
  --tunerstudio-ini ~/TunerStudioProjects/ExampleProject/projectCfg/mainController.ini \
  --dry-run \
  --print-raw
```

In a good dry-run you should see longer `serial in` blocks followed by JSON payloads:

```text
serial out 000772003000007900b9476445
serial in  007a00...
{"event":"telemetry:push","payload":{"rpm":0.0,"mapKpa":10.0,...}}
```

If you only see repeated `drop serial poll: ECU returned serial status 0x82`, the bridge is reaching the serial device but the ECU rejected the request. Check `--serial-page`, `--serial-read-size`, `--serial-can-id`, and leave `--serial-command-crc crc32` unless you are testing a firmware known to accept zero CRC.

Useful options:

```text
--serial-baud 115200
--serial-timeout 0.5
--serial-read-size 121
--serial-can-id 0
--serial-page 0x30
--serial-command-crc crc32
--serial-poll-interval 0.05
```

The defaults match the packet shape observed in the usbmon reference dump. If your ECU firmware uses different realtime page or block sizing, adjust `--serial-page` and `--serial-read-size`. Active serial commands use a real CRC32 by default; `--serial-command-crc zero` is only for older or permissive firmware tests.

## TunerStudio Plugin

The plugin is useful when you run full TunerStudio on a computer that can load Java plugins.

Important: the plugin path is less field-tested than the Linux console path. Use it when you need direct integration inside TunerStudio. For TSDash, use the Linux console.

### Install The Prebuilt Jar

The prebuilt plugin jar is here:

```text
tunerstudio-plugin/build/tunerstudio-livi-telemetry-plugin.jar
```

Copy the jar into the plugin/lib folder used by your TunerStudio installation, following the same method used for TunerStudio example plugins.

The jar manifest contains:

```text
ApplicationPlugin: io.fio.livi.tunerstudio.LiviTelemetryPlugin
```

### Configure The Plugin

The plugin configuration file is:

```text
livi-telemetry.properties
```

The plugin searches for it in this order:

1. an explicit JVM property: `-Dlivi.telemetry.config=...`
2. the same directory as the plugin jar
3. TunerStudio's working directory
4. `~/.livi/tunerstudio-livi.properties`

For a simple installation, place `livi-telemetry.properties` next to the jar.

### Plugin Direct Mode

In direct mode, the plugin sends directly to LIVI through Socket.IO/WebSocket:

```properties
livi.telemetry.mode=direct
livi.telemetry.remote.host=livi.local
livi.telemetry.remote.port=4000
livi.telemetry.event=telemetry:push
livi.telemetry.hz=20
livi.telemetry.channels=*
```

You can also set the full URL:

```properties
livi.telemetry.livi.url=ws://livi.local:4000
```

### Plugin Bridge Mode

In bridge mode, the plugin sends raw channel updates to the Linux console over UDP. The console handles mapping and LIVI output.

Plugin configuration:

```properties
livi.telemetry.mode=bridge
livi.telemetry.udp.host=127.0.0.1
livi.telemetry.udp.port=8765
livi.telemetry.channels=*
```

Console command:

```bash
tunerstudio-livi-bridge \
  --source udp \
  --listen-host 127.0.0.1 \
  --listen-port 8765 \
  --livi-url ws://livi.local:4000
```

If the plugin and the Linux console run on different machines, set `udp.host` to the Linux machine hostname or IP address, and make sure the firewall allows UDP on the selected port.

### Rebuild The Plugin

You need the real `TunerStudioPluginAPI.jar`, not the javadoc jar.

```bash
cd tunerstudio-plugin
chmod +x build.sh
./build.sh /path/to/TunerStudioPluginAPI.jar
```

The output is:

```text
tunerstudio-plugin/build/tunerstudio-livi-telemetry-plugin.jar
```

## Field Mapping

LIVI expects specific field names, for example:

```text
rpm
speedKph
gear
coolantC
iatC
batteryV
fuelPct
mapKpa
baroKpa
afr
gps.lat
gps.lng
```

This repository includes a TSV mapping file:

```text
livi-tunerstudio-field-map.tsv
```

The important columns are:

```text
livi_field
tunerstudio_field
```

Example:

```text
rpm        rpm
speedKph   vss
fuelPct    benzina
```

Fields without a known match can be left empty.

## Custom.ini, .inc Tables, And Conversions

Some TunerStudio projects do not send the final dashboard value directly. The serial stream may contain a raw channel that is later transformed by `custom.ini` formulas or `.inc` lookup tables.

Conceptual example:

```ini
benzina = { table(auxin_gauge0, "benzina.inc") }, "L"
```

In this case the serial stream contains `auxin_gauge0`, while the dashboard displays `benzina` after a lookup table conversion.

This helper can use TSV mappings, `custom.ini`, and `.inc` files to update LIVI JSON with the correct logic:

```bash
python tools/update_livi_json_from_tsv.py --help
```

## Helper Tools

Extract `OutputChannel` and gauge title pairs from a TunerStudio dashboard:

```bash
python tools/extract_dash_gauge_channels.py dashboard.dsh > dash-gauge-outputchannel-title.tsv
```

Update a LIVI JSON file from the TSV mapping:

```bash
python tools/update_livi_json_from_tsv.py \
  --input existing-livi.json \
  --tsv livi-tunerstudio-field-map.tsv \
  --output updated-livi.json
```

Always review generated files before using them on a real vehicle.

## Quick Tests

### Test The Console Without LIVI

```bash
tunerstudio-livi-bridge --source demo --dry-run --demo-duration 3
```

If JSON appears in the terminal, the console is working.

### Test UDP Without TunerStudio

Terminal 1:

```bash
tunerstudio-livi-bridge --source udp --dry-run
```

Terminal 2:

```bash
python tools/send_sample_udp.py
```

You should see a payload similar to:

```json
{"event":"telemetry:push","payload":{"rpm":2100.0,"speedKph":72.0,"ts":1234567890}}
```

## Troubleshooting

### Nothing Arrives In LIVI

- Check that the URL starts with `ws://` or `wss://`.
- Check LIVI hostname and port.
- Try `--source demo --dry-run` first.
- If you use plugin direct mode, open the plugin panel in TunerStudio and check the status.
- If you send UDP between two machines, check firewall and network routing.
- If you use active serial mode, confirm that no other program is already using the same serial port.

### Active Serial Mode Does Not Feed LIVI

- First run the same command with `--dry-run --print-raw`. This bypasses LIVI and shows whether the ECU is returning data.
- A good serial exchange prints `serial out`, then a longer `serial in`, then a `telemetry:push` JSON line.
- `ECU returned serial status 0x82` means the ECU rejected the read command. Keep `--serial-command-crc crc32` and verify page, CAN id, read size, and that the selected port is the ECU.
- Timeouts usually mean the wrong serial port, wrong baud rate, or another application already owns the port.
- If demo mode works but serial mode does not, the LIVI side is probably fine; debug the serial exchange first.

### usbmon Does Not Open

Try:

```bash
sudo modprobe usbmon
ls /dev/usbmon*
```

Then run the bridge again with `sudo`.

### Values Are Unstable Or Implausible

- Prefer `--tunerstudio-ini` over a hand-written JSON map.
- Make sure the serial port belongs to the ECU, not to another USB device.
- Use `--dry-run --print-raw` to inspect payloads before sending them to LIVI.
- Check for formulas in `custom.ini` and lookup tables in `.inc` files.

### TSDash Does Not See The Plugin

That is expected. TSDash does not support TunerStudio plugins. Use the Linux console with `--source usbmon`.


## Project Status

- Linux console: most developed path and recommended especially for TSDash.
- TunerStudio plugin: working and buildable, but less field-tested.
- Mapping: ECU and TunerStudio project dependent. Always check dry-run output and real values before relying on it while driving.
