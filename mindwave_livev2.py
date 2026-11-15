import argparse
import csv
import inspect
import sys
import threading
import time
from collections import deque
from datetime import datetime

import matplotlib.pyplot as plt
import serial
import serial.tools.list_ports
from matplotlib.animation import FuncAnimation

BANDS = ["delta", "theta", "lowAlpha", "highAlpha",
         "lowBeta", "highBeta", "lowGamma", "midGamma"]
FIELDS = ["poorSignal", "attention", "meditation", "blinkStrength"] + BANDS
CSV_HEADER = ["timestamp", "t_sec"] + FIELDS

RAW_BUFFER = 1024 

DONGLE_STATUS = {
    0xD0: "headset połączony",
    0xD1: "dongle nie znajduje headsetu",
    0xD2: "headset rozłączony",
    0xD3: "dongle odrzucił polecenie",
    0xD4: "dongle w trybie oczekiwania (standby)",
}

class ThinkGearReader:
    def __init__(self, port, baud=115200, autoconnect=True):
        self.port = port
        self.baud = baud
        self.autoconnect = autoconnect
        self.rawValue = 0
        for f in FIELDS:
            setattr(self, f, 0)
        self.packets = 0
        self.dongle_status = None
        self._callbacks = {}
        self._ser = None
        self._thread = None
        self._running = False
        self._last_packet = time.time()

    def setCallBack(self, name, fn):
        self._callbacks[name] = fn

    def start(self):
        self._ser = serial.Serial(self.port, self.baud, timeout=0.2)
        if self.autoconnect:
            self._ser.write(bytes([0xC2]))  # auto-connect
        self._running = True
        self._last_packet = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
        if self._ser:
            self._ser.close()

    # --- wątek odczytu ---
    def _loop(self):
        buf = bytearray()
        last_ac = time.time()
        while self._running:
            try:
                data = self._ser.read(512)
            except (serial.SerialException, OSError):
                break
            if data:
                buf += data
                self._extract(buf)
            # brak pakietów > 5 s -> ponów auto-connect
            now = time.time()
            if (self.autoconnect and now - self._last_packet > 5
                    and now - last_ac > 5):
                try:
                    self._ser.write(bytes([0xC2]))
                except (serial.SerialException, OSError):
                    break
                last_ac = now

    def _extract(self, buf):
        while True:
            i = buf.find(b"\xaa\xaa")
            if i < 0:
                del buf[:-1]  
                return
            if i > 0:
                del buf[:i]
            if len(buf) < 4:
                return
            plen = buf[2]
            if plen == 0xAA: 
                del buf[0]
                continue
            if plen > 169:
                del buf[:2]
                continue
            if len(buf) < 4 + plen:
                return
            payload = bytes(buf[3:3 + plen])
            checksum = buf[3 + plen]
            if ((~sum(payload)) & 0xFF) == checksum:
                self._parse_payload(payload)
                self.packets += 1
                self._last_packet = time.time()
                del buf[:4 + plen]
            else:
                del buf[:2] 

    def _parse_payload(self, p):
        i = 0
        while i < len(p):
            while i < len(p) and p[i] == 0x55:
                i += 1
            if i >= len(p):
                break
            code = p[i]
            i += 1
            if code >= 0x80:
                if i >= len(p):
                    break
                vlen = p[i]
                i += 1
            else:
                vlen = 1
            val = p[i:i + vlen]
            i += vlen
            if len(val) < vlen:
                break
            self._handle(code, val)

    def _handle(self, code, val):
        if code == 0x02:
            self.poorSignal = val[0]
        elif code == 0x04:
            self.attention = val[0]
        elif code == 0x05:
            self.meditation = val[0]
        elif code == 0x16:
            self.blinkStrength = val[0]
        elif code == 0x80 and len(val) == 2:
            v = (val[0] << 8) | val[1]
            if v >= 32768:
                v -= 65536
            self.rawValue = v
            cb = self._callbacks.get("rawValue")
            if cb:
                cb(v)
        elif code == 0x83 and len(val) == 24:
            for k, name in enumerate(BANDS):
                setattr(self, name, int.from_bytes(val[3 * k:3 * k + 3], "big"))
        elif code in DONGLE_STATUS:
            self.dongle_status = DONGLE_STATUS[code]


def load_neuropy():
    import _thread
    sys.modules["thread"] = _thread
    import NeuroPy as mod
    cls = mod
    for _ in range(2):
        if inspect.isclass(cls):
            break
        cls = getattr(cls, "NeuroPy")
    return cls


def find_dongle():
    ports = [p for p in serial.tools.list_ports.comports()
             if p.device.startswith(("/dev/ttyUSB", "/dev/ttyACM"))]
    if not ports:
        return None
    if len(ports) > 1:
        print("Znaleziono kilka portów USB:")
        for p in ports:
            print(f"  {p.device}  ({p.description})")
        print(f"Używam {ports[0].device}. Inny port wskaż przez --port.")
    return ports[0].device


def parse_args():
    p = argparse.ArgumentParser(description="MindWave live monitor (dongle USB)")
    p.add_argument("--port", default=None,
                   help="port dongla USB, np. /dev/ttyUSB0 (domyślnie: autodetekcja)")
    p.add_argument("--baud", type=int, default=115200, help="baudrate (domyślnie 115200)")
    p.add_argument("--backend", choices=["serial", "neuropy"], default="serial",
                   help="serial = własny parser (domyślnie), neuropy = biblioteka NeuroPy")
    p.add_argument("--no-autoconnect", action="store_true",
                   help="nie wysyłaj do dongla polecenia auto-connect (0xC2)")
    p.add_argument("--window", type=int, default=60, help="szerokość okna wykresu w sekundach")
    p.add_argument("--interval", type=float, default=1.0, help="co ile sekund próbkować/zapisywać")
    p.add_argument("--output", default=None, help="plik CSV (domyślnie mindwave_YYYYmmdd_HHMMSS.csv)")
    return p.parse_args()


