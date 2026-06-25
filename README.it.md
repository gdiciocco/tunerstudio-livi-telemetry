# TunerStudio / TSDash to f-io LIVI telemetry bridge

Questo progetto porta i dati motore letti da TunerStudio o TSDash dentro una dashboard [f-io/LIVI](https://github.com/f-io/LIVI).

La strada consigliata e la **console Linux**, che e la parte piu sviluppata del progetto. Supporta tre modalita pratiche:

- `--source serial`: feed LIVI standalone senza avviare TunerStudio o TSDash. Il bridge apre la seriale ECU ed esegue letture realtime in stile TunerStudio.
- `--source usbmon`: cattura passiva in sola lettura di una sessione TunerStudio/TSDash gia aperta. Usala quando un altro programma sta gia usando la seriale ECU.
- `--source udp`: riceve pacchetti dal plugin TunerStudio e lascia alla console Linux mapping e invio a LIVI.

Il progetto include anche un **plugin Java per TunerStudio** completo e una **modalita demo** per muovere LIVI con dati plausibili senza ECU o seriale. Il plugin funziona, ma ha ricevuto meno test sul campo rispetto alla console Linux.

## Cosa Fa

- Converte canali TunerStudio, per esempio `rpm`, `vss`, `coolant`, `iat`, `map`, `afr`, in campi LIVI come `rpm`, `speedKph`, `coolantC`, `iatC`, `mapKpa`, `afr`.
- Invia a LIVI eventi Socket.IO/WebSocket `telemetry:push`.
- Puo ricavare la mappa binaria realtime da un file `mainController.ini` TunerStudio.
- Include strumenti per aggiornare la configurazione LIVI partendo da TSV e file dashboard TunerStudio.

## Quale Modalita Usare

| Caso | Modalita consigliata |
| --- | --- |
| Voglio alimentare LIVI senza avviare TSDash o TunerStudio | Console Linux con `--source serial` |
| Uso TSDash su Linux | Console Linux con `--source usbmon` |
| Uso TunerStudio completo e voglio una soluzione integrata | Plugin TunerStudio in modalita `direct` |
| Uso TunerStudio completo ma voglio lasciare la logica a Linux | Plugin TunerStudio in modalita `bridge` + console Linux `--source udp` |
| Voglio solo vedere la dashboard LIVI muoversi | Console Linux con `--source demo` |
| Sto debuggando mapping o valori strani | Console Linux con `--dry-run --print-raw` |

## Flussi Dati

Plugin TunerStudio in modalita direct:

```text
TunerStudio -> plugin Java -> LIVI
```

Plugin TunerStudio in modalita bridge:

```text
TunerStudio -> plugin Java -> UDP -> console Linux -> LIVI
```

TSDash o TunerStudio senza plugin, in lettura passiva:

```text
TSDash/TunerStudio <-> ECU seriale USB -> /dev/usbmon -> console Linux -> LIVI
```

Polling seriale attivo senza TunerStudio/TSDash:

```text
console Linux -> ECU seriale USB -> letture realtime -> LIVI
```

Demo:

```text
console Linux -> dati simulati -> LIVI
```

## Prerequisiti

Per la console Linux:

- Un sistema Linux.
- Python 3.10 o superiore.
- Accesso alla macchina su cui gira LIVI.
- Per la modalita usbmon: permessi `sudo`, perche `/dev/usbmon*` richiede privilegi elevati su molte distribuzioni.

Per il plugin TunerStudio:

- TunerStudio completo, non TSDash.
- Java disponibile nell'ambiente di TunerStudio.
- `TunerStudioPluginAPI.jar` se vuoi ricompilare il plugin.

Nota per utenti meno esperti: i comandi che iniziano con `$` o che sono dentro blocchi `bash` vanno eseguiti nel terminale. Non copiare il simbolo `$`.

## Installazione Console Linux

Entra nella cartella della console:

```bash
cd linux-python-bridge
```

Crea un ambiente Python isolato. Questo evita di installare librerie nel sistema:

```bash
python3 -m venv .venv
```

Attiva l'ambiente:

```bash
. .venv/bin/activate
```

Quando l'ambiente e attivo, di solito il prompt mostra `(.venv)` all'inizio.

Installa il programma:

```bash
pip install -e .
```

Verifica che il comando sia disponibile:

```bash
tunerstudio-livi-bridge --help
```

Se il comando non viene trovato, controlla di avere attivato `.venv`.

## Modalita Demo

La demo e il primo test consigliato. Non usa ECU, seriale, TunerStudio o TSDash.

Sostituisci `livi.local` con l'host o indirizzo IP della macchina su cui LIVI ascolta:

```bash
tunerstudio-livi-bridge \
  --source demo \
  --livi-url ws://livi.local:4000 \
  --hz 20
```

Per vedere cosa verrebbe inviato senza collegarsi a LIVI:

```bash
tunerstudio-livi-bridge \
  --source demo \
  --dry-run \
  --demo-duration 5 \
  --hz 5
```

In dry-run vedrai righe JSON nel terminale. Questo e utile per capire se i campi sono corretti prima di aprire LIVI.

## Modalita TSDash / usbmon

Questa e la modalita principale per TSDash.

TSDash non carica plugin TunerStudio, quindi la console Linux osserva la comunicazione USB seriale gia in corso. Non apre la porta seriale e non scrive verso la ECU: legge solo `/dev/usbmon`.

### 1. Carica usbmon

Su molte distribuzioni serve:

```bash
sudo modprobe usbmon
```

Controlla che i device esistano:

```bash
ls /dev/usbmon*
```

Dovresti vedere file come `/dev/usbmon0`, `/dev/usbmon1`, ecc.

### 2. Trova la porta seriale

La porta e di solito qualcosa come:

```text
/dev/ttyUSB0
/dev/ttyACM0
```

Usa la stessa porta che TSDash o TunerStudio usa per comunicare con la centralina.

### 3. Avvia con un file INI TunerStudio

Il modo piu comodo e passare il file `mainController.ini` del progetto TunerStudio. La console usa quel file per sapere dove sono i campi nel flusso seriale.

Esempio:

```bash
sudo tunerstudio-livi-bridge \
  --source usbmon \
  --serial-port /dev/ttyUSB0 \
  --tunerstudio-ini ~/TunerStudioProjects/ExampleProject/projectCfg/mainController.ini \
  --livi-url ws://livi.local:4000
```

Se non sai dov'e il file INI, cerca nella cartella del progetto TunerStudio, di solito sotto:

```text
TunerStudioProjects/NomeProgetto/projectCfg/mainController.ini
```

### 4. Prova prima in dry-run

Prima di inviare a LIVI, puoi stampare i payload:

```bash
sudo tunerstudio-livi-bridge \
  --source usbmon \
  --serial-port /dev/ttyUSB0 \
  --tunerstudio-ini ~/TunerStudioProjects/ExampleProject/projectCfg/mainController.ini \
  --dry-run \
  --print-raw
```

Se i valori sono plausibili in dry-run, togli `--dry-run --print-raw` e aggiungi `--livi-url`.

### 5. Esporta la configurazione generata

Se vuoi controllare o modificare la mappa generata dall'INI:

```bash
tunerstudio-livi-bridge \
  --source usbmon \
  --tunerstudio-ini ~/TunerStudioProjects/ExampleProject/projectCfg/mainController.ini \
  --dump-generated-usbmon-config generated-usbmon-map.json \
  --dry-run
```

Il file `generated-usbmon-map.json` puo poi essere passato con:

```bash
sudo tunerstudio-livi-bridge \
  --source usbmon \
  --serial-port /dev/ttyUSB0 \
  --usbmon-config generated-usbmon-map.json \
  --livi-url ws://livi.local:4000
```

## Modalita Seriale Attiva

Usa la modalita seriale attiva quando la console Linux deve parlare direttamente con la ECU e alimentare LIVI da sola. Apre la porta seriale, invia comandi realtime `r` in stile TunerStudio, decodifica il blocco output-channel e genera payload LIVI.

Importante: non usare questa modalita mentre TunerStudio o TSDash sono collegati alla stessa seriale. Se un altro programma sta gia parlando con la ECU, usa `--source usbmon`.

Lo scambio seriale usa la stessa forma incorniciata osservata nel traffico TunerStudio:

```text
lunghezza payload a 2 byte + payload comando + CRC32 a 4 byte
```

Con i default, il bridge invia comandi simili a questo:

```text
serial out 000772003000007900b9476445
```

Gli ultimi quattro byte sono il CRC32. Firmware recenti possono rifiutare comandi con CRC a zero con una risposta corta come `000182d1b40d81`, dove `0x82` e lo status di errore della ECU.

Esempio usando un INI TunerStudio:

```bash
tunerstudio-livi-bridge \
  --source serial \
  --serial-port /dev/ttyUSB0 \
  --tunerstudio-ini ~/TunerStudioProjects/ExampleProject/projectCfg/mainController.ini \
  --livi-url ws://livi.local:4000
```

Parti da dry-run se non sei sicuro:

```bash
tunerstudio-livi-bridge \
  --source serial \
  --serial-port /dev/ttyUSB0 \
  --tunerstudio-ini ~/TunerStudioProjects/ExampleProject/projectCfg/mainController.ini \
  --dry-run \
  --print-raw
```

In un dry-run corretto dovresti vedere blocchi `serial in` lunghi seguiti da payload JSON:

```text
serial out 000772003000007900b9476445
serial in  007a00...
{"event":"telemetry:push","payload":{"rpm":0.0,"mapKpa":10.0,...}}
```

Se vedi `drop serial poll: ECU returned serial status 0x82`, il bridge sta raggiungendo la seriale ma la ECU rifiuta la richiesta. Controlla `--serial-page`, `--serial-read-size`, `--serial-can-id`, e lascia `--serial-command-crc crc32` salvo test con firmware che sai accettare CRC a zero.

Opzioni utili:

```text
--serial-baud 115200
--serial-timeout 0.5
--serial-read-size 121
--serial-can-id 0
--serial-page 0x30
--serial-command-crc crc32
--serial-poll-interval 0.05
```

I default seguono la forma dei pacchetti osservata nel dump usbmon di riferimento. Se il firmware ECU usa pagina realtime o dimensione blocco diverse, modifica `--serial-page` e `--serial-read-size`. `--serial-command-crc zero` serve solo per test con firmware vecchi o permissivi.

## Plugin TunerStudio

Il plugin e utile se usi TunerStudio completo su un computer dove puoi installare plugin Java.

Importante: questa parte e meno collaudata della console Linux. Usala quando ti serve integrazione diretta dentro TunerStudio; per TSDash usa la console Linux.

### Installare il jar gia compilato

Il jar compilato si trova qui:

```text
tunerstudio-plugin/build/tunerstudio-livi-telemetry-plugin.jar
```

Copia il jar nella cartella plugin/lib usata dalla tua installazione TunerStudio, seguendo lo stesso metodo usato per installare plugin di esempio.

Il manifest del jar contiene:

```text
ApplicationPlugin: io.fio.livi.tunerstudio.LiviTelemetryPlugin
```

### Configurare il plugin

Il file di configurazione si chiama:

```text
livi-telemetry.properties
```

Il plugin lo cerca in questo ordine:

1. percorso esplicito passato alla JVM con `-Dlivi.telemetry.config=...`
2. stessa directory del jar plugin
3. directory di lavoro di TunerStudio
4. `~/.livi/tunerstudio-livi.properties`

Per una installazione semplice, metti `livi-telemetry.properties` accanto al jar.

### Plugin in modalita direct

In direct mode il plugin invia direttamente a LIVI via Socket.IO/WebSocket:

```properties
livi.telemetry.mode=direct
livi.telemetry.remote.host=livi.local
livi.telemetry.remote.port=4000
livi.telemetry.event=telemetry:push
livi.telemetry.hz=20
livi.telemetry.channels=*
```

Se preferisci indicare una URL completa:

```properties
livi.telemetry.livi.url=ws://livi.local:4000
```

### Plugin in modalita bridge

In bridge mode il plugin manda dati grezzi via UDP alla console Linux. La console fa mapping e invio a LIVI.

Configurazione plugin:

```properties
livi.telemetry.mode=bridge
livi.telemetry.udp.host=127.0.0.1
livi.telemetry.udp.port=8765
livi.telemetry.channels=*
```

Avvio console:

```bash
tunerstudio-livi-bridge \
  --source udp \
  --listen-host 127.0.0.1 \
  --listen-port 8765 \
  --livi-url ws://livi.local:4000
```

Se il plugin gira su un computer e la console Linux su un altro, cambia `udp.host` con l'host della macchina Linux e assicurati che firewall e rete permettano UDP sulla porta scelta.

### Ricompilare il plugin

Serve il vero `TunerStudioPluginAPI.jar`, non il jar javadoc.

```bash
cd tunerstudio-plugin
chmod +x build.sh
./build.sh /path/to/TunerStudioPluginAPI.jar
```

Il risultato sara:

```text
tunerstudio-plugin/build/tunerstudio-livi-telemetry-plugin.jar
```

## Mapping Dei Campi

LIVI si aspetta nomi campo specifici, per esempio:

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

Il progetto include una mappa TSV:

```text
livi-tunerstudio-field-map.tsv
```

La TSV ha due colonne importanti:

```text
livi_field
tunerstudio_field
```

Esempio:

```text
rpm        rpm
speedKph   vss
fuelPct    benzina
```

I campi senza corrispondenza possono rimanere vuoti.

## Custom.ini, Tabelle .inc E Conversioni

Alcuni progetti TunerStudio non inviano direttamente il valore finale mostrato sulla dashboard. A volte il valore seriale viene trasformato da formule in `custom.ini` o da tabelle `.inc`.

Esempio concettuale:

```ini
benzina = { table(auxin_gauge0, "benzina.inc") }, "L"
```

In questo caso sulla seriale arriva `auxin_gauge0`, ma la dashboard mostra `benzina` dopo una tabella di conversione.

Lo script:

```bash
python tools/update_livi_json_from_tsv.py --help
```

puo usare TSV, `custom.ini` e file `.inc` per aggiornare il JSON LIVI con la logica corretta.

## Strumenti Utili

Estrarre coppie `OutputChannel` e titolo da dashboard TunerStudio:

```bash
python tools/extract_dash_gauge_channels.py dashboard.dsh > dash-gauge-outputchannel-title.tsv
```

Aggiornare un JSON LIVI partendo dalla TSV:

```bash
python tools/update_livi_json_from_tsv.py \
  --input existing-livi.json \
  --tsv livi-tunerstudio-field-map.tsv \
  --output updated-livi.json
```

Rivedi sempre l'output prima di usarlo in macchina.

## Test Rapidi

### Test della console senza LIVI

```bash
tunerstudio-livi-bridge --source demo --dry-run --demo-duration 3
```

Se vedi JSON nel terminale, la console funziona.

### Test UDP senza TunerStudio

Terminale 1:

```bash
tunerstudio-livi-bridge --source udp --dry-run
```

Terminale 2:

```bash
python tools/send_sample_udp.py
```

Dovresti vedere un payload simile:

```json
{"event":"telemetry:push","payload":{"rpm":2100.0,"speedKph":72.0,"ts":1234567890}}
```

## Troubleshooting

### Non arriva nulla a LIVI

- Controlla che l'URL inizi con `ws://` o `wss://`.
- Controlla host e porta di LIVI.
- Prova prima `--source demo --dry-run`.
- Se usi il plugin direct, apri il pannello plugin in TunerStudio e guarda lo stato.
- Se usi UDP tra due macchine, controlla firewall e rete.
- Se usi la modalita seriale attiva, verifica che nessun altro programma stia usando la stessa porta seriale.

### usbmon non si apre

Prova:

```bash
sudo modprobe usbmon
ls /dev/usbmon*
```

Poi riesegui il bridge con `sudo`.

### I valori sono instabili o non plausibili

- Usa `--tunerstudio-ini` invece di una mappa JSON scritta a mano.
- Verifica che la porta seriale sia quella della ECU, non di un altro dispositivo USB.
- Prova `--dry-run --print-raw` per vedere i payload prima dell'invio.
- Controlla eventuali formule in `custom.ini` e tabelle `.inc`.

### TSDash non vede il plugin

E normale: TSDash non supporta i plugin TunerStudio. Usa la console Linux con `--source usbmon`.
