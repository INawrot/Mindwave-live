# MindWave Live

A simple Python program for Debian that reads data from a NeuroSky MindWave USB dongle (ThinkGear protocol), plots it live, and logs it to a CSV file.

## Features

- reads packets from the dongle (built-in parser, or optionally the NeuroPy library),
- live plots:
  - eSense: attention / meditation,
  - EEG bands (delta, theta, lowAlpha, highAlpha, lowBeta, highBeta, lowGamma, midGamma) on a log scale,
  - poorSignal and blinkStrength,
  - raw EEG signal (last ~2 s),
- writes samples to CSV at a configurable interval,
- automatically retries auto-connect if no packets arrive for 5 s.

## Requirements

- Debian (or a derivative) with Python 3
- MindWave dongle plugged in via USB (shows up as `/dev/ttyUSB*` or `/dev/ttyACM*`)
- packages: `pyserial`, `matplotlib`, `tkinter`

## Installation

The simplest way is via apt (avoids PEP 668 issues):

```bash
sudo apt update
sudo apt install python3 python3-serial python3-matplotlib python3-tk
```

Alternatively, in a virtualenv:

```bash
sudo apt install python3-venv python3-tk
python3 -m venv .venv
source .venv/bin/activate
pip install pyserial matplotlib
```

### Serial port access

Your user must be in the `dialout` group:

```bash
sudo usermod -aG dialout $USER
```

Then log out and back in (or reboot).

## Usage

Turn on the headset, plug in the dongle, then run:

```bash
python3 mindwave_livev2.py
```

The port is detected automatically. To quit, close the plot window (or press Ctrl+C in the terminal).

## Options

| Option | Description | Default |
|---|---|---|
| `--port` | dongle port, e.g. `/dev/ttyUSB0` | auto-detect |
| `--baud` | baud rate | `115200` |
| `--backend` | `serial` (built-in parser) or `neuropy` | `serial` |
| `--no-autoconnect` | don't send the auto-connect command (0xC2) to the dongle | off |
| `--window` | plot window width in seconds | `60` |
| `--interval` | sampling/logging interval in seconds | `1.0` |
| `--output` | CSV file name | `mindwave_YYYYmmdd_HHMMSS.csv` |

Examples:

```bash
python3 mindwave_livev2.py --port /dev/ttyUSB0
python3 mindwave_livev2.py --window 120 --interval 0.5 --output session1.csv
```

## CSV format

Columns:

```
timestamp, t_sec, poorSignal, attention, meditation, blinkStrength,
delta, theta, lowAlpha, highAlpha, lowBeta, highBeta, lowGamma, midGamma
```

- `timestamp` – ISO time with millisecond precision,
- `t_sec` – seconds since the program started,
- the rest – the latest values received from the dongle.

The file is flushed on every sample, so data is preserved even if the program is closed abruptly.

## Interpreting `poorSignal`

- `0` – good signal,
- `1–199` – weak signal (noise),
- `200` – no contact with the forehead.

Attention/meditation values are only reliable when `poorSignal = 0`.

## Troubleshooting

- **"Nie znaleziono dongla USB" (dongle not found)** – check `dmesg | tail` after plugging it in, and if needed pass the port with `--port`.
- **`Permission denied` on the port** – add your user to the `dialout` group (see above) and log in again.
- **"BRAK DANYCH z dongla" (no data) in the plot title** – make sure the headset is on and charged, and that `--baud` matches (usually `115200` for the MindWave dongle).
- **No plot window** – install `python3-tk`; on a headless server you need a working display (X11/Wayland).
- **`neuropy` backend** – requires the NeuroPy library (`pip install NeuroPy`); the default `serial` backend doesn't need it.

> Note: the program's runtime messages (status, errors, plot titles) are in Polish.