def main():
    args = parse_args()
    out_name = args.output or datetime.now().strftime("mindwave_%Y%m%d_%H%M%S.csv")

    port = args.port or find_dongle()
    if port is None:
        print("Nie znaleziono dongla USB (/dev/ttyUSB* ani /dev/ttyACM*).\n"
              "Sprawdź podłączenie (`dmesg | tail`) lub podaj port przez --port.",
              file=sys.stderr)
        sys.exit(1)

    raw = deque([0] * RAW_BUFFER, maxlen=RAW_BUFFER)
    try:
        if args.backend == "neuropy":
            if not args.no_autoconnect:
                with serial.Serial(port, args.baud, timeout=1) as s:
                    s.write(bytes([0xC2]))
                    time.sleep(1.5)
            mw = load_neuropy()(port, args.baud)
        else:
            mw = ThinkGearReader(port, args.baud, autoconnect=not args.no_autoconnect)
        mw.setCallBack("rawValue", lambda v: raw.append(v))
        mw.start()
    except Exception as e:
        print(f"Nie można uruchomić odczytu z {port}: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Połączono z {port} ({args.backend}), zapis do {out_name}. "
          "Zamknij okno wykresu, aby zakończyć.")

    csv_file = open(out_name, "w", newline="")
    writer = csv.writer(csv_file)
    writer.writerow(CSV_HEADER)

    maxlen = max(10, int(args.window / args.interval))
    t_buf = deque(maxlen=maxlen)
    data = {f: deque(maxlen=maxlen) for f in FIELDS}
    t0 = time.time()

    plt.style.use("dark_background")
    fig, axes = plt.subplots(4, 1, figsize=(11, 9))
    fig.canvas.manager.set_window_title("MindWave – podgląd na żywo")
    ax_es, ax_bands, ax_q, ax_raw = axes
    lines = {}

    ax_es.set_title("eSense: Attention / Meditation")
    ax_es.set_ylim(0, 100)
    lines["attention"], = ax_es.plot([], [], label="attention", color="tab:orange")
    lines["meditation"], = ax_es.plot([], [], label="meditation", color="tab:cyan")
    ax_es.legend(loc="upper left", ncol=2)

    ax_bands.set_title("Pasma EEG (skala log)")
    ax_bands.set_yscale("log")
    for b in BANDS:
        lines[b], = ax_bands.plot([], [], label=b, linewidth=1.2)
    ax_bands.legend(loc="upper left", ncol=4, fontsize=8)

    ax_q.set_title("poorSignal (0 = dobry, 200 = brak kontaktu) i blinkStrength")
    ax_q.set_ylim(0, 255)
    lines["poorSignal"], = ax_q.plot([], [], label="poorSignal", color="tab:red")
    lines["blinkStrength"], = ax_q.plot([], [], label="blinkStrength", color="tab:green")
    ax_q.legend(loc="upper left", ncol=2)

    ax_raw.set_title("Raw EEG (ostatnie ~2 s)")
    ax_raw.set_xlim(0, RAW_BUFFER)
    ax_raw.set_ylim(-2048, 2048)
    raw_line, = ax_raw.plot(range(RAW_BUFFER), list(raw), color="tab:purple", linewidth=0.8)

    for ax in (ax_es, ax_bands, ax_q):
        ax.set_xlabel("czas [s]")
        ax.grid(alpha=0.25)
    ax_raw.grid(alpha=0.25)
    fig.tight_layout()

    def update(_frame):
        now = time.time()
        t = now - t0
        values = {f: getattr(mw, f, 0) or 0 for f in FIELDS}

        writer.writerow([datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
                         f"{t:.2f}"] + [values[f] for f in FIELDS])
        csv_file.flush()

        t_buf.append(t)
        for f in FIELDS:
            data[f].append(values[f])

        for f in FIELDS:
            ys = data[f]
            if f in BANDS:
                ys = [max(v, 1) for v in ys] 
            lines[f].set_data(list(t_buf), list(ys))

        xmin = max(0, t - args.window)
        xmax = max(args.window, t)
        for ax in (ax_es, ax_bands, ax_q):
            ax.set_xlim(xmin, xmax)
        ax_bands.relim()
        ax_bands.autoscale_view(scalex=False, scaley=True)
        raw_line.set_ydata(list(raw))

        ps = values["poorSignal"]
        packets = getattr(mw, "packets", None)
        if packets is not None:
            no_data = t > 5 and packets == 0
        else:
            no_data = t > 5 and not any(values[f] for f in FIELDS)

        if no_data:
            status = "BRAK DANYCH z dongla"
        elif getattr(mw, "dongle_status", None) and ps == 0 and not values["attention"]:
            status = mw.dongle_status
        elif ps >= 200:
            status = "BRAK KONTAKTU z czołem"
        else:
            status = "słaby sygnał" if ps > 0 else "sygnał OK"
        extra = f", pakiety: {packets}" if packets is not None else ""
        fig.suptitle(f"MindWave – {status} (poorSignal={ps}{extra})", fontsize=11)

    anim = FuncAnimation(fig, update, interval=int(args.interval * 1000),
                         cache_frame_data=False)

    try:
        plt.show()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            mw.stop()
        except Exception:
            pass
        csv_file.close()
        print(f"Zakończono. Dane zapisane w {out_name}")


if __name__ == "__main__":
    main()
