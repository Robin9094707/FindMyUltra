#!/usr/bin/env python3
"""
FindMy Ultra – Server
=====================

Eine einzige Python-Datei, die die Standortberichte deiner **eigenen** AirTags
und Wo-ist-Zubehörteile direkt bei Apple abholt (über FindMy.py), lückenlos in
SQLite speichert und per HTTP-API + Web-App bereitstellt. Seit 1.7 zusätzlich
Google-Find-Hub- und Samsung-SmartThings-Find-Tracker (eigene Konten). Die iOS-App
„FindMy Ultra“ koppelt sich an diesen Server.

Funktionen
----------
* Apple-Anmeldung über die API (App oder Web) inkl. 2FA (vertrauenswürdiges
  Gerät oder SMS). Die Sitzung bleibt gespeichert.
* Import der Schlüssel-Dateien (FindMy.py-/export-findmy-JSON oder
  entschlüsselte .plist).
* Effizienter Abruf: Schlüssel aller Geräte werden in gemeinsamen Anfragen
  gebündelt; Schnell-Abruf (letzte Stunden), Tages-Scan und 7-Tage-Voll-Scan,
  damit auch nachgereichte Batch-Berichte landen.
* Standortverlauf mit einstellbarer Aufbewahrung (Standard 7 Tage, pro Gerät
  überschreibbar).
* Alarme: Bewegung, Wache (Diebstahlschutz), Zonen betreten/verlassen,
  Offline, Batterie, Verloren-Modus – Benachrichtigung über Bark
  (inkl. kritischer Hinweise).
* Sicherheit: Anmeldedaten in data/credentials.json (löschen ⇒ beim Neustart
  neu generiert), Passwort ändern, optional TOTP-2FA und Passkeys (WebAuthn).
* Live-Ereignisse per Server-Sent Events, Export als GPX/CSV/JSON.

Start
-----
    python3 findmy_ultra.py                 # installiert Abhängigkeiten selbst (.venv)
    python3 findmy_ultra.py --demo          # Demo-Daten, ohne Apple
    python3 findmy_ultra.py --self-signed   # HTTPS mit selbstsigniertem Zertifikat
    python3 findmy_ultra.py --help

Nur für deine eigenen Geräte gedacht.
"""

from __future__ import annotations

# ════════════════════════════════════════════════════════════════════════════
#  ⚙️  HIER EINSTELLEN
# ════════════════════════════════════════════════════════════════════════════
PORT = 5070          # Port, auf dem der Server läuft (in der App: <IP>:<PORT>)
HOST = "0.0.0.0"     # "0.0.0.0" = im ganzen Netzwerk erreichbar, "127.0.0.1" = nur lokal
# (Kommandozeile --port/--host oder FMU_PORT/FMU_HOST überschreiben diese Werte)

# ────────────────────────────────────────────────────────────────────────────
#  Bootstrap: fehlende Abhängigkeiten automatisch in eine .venv installieren
# ────────────────────────────────────────────────────────────────────────────
import os
import subprocess
import sys
from pathlib import Path

# Seit Mitte Oktober 2026 verlangt Apple bei der Anmeldung eine macOS-Identität
# (FindMy.py Issue #278). Bis FindMy.py das offiziell veröffentlicht, nutzen wir
# die geprüften Kompatibilitäts-Stände aus PR #279 (FindMy.py) bzw. #6 (Anisette.py).
# Installiert wird ohne git direkt aus den GitHub-Archiven (feste Commits).
_GH = "https://github.com"
REQUIREMENTS_DEPS = [
    f"macOS-ADI-emulator @ {_GH}/sacca97/os-findmy-e/archive/374d83854f657a7fdca45f813387d99d491db0e2.zip"
    "#subdirectory=macOS-ADI-emulator",
    "aiohttp>=3.9.5,<4", "httpx>=0.28.1", "pyelftools>=0.33", "unicorn>=2.1.4,<3", "websockets>=13",
    "typing-extensions>=4.12.2,<5", "srp>=1.0.21,<2", "cryptography>=42", "beautifulsoup4>=4.12.3,<5",
    "bleak>=3.0.2,<3.1.0", "certifi",
]
REQUIREMENTS_PINNED = [  # ohne Abhängigkeiten (die stehen oben), sonst zieht Anisette git-Quellen nach
    f"Anisette @ {_GH}/sacca97/Anisette.py/archive/627c9c663062bd872182b653113759c9d66b7e13.zip",
    f"FindMy @ {_GH}/sacca97/FindMy.py/archive/f2d24c86c3357f93cc19dd605fa9dc34d6d1b1c6.zip",
]
REQUIREMENTS = REQUIREMENTS_DEPS + REQUIREMENTS_PINNED
_HERE = Path(__file__).resolve().parent


def _deps_state() -> str:
    """ok = alles da · old = Pakete da, aber ohne Apple-Kompatibilität · missing = fehlen."""
    try:
        import aiohttp  # noqa: F401
        import findmy  # noqa: F401
    except ImportError:
        return "missing"
    try:
        import anisette
        from findmy.reports.anisette import BaseAnisetteProvider
        if hasattr(anisette, "AsyncAnisetteProvider") and hasattr(BaseAnisetteProvider, "get_client_info"):
            return "ok"
    except Exception:  # noqa: BLE001
        pass
    return "old"


def _bootstrap() -> None:
    state = _deps_state()
    if state == "ok":
        return
    if os.environ.get("FMU_BOOTSTRAPPED") or "--no-bootstrap" in sys.argv:
        if state == "old":
            print("⚠️  FindMy.py ohne Apple-Kompatibilität (Okt. 2026) – Apple-Anmeldung wird scheitern.")
            print("   Installieren: pip install " + " ".join(f'"{r}"' for r in REQUIREMENTS_DEPS))
            print("                 pip install --no-deps --force-reinstall " + " ".join(f'"{r}"' for r in REQUIREMENTS_PINNED))
            return
        print("❌ Abhängigkeiten fehlen – siehe README (Abschnitt Server).")
        sys.exit(1)
    if sys.version_info < (3, 10):
        print("❌ Python 3.10 oder neuer nötig.")
        sys.exit(1)
    venv = _HERE / ".venv"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        print(f"→ Erstelle virtuelle Umgebung in {venv} …")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
    print("→ Installiere bzw. aktualisiere Abhängigkeiten (einmalig, ein paar Minuten) …")
    subprocess.check_call([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([str(py), "-m", "pip", "install", "-q", "--prefer-binary", *REQUIREMENTS_DEPS])
    subprocess.check_call([str(py), "-m", "pip", "install", "-q", "--no-deps", "--force-reinstall",
                           *REQUIREMENTS_PINNED])
    env = dict(os.environ, FMU_BOOTSTRAPPED="1")
    os.execve(str(py), [str(py), str(Path(__file__).resolve()), *sys.argv[1:]], env)


if __name__ == "__main__":
    _bootstrap()

# ────────────────────────────────────────────────────────────────────────────
import argparse
import asyncio
import base64
import contextlib
import copy
import csv
import datetime as dt
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import math
import plistlib
import random
import re
import secrets
import signal
import socket
import sqlite3
import ssl
import struct
import time
import zlib
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlparse

from aiohttp import ClientSession, ClientTimeout, web

APP_NAME = "FindMy Ultra"
VERSION = "1.7.3"
DATA_DIR = Path(os.environ.get("FMU_HOME", _HERE / "data"))
log = logging.getLogger("findmy-ultra")

KEY_INTERVAL = dt.timedelta(minutes=15)
MAX_KEYS_PER_CHUNK = 290      # Apple akzeptiert max. ~290 IDs je Liste
CHUNKS_PER_REQUEST = 8        # mehrere Geräte/Zeitfenster in einer Anfrage

PALETTE = ["#0A84FF", "#FF9F0A", "#30D158", "#FF375F", "#BF5AF2",
           "#64D2FF", "#FFD60A", "#FF6482", "#5E5CE6", "#66D4CF"]
BATTERY = {0: "full", 1: "medium", 2: "low", 3: "critical"}
LEVELS = ("passive", "active", "timeSensitive", "critical")


def now() -> float:
    return time.time()


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def fmt_dist(m: float) -> str:
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{m:.0f} m"


def fmt_time(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%d.%m. %H:%M")


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def deep_merge(base: dict, upd: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (upd or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def secure_write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(tmp, mode, **({} if isinstance(data, bytes) else {"encoding": "utf-8"})) as f:
        f.write(data)
    with contextlib.suppress(OSError):
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


# ════════════════════════════════════════════════════════════════════════════
#  Einstellungen
# ════════════════════════════════════════════════════════════════════════════

DEFAULT_SETTINGS: dict = {
    "poll_interval": 60,          # s  – Schnell-Abruf (letzte Stunden)
    "lost_poll_interval": 20,     # s  – Geräte im Verloren-Modus / mit Wache
    "quick_hours": 6,             # h  – Fenster des Schnell-Abrufs
    "day_sweep_minutes": 10,      # min – 24-h-Scan
    "full_sweep_minutes": 60,     # min – 7-Tage-Voll-Scan (fängt Batches)
    "retention_days": 7,          # Tage Standortverlauf (0 = unbegrenzt)
    "geocode": False,             # Adressen in Benachrichtigungen (OpenStreetMap)
    "anisette_server": "",        # leer = lokal
    "zones": [],                  # [{id,name,lat,lon,radius}]
    "bark": {
        "enabled": False,
        "server": "https://api.day.app",
        "device_keys": [],
        "sound": "",
        "critical_sound": "alarm",
        "critical_volume": 8,
        "group": "FindMy Ultra",
        "icon": "",
        "min_level": "passive",
    },
    "quiet_hours": {"enabled": False, "start": "23:00", "end": "07:00"},
    "online_devices": {           # Online-Ortung der Apple-Geräte (iCloud „Wo ist?“)
        "enabled": True,
        "interval": 120,          # s zwischen Abfragen
    },
    "networks": {                 # Ortungsnetze (in der App einzeln auswählbar)
        "apple": {"enabled": True},
        "google": {
            "enabled": True,
            "server_mode": "auto",    # auto = Server ortet nur, wenn die App länger nichts geliefert hat
                                      # always = Server ortet immer · off = nur die App
            "interval": 900,          # s zwischen Server-Ortungen (min. 300)
            "app_grace_min": 30,      # so lange gilt eine App-Lieferung als „frisch“
        },
        "samsung": {
            "enabled": True,
            "interval": 120,          # s zwischen Abrufen (min. 30)
            "history": False,         # optional: Standortverlauf von Samsung (bis 7 Tage) mit abrufen
        },
    },
    "stays": {                    # Aufenthalte / stationäre Orte
        "radius_m": 120,          # max. Abstand zum Mittelpunkt, um als „gleicher Ort“ zu zählen
        "min_minutes": 5,         # Mindestdauer eines Aufenthalts
        "min_points": 2,          # Mindestanzahl Berichte
        "max_outliers": 3,        # so viele Ausreißer in Folge werden toleriert …
        "outlier_minutes": 30,    # … solange sie zusammen nicht länger als X min dauern
        "max_gap_hours": 12,      # längere Funkstille am selben Ort trennt Aufenthalte
        "max_accuracy_m": 500,    # ungenauere Berichte zählen nur, wenn sie hineinpassen
        "merge_minutes": 45,      # Aufenthalte am selben Ort mit kurzer Lücke zusammenfassen
    },
}

DEFAULT_ALERTS: dict = {
    "new_report": {"enabled": False, "level": "passive", "min_interval_min": 30},
    "movement": {"enabled": False, "distance_m": 250, "window_min": 30, "level": "critical"},
    "guard": {"enabled": False, "lat": None, "lon": None, "radius_m": 120, "level": "critical",
              "armed_at": None},
    "zones": {"enabled": False, "level": "timeSensitive"},
    "offline": {"enabled": False, "hours": 12, "level": "active"},
    "battery": {"enabled": True, "level": "active"},
}

DEFAULT_APPLE_SETTINGS: dict = {
    "case": {                      # AirPods: Case-Erkennung (geschätzt aus Offline-Ortungen)
        "window_min": 20,          # Ohrhörer gilt als „draußen“, wenn er so frisch geortet wurde
        "alert_out": {"enabled": False, "level": "timeSensitive"},
        "alert_in": {"enabled": False, "level": "active"},
        "once": False,             # True: jede Richtung nur einmal, bis neu scharf geschaltet
        "sep_distance_m": 150,     # Teile gelten als getrennt ab dieser Entfernung (+ Ungenauigkeit)
        "sep_min_obs": 2,          # … bestätigt nach so vielen getrennten Ortungen in Folge
        "sep_lookback_h": 6,
        "alert_separated": {"enabled": False, "level": "timeSensitive"},
    },
}

DEFAULT_LOST: dict = {"enabled": False, "since": None, "message": "", "phone": "",
                      "level": "critical", "notify_every_report": True}


# ════════════════════════════════════════════════════════════════════════════
#  Datenbank
# ════════════════════════════════════════════════════════════════════════════

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS devices (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    model         TEXT,
    emoji         TEXT,
    color         TEXT,
    serial        TEXT,
    kind          TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    retention_days INTEGER,
    alerts        TEXT NOT NULL DEFAULT '{}',
    lost          TEXT NOT NULL DEFAULT '{}',
    state         TEXT NOT NULL DEFAULT '{}',
    sort          INTEGER NOT NULL DEFAULT 0,
    added_at      REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    TEXT NOT NULL,
    ts           REAL NOT NULL,
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    accuracy     INTEGER,
    confidence   INTEGER,
    status       INTEGER,
    battery      TEXT,
    received_at  REAL NOT NULL,
    batch_id     TEXT,
    batch_size   INTEGER,
    late         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(device_id, ts, lat, lon)
);
CREATE INDEX IF NOT EXISTS idx_reports_dev_ts ON reports(device_id, ts);
CREATE INDEX IF NOT EXISTS idx_reports_ts ON reports(ts);
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    device_id  TEXT,
    kind       TEXT NOT NULL,
    level      TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    lat        REAL,
    lon        REAL,
    delivered  INTEGER NOT NULL DEFAULT 0,
    error      TEXT
);
CREATE TABLE IF NOT EXISTS polls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  REAL NOT NULL,
    duration    REAL,
    mode        TEXT,
    devices     INTEGER,
    keys        INTEGER,
    requests    INTEGER,
    new_reports INTEGER,
    error       TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    created     REAL NOT NULL,
    last_used   REAL NOT NULL,
    label       TEXT,
    ip          TEXT,
    kind        TEXT
);
CREATE TABLE IF NOT EXISTS apple_devices (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL DEFAULT 'fmip',   -- fmip (von Apple) | manual
    mode          TEXT NOT NULL DEFAULT 'device', -- device | airpods
    name          TEXT NOT NULL,
    custom_name   TEXT,
    emoji         TEXT,
    model         TEXT,
    display_name  TEXT,
    device_class  TEXT,
    battery_level REAL,
    battery_status TEXT,
    device_status TEXT,
    online        TEXT,          -- JSON: letzter Online-Standort
    links         TEXT NOT NULL DEFAULT '{}',   -- JSON: {rolle: accessory-device-id}
    hidden        INTEGER NOT NULL DEFAULT 0,
    sort          INTEGER NOT NULL DEFAULT 0,
    updated_at    REAL,
    added_at      REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS online_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    apple_id     TEXT NOT NULL,
    ts           REAL NOT NULL,
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    accuracy     INTEGER,
    position_type TEXT,
    battery_level REAL,
    received_at  REAL NOT NULL,
    UNIQUE(apple_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_online_dev_ts ON online_reports(apple_id, ts);
CREATE TABLE IF NOT EXISTS recordings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    apple_id    TEXT NOT NULL,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'both',   -- both | offline | online
    start_ts    REAL NOT NULL,
    end_ts      REAL,                           -- geplantes Ende (optional)
    stopped_ts  REAL,                           -- tatsächlich beendet
    created     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    k  TEXT PRIMARY KEY,
    v  TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        # Migrationen (bestehende Daten bleiben erhalten)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(devices)")}
        if "category" not in cols:
            self.db.execute("ALTER TABLE devices ADD COLUMN category TEXT NOT NULL DEFAULT 'item'")
        if "network" not in cols:   # 1.7: apple | google | samsung
            self.db.execute("ALTER TABLE devices ADD COLUMN network TEXT NOT NULL DEFAULT 'apple'")
        if "ext_id" not in cols:    # 1.7: ID des Trackers im fremden Netz
            self.db.execute("ALTER TABLE devices ADD COLUMN ext_id TEXT")
        acols = {r[1] for r in self.db.execute("PRAGMA table_info(apple_devices)")}
        if "settings" not in acols:
            self.db.execute("ALTER TABLE apple_devices ADD COLUMN settings TEXT NOT NULL DEFAULT '{}'")
        if "state" not in acols:
            self.db.execute("ALTER TABLE apple_devices ADD COLUMN state TEXT NOT NULL DEFAULT '{}'")
        if "extra" not in acols:
            self.db.execute("ALTER TABLE apple_devices ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'")
        if "raw" not in acols:
            self.db.execute("ALTER TABLE apple_devices ADD COLUMN raw TEXT NOT NULL DEFAULT '{}'")
        self.db.commit()

    # kv / settings ----------------------------------------------------------
    def kv_get(self, k: str, default: Any = None) -> Any:
        r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def kv_set(self, k: str, v: Any) -> None:
        self.db.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                        (k, json.dumps(v)))
        self.db.commit()

    def settings(self) -> dict:
        return deep_merge(DEFAULT_SETTINGS, self.kv_get("settings", {}))

    def save_settings(self, s: dict) -> None:
        self.kv_set("settings", s)

    # devices ----------------------------------------------------------------
    def upsert_device(self, dev_id: str, name: str, model: str | None, emoji: str | None,
                      serial: str | None, kind: str) -> None:
        exists = self.db.execute("SELECT 1 FROM devices WHERE id=?", (dev_id,)).fetchone()
        if exists:
            self.db.execute("UPDATE devices SET model=COALESCE(?,model), serial=COALESCE(?,serial), "
                            "kind=? WHERE id=?", (model, serial, kind, dev_id))
        else:
            used = {r[0] for r in self.db.execute("SELECT color FROM devices")}
            h = int(hashlib.sha1(dev_id.encode()).hexdigest(), 16)
            color = PALETTE[h % len(PALETTE)]
            if color in used:
                color = next((c for c in PALETTE if c not in used), color)
            sort = (self.db.execute("SELECT COALESCE(MAX(sort),0)+1 FROM devices").fetchone()[0])
            self.db.execute(
                "INSERT INTO devices(id,name,model,emoji,color,serial,kind,enabled,alerts,lost,state,"
                "sort,added_at) VALUES(?,?,?,?,?,?,?,1,?,?,?,?,?)",
                (dev_id, name, model, emoji or "📍", color, serial, kind,
                 json.dumps(DEFAULT_ALERTS), json.dumps(DEFAULT_LOST), "{}", sort, now()))
        self.db.commit()

    def device_row(self, dev_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM devices WHERE id=?", (dev_id,)).fetchone()
        return self._dev(r) if r else None

    @staticmethod
    def _dev(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        d["alerts"] = deep_merge(DEFAULT_ALERTS, json.loads(d.get("alerts") or "{}"))
        d["lost"] = deep_merge(DEFAULT_LOST, json.loads(d.get("lost") or "{}"))
        d["state"] = json.loads(d.get("state") or "{}")
        return d

    def update_device(self, dev_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols, vals = [], []
        for k, v in fields.items():
            if k in ("alerts", "lost", "state"):
                v = json.dumps(v)
            if k == "enabled":
                v = int(bool(v))
            cols.append(f"{k}=?")
            vals.append(v)
        self.db.execute(f"UPDATE devices SET {', '.join(cols)} WHERE id=?", (*vals, dev_id))
        self.db.commit()

    def delete_device(self, dev_id: str, keep_reports: bool = False) -> None:
        self.db.execute("DELETE FROM devices WHERE id=?", (dev_id,))
        if not keep_reports:
            self.db.execute("DELETE FROM reports WHERE device_id=?", (dev_id,))
        self.db.commit()

    def devices(self, category: str | None = None) -> list[dict]:
        if category:
            rows = self.db.execute("SELECT * FROM devices WHERE category=? ORDER BY sort, name COLLATE NOCASE",
                                   (category,)).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM devices ORDER BY sort, name COLLATE NOCASE").fetchall()
        out = []
        for r in rows:
            d = self._dev(r)
            agg = self.db.execute("SELECT COUNT(*), MIN(ts) FROM reports WHERE device_id=?",
                                  (d["id"],)).fetchone()
            d["total"], d["first_ts"] = agg[0], agg[1]
            last = self.db.execute("SELECT * FROM reports WHERE device_id=? ORDER BY ts DESC LIMIT 1",
                                   (d["id"],)).fetchone()
            d["last"] = dict(last) if last else None
            bat = self.db.execute("SELECT battery FROM reports WHERE device_id=? AND battery IS NOT NULL "
                                  "ORDER BY ts DESC LIMIT 1", (d["id"],)).fetchone()
            d["battery"] = bat[0] if bat else None
            d.pop("state", None)
            out.append(d)
        return out

    def upsert_network_device(self, network: str, ext_id: str, name: str, model: str | None,
                              kind: str) -> tuple[str, bool]:
        """Tracker eines fremden Netzes anlegen bzw. aktualisieren (Name bleibt, falls umbenannt)."""
        did = network_device_id(network, ext_id)
        new = not self.device_row(did)
        if new:
            self.upsert_device(did, name, model, None, None, kind)
            self.db.execute("UPDATE devices SET network=?, ext_id=? WHERE id=?", (network, ext_id, did))
            if network != "apple":
                alerts = copy.deepcopy(DEFAULT_ALERTS)
                self.db.execute("UPDATE devices SET alerts=? WHERE id=?", (json.dumps(alerts), did))
            self.db.commit()
        elif model:
            self.db.execute("UPDATE devices SET model=? WHERE id=?", (model, did))
            self.db.commit()
        return did, new

    def network_devices(self, network: str) -> list[dict]:
        rows = self.db.execute("SELECT * FROM devices WHERE network=? ORDER BY sort", (network,)).fetchall()
        return [self._dev(r) for r in rows]

    def device_public(self, dev_id: str) -> dict | None:
        return next((d for d in self.devices() if d["id"] == dev_id), None)

    # Apple-Geräte -------------------------------------------------------------
    def apple_rows(self, include_hidden: bool = False) -> list[dict]:
        q = "SELECT * FROM apple_devices" + ("" if include_hidden else " WHERE hidden=0") + \
            " ORDER BY sort, COALESCE(custom_name, name) COLLATE NOCASE"
        out = []
        for r in self.db.execute(q).fetchall():
            d = dict(r)
            d["online"] = json.loads(d["online"]) if d.get("online") else None
            d["links"] = json.loads(d.get("links") or "{}")
            d["settings"] = deep_merge(DEFAULT_APPLE_SETTINGS, json.loads(d.get("settings") or "{}"))
            d["state"] = json.loads(d.get("state") or "{}")
            d["extra"] = json.loads(d.get("extra") or "{}")
            d.pop("raw", None)
            d["hidden"] = bool(d["hidden"])
            out.append(d)
        return out

    # Online-Verlauf & Aufzeichnungen ------------------------------------------------
    def add_online_report(self, aid: str, on: dict, battery: float | None) -> None:
        self.db.execute("INSERT OR IGNORE INTO online_reports(apple_id,ts,lat,lon,accuracy,position_type,"
                        "battery_level,received_at) VALUES(?,?,?,?,?,?,?,?)",
                        (aid, on["ts"], on["lat"], on["lon"], on.get("accuracy"), on.get("position_type"),
                         battery, now()))
        self.db.commit()

    @staticmethod
    def _recording(r: sqlite3.Row) -> dict:
        d = dict(r)
        t = now()
        d["active"] = d["stopped_ts"] is None and (d["end_ts"] is None or d["end_ts"] > t)
        d["effective_end"] = d["stopped_ts"] or (d["end_ts"] if d["end_ts"] and d["end_ts"] <= t else None)
        return d

    def recordings(self, aid: str | None = None) -> list[dict]:
        if aid:
            rows = self.db.execute("SELECT * FROM recordings WHERE apple_id=? ORDER BY start_ts DESC", (aid,))
        else:
            rows = self.db.execute("SELECT * FROM recordings ORDER BY start_ts DESC")
        return [self._recording(r) for r in rows.fetchall()]

    def recording(self, sid: int) -> dict | None:
        r = self.db.execute("SELECT * FROM recordings WHERE id=?", (sid,)).fetchone()
        return self._recording(r) if r else None

    def add_recording(self, aid: str, name: str, source: str, end_ts: float | None) -> int:
        cur = self.db.execute("INSERT INTO recordings(apple_id,name,source,start_ts,end_ts,created) "
                              "VALUES(?,?,?,?,?,?)", (aid, name, source, now(), end_ts, now()))
        self.db.commit()
        return cur.lastrowid

    def update_recording(self, sid: int, **f: Any) -> None:
        if f:
            self.db.execute(f"UPDATE recordings SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), sid))
            self.db.commit()

    def delete_recording(self, sid: int) -> None:
        self.db.execute("DELETE FROM recordings WHERE id=?", (sid,))
        self.db.commit()

    def apple_row(self, aid: str) -> dict | None:
        return next((d for d in self.apple_rows(True) if d["id"] == aid), None)

    def apple_upsert_fmip(self, dev: dict) -> None:
        aid = dev["id"]
        exists = self.db.execute("SELECT 1 FROM apple_devices WHERE id=?", (aid,)).fetchone()
        vals = (dev["name"], dev.get("model"), dev.get("display_name"), dev.get("device_class"),
                dev.get("battery_level"), dev.get("battery_status"), dev.get("device_status"),
                json.dumps(dev["online"]) if dev.get("online") else None, now())
        if exists:
            # Online-Standort nur überschreiben, wenn neu vorhanden (sonst letzten behalten)
            if dev.get("online"):
                self.db.execute("UPDATE apple_devices SET name=?, model=?, display_name=?, device_class=?, "
                                "battery_level=?, battery_status=?, device_status=?, online=?, updated_at=? "
                                "WHERE id=?", (*vals, aid))
            else:
                self.db.execute("UPDATE apple_devices SET name=?, model=?, display_name=?, device_class=?, "
                                "battery_level=?, battery_status=?, device_status=?, updated_at=? WHERE id=?",
                                (*vals[:7], vals[8], aid))
        else:
            mode = "airpods" if "airpod" in " ".join(str(dev.get(k) or "") for k in
                                                     ("device_class", "display_name", "model", "name")).lower() else "device"
            sort = self.db.execute("SELECT COALESCE(MAX(sort),0)+1 FROM apple_devices").fetchone()[0]
            self.db.execute("INSERT INTO apple_devices(id,kind,mode,name,model,display_name,device_class,"
                            "battery_level,battery_status,device_status,online,updated_at,links,sort,added_at) "
                            "VALUES(?,'fmip',?,?,?,?,?,?,?,?,?,?,'{}',?,?)", (aid, mode, *vals, sort, now()))
        self.db.commit()

    def apple_create(self, name: str, mode: str, device_class: str | None) -> str:
        aid = "m-" + secrets.token_hex(6)
        sort = self.db.execute("SELECT COALESCE(MAX(sort),0)+1 FROM apple_devices").fetchone()[0]
        self.db.execute("INSERT INTO apple_devices(id,kind,mode,name,device_class,links,sort,added_at) "
                        "VALUES(?,'manual',?,?,?,'{}',?,?)", (aid, mode, name, device_class, sort, now()))
        self.db.commit()
        return aid

    def apple_update(self, aid: str, **fields: Any) -> None:
        if not fields:
            return
        cols, vals = [], []
        for k, v in fields.items():
            if k in ("links", "online", "settings", "state", "extra", "raw") and not isinstance(v, str):
                v = json.dumps(v) if v is not None else None
            if k == "hidden":
                v = int(bool(v))
            cols.append(f"{k}=?")
            vals.append(v)
        self.db.execute(f"UPDATE apple_devices SET {', '.join(cols)} WHERE id=?", (*vals, aid))
        self.db.commit()

    def apple_delete(self, aid: str) -> None:
        self.db.execute("DELETE FROM apple_devices WHERE id=?", (aid,))
        self.db.commit()

    # reports ----------------------------------------------------------------
    def newest_ts(self, dev_id: str) -> float:
        r = self.db.execute("SELECT MAX(ts) FROM reports WHERE device_id=?", (dev_id,)).fetchone()
        return r[0] or 0.0

    def insert_reports(self, dev_id: str, items: list[dict]) -> list[dict]:
        if not items:
            return []
        prev_newest = self.newest_ts(dev_id)
        received = now()
        uniq = {(round(i["ts"], 3), i["lat"], i["lon"]): i for i in items}
        cand = [i for k, i in uniq.items() if not self.db.execute(
            "SELECT 1 FROM reports WHERE device_id=? AND ts=? AND lat=? AND lon=?",
            (dev_id, i["ts"], i["lat"], i["lon"])).fetchone()]
        if not cand:
            return []
        prefix = "init-" if prev_newest == 0.0 else ""
        batch_id = f"{prefix}{dev_id[:8]}-{int(received * 1000)}"
        new = []
        for it in sorted(cand, key=lambda x: x["ts"]):
            cur = self.db.execute(
                "INSERT OR IGNORE INTO reports(device_id,ts,lat,lon,accuracy,confidence,status,battery,"
                "received_at,batch_id,batch_size,late) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (dev_id, it["ts"], it["lat"], it["lon"], it.get("accuracy"), it.get("confidence"),
                 it.get("status"), it.get("battery"), received, batch_id, len(cand),
                 1 if it["ts"] < prev_newest else 0))
            if cur.rowcount:
                new.append(dict(self.db.execute("SELECT * FROM reports WHERE id=?",
                                                (cur.lastrowid,)).fetchone()))
        self.db.commit()
        return new

    def reports(self, since: float | None = None, until: float | None = None,
                device: str | None = None, limit: int = 200000) -> list[dict]:
        q, a = "SELECT * FROM reports WHERE 1=1", []
        if since is not None:
            q += " AND ts>=?"
            a.append(since)
        if until is not None:
            q += " AND ts<=?"
            a.append(until)
        if device:
            q += " AND device_id=?"
            a.append(device)
        q += " ORDER BY ts DESC LIMIT ?"
        a.append(limit)
        rows = [dict(r) for r in self.db.execute(q, a).fetchall()]
        rows.reverse()
        return rows

    def purge(self, settings: dict) -> int:
        removed = 0
        default = int(settings.get("retention_days") or 0)
        # Zeiträume von Aufzeichnungen bleiben unabhängig von der Aufbewahrung erhalten
        protect: dict[str, list[tuple[float, float]]] = {}
        for a in self.apple_rows(True):
            for se in self.recordings(a["id"]):
                rng = (se["start_ts"] - 3600, (se["effective_end"] or now()) + 3600)
                protect.setdefault(a["id"], []).append(rng)
                for did in a["links"].values():
                    protect.setdefault(did, []).append(rng)

        def guard(key: str) -> tuple[str, list]:
            sql, args = "", []
            for lo, hi in protect.get(key, []):
                sql += " AND NOT (ts BETWEEN ? AND ?)"
                args += [lo, hi]
            return sql, args

        for d in self.db.execute("SELECT id, retention_days FROM devices").fetchall():
            days = d["retention_days"] if d["retention_days"] is not None else default
            if days and days > 0:
                g, ga = guard(d["id"])
                cur = self.db.execute("DELETE FROM reports WHERE device_id=? AND ts<?" + g,
                                      (d["id"], now() - days * 86400, *ga))
                removed += cur.rowcount
        if default > 0:
            for a in self.db.execute("SELECT DISTINCT apple_id FROM online_reports").fetchall():
                g, ga = guard(a[0])
                self.db.execute("DELETE FROM online_reports WHERE apple_id=? AND ts<?" + g,
                                (a[0], now() - default * 86400, *ga))
        self.db.execute("DELETE FROM notifications WHERE ts<?", (now() - 60 * 86400,))
        self.db.execute("DELETE FROM polls WHERE id NOT IN (SELECT id FROM polls ORDER BY id DESC LIMIT 3000)")
        self.db.commit()
        return removed

    def log_poll(self, **kw: Any) -> None:
        self.db.execute("INSERT INTO polls(started_at,duration,mode,devices,keys,requests,new_reports,error) "
                        "VALUES(:started_at,:duration,:mode,:devices,:keys,:requests,:new_reports,:error)", kw)
        self.db.commit()

    def stats(self) -> dict:
        total = self.db.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        today0 = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        today = self.db.execute("SELECT COUNT(*) FROM reports WHERE received_at>=?", (today0,)).fetchone()[0]
        batches = self.db.execute("SELECT COUNT(DISTINCT batch_id) FROM reports WHERE batch_size>1 "
                                  "AND batch_id NOT LIKE 'init-%'").fetchone()[0]
        late = self.db.execute("SELECT COUNT(*) FROM reports WHERE late=1").fetchone()[0]
        polls = self.db.execute("SELECT COUNT(*), COALESCE(SUM(requests),0) FROM polls "
                                "WHERE started_at>=?", (today0,)).fetchone()
        return {"total": total, "today": today, "batches": batches, "late": late,
                "polls_today": polls[0], "requests_today": polls[1]}

    # notifications ------------------------------------------------------------
    def add_notification(self, **kw: Any) -> int:
        cur = self.db.execute(
            "INSERT INTO notifications(ts,device_id,kind,level,title,body,lat,lon,delivered,error) "
            "VALUES(:ts,:device_id,:kind,:level,:title,:body,:lat,:lon,:delivered,:error)", kw)
        self.db.commit()
        return cur.lastrowid

    def set_delivery(self, nid: int, delivered: bool, error: str | None) -> None:
        self.db.execute("UPDATE notifications SET delivered=?, error=? WHERE id=?",
                        (int(delivered), error, nid))
        self.db.commit()

    def notifications(self, limit: int = 200, device: str | None = None) -> list[dict]:
        if device:
            rows = self.db.execute("SELECT * FROM notifications WHERE device_id=? ORDER BY id DESC LIMIT ?",
                                   (device, limit))
        else:
            rows = self.db.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) | {"delivered": bool(r["delivered"])} for r in rows.fetchall()]

    # sessions ----------------------------------------------------------------
    def add_session(self, token: str, label: str, ip: str, kind: str) -> None:
        t = now()
        self.db.execute("INSERT INTO sessions(token_hash,created,last_used,label,ip,kind) VALUES(?,?,?,?,?,?)",
                        (hashlib.sha256(token.encode()).hexdigest(), t, t, label[:80], ip, kind))
        self.db.commit()

    def check_session(self, token: str) -> dict | None:
        h = hashlib.sha256(token.encode()).hexdigest()
        r = self.db.execute("SELECT * FROM sessions WHERE token_hash=?", (h,)).fetchone()
        if not r:
            return None
        if now() - r["last_used"] > 60:
            self.db.execute("UPDATE sessions SET last_used=? WHERE token_hash=?", (now(), h))
            self.db.commit()
        if r["kind"] == "link" and now() - r["created"] > 600:
            return None
        return dict(r)

    def sessions(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM sessions WHERE kind!='link' ORDER BY last_used DESC").fetchall()]

    def delete_session(self, token_hash: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
        self.db.commit()

    def delete_all_sessions(self, except_hash: str | None = None) -> None:
        self.db.execute("DELETE FROM sessions WHERE token_hash!=?", (except_hash or "",))
        self.db.commit()


# ════════════════════════════════════════════════════════════════════════════
#  Anmeldedaten (credentials.json), TOTP, Passkeys (WebAuthn)
# ════════════════════════════════════════════════════════════════════════════

def hash_password(pw: str, salt: bytes | None = None) -> dict:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return {"algo": "scrypt", "salt": salt.hex(), "hash": h.hex()}


def verify_password(pw: str, rec: dict) -> bool:
    try:
        h = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(rec["salt"]), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(h.hex(), rec["hash"])
    except Exception:  # noqa: BLE001
        return False


def totp_code(secret: str, t: float | None = None) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    counter = int((t if t is not None else now()) // 30)
    h = hmac.new(key, struct.pack(">Q", counter), "sha1").digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def totp_verify(secret: str, code: str) -> bool:
    code = re.sub(r"\D", "", code or "")
    return len(code) == 6 and any(hmac.compare_digest(totp_code(secret, now() + d * 30), code)
                                  for d in (-1, 0, 1))


class Credentials:
    """Liegt in data/credentials.json. Löschen ⇒ beim nächsten Start neu generiert."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict = {}
        self.generated_password: str | None = None

    def load_or_create(self) -> bool:
        if self.path.exists():
            self.data = json.loads(self.path.read_text("utf-8"))
            return False
        pw = "-".join(secrets.token_urlsafe(6).replace("-", "x").replace("_", "y") for _ in range(3))
        self.generated_password = pw
        self.data = {
            "username": "admin",
            "password": hash_password(pw),
            "password_is_generated": True,
            "user_handle": b64u(secrets.token_bytes(16)),
            "totp": {"enabled": False, "secret": None, "pending": None},
            "passkeys": [],
            "created": iso(now()),
        }
        self.save()
        secure_write(self.path.parent / "ERSTES-PASSWORT.txt",
                     f"{APP_NAME}\nBenutzer: admin\nPasswort: {pw}\n\n"
                     "Diese Datei wird gelöscht, sobald du das Passwort änderst.\n")
        return True

    def save(self) -> None:
        secure_write(self.path, json.dumps(self.data, indent=2))

    @property
    def username(self) -> str:
        return self.data["username"]

    def check(self, username: str, password: str) -> bool:
        ok_user = hmac.compare_digest(username.strip().lower(), self.username.lower())
        return verify_password(password, self.data["password"]) and ok_user

    def set_password(self, pw: str, username: str | None = None) -> None:
        self.data["password"] = hash_password(pw)
        self.data["password_is_generated"] = False
        if username:
            self.data["username"] = username.strip()
        self.save()
        with contextlib.suppress(FileNotFoundError):
            (self.path.parent / "ERSTES-PASSWORT.txt").unlink()

    @property
    def totp_enabled(self) -> bool:
        return bool(self.data.get("totp", {}).get("enabled"))


# --- minimaler CBOR-Decoder (für WebAuthn) -----------------------------------

def cbor_decode(data: bytes, pos: int = 0) -> tuple[Any, int]:
    ib = data[pos]
    mt, ai = ib >> 5, ib & 31
    pos += 1
    if ai < 24:
        val = ai
    elif ai in (24, 25, 26, 27):
        n = {24: 1, 25: 2, 26: 4, 27: 8}[ai]
        raw = data[pos:pos + n]
        pos += n
        if mt == 7:
            if n == 2:
                return struct.unpack(">e", raw)[0], pos
            if n == 4:
                return struct.unpack(">f", raw)[0], pos
            if n == 8:
                return struct.unpack(">d", raw)[0], pos
        val = int.from_bytes(raw, "big")
    else:
        raise ValueError("CBOR: unbestimmte Länge nicht unterstützt")
    if mt == 0:
        return val, pos
    if mt == 1:
        return -1 - val, pos
    if mt == 2:
        return data[pos:pos + val], pos + val
    if mt == 3:
        return data[pos:pos + val].decode("utf-8"), pos + val
    if mt == 4:
        arr = []
        for _ in range(val):
            item, pos = cbor_decode(data, pos)
            arr.append(item)
        return arr, pos
    if mt == 5:
        m = {}
        for _ in range(val):
            k, pos = cbor_decode(data, pos)
            v, pos = cbor_decode(data, pos)
            m[k] = v
        return m, pos
    if mt == 6:
        return cbor_decode(data, pos)
    if mt == 7:
        return {20: False, 21: True, 22: None, 23: None}.get(val, val), pos
    raise ValueError("CBOR: unbekannter Typ")


def cose_verify(cose_bytes: bytes, signature: bytes, data: bytes) -> None:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

    cose, _ = cbor_decode(cose_bytes)
    kty, alg = cose.get(1), cose.get(3)
    if kty == 2:  # EC2 / ES256
        curve = {1: ec.SECP256R1(), 2: ec.SECP384R1(), 3: ec.SECP521R1()}[cose.get(-1, 1)]
        hsh = {1: hashes.SHA256(), 2: hashes.SHA384(), 3: hashes.SHA512()}[cose.get(-1, 1)]
        pub = ec.EllipticCurvePublicNumbers(int.from_bytes(cose[-2], "big"),
                                            int.from_bytes(cose[-3], "big"), curve).public_key()
        pub.verify(signature, data, ec.ECDSA(hsh))
    elif kty == 3:  # RSA / RS256
        pub = rsa.RSAPublicNumbers(int.from_bytes(cose[-2], "big"),
                                   int.from_bytes(cose[-1], "big")).public_key()
        pub.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
    elif kty == 1:  # OKP / Ed25519
        ed25519.Ed25519PublicKey.from_public_bytes(cose[-2]).verify(signature, data)
    else:
        raise ValueError(f"Schlüsseltyp {kty}/{alg} nicht unterstützt")


class WebAuthn:
    def __init__(self, creds: Credentials) -> None:
        self.creds = creds
        self.challenges: dict[str, tuple[float, str]] = {}

    def new_challenge(self, purpose: str) -> str:
        t = now()
        self.challenges = {k: v for k, v in self.challenges.items() if v[0] > t}
        c = b64u(secrets.token_bytes(32))
        self.challenges[c] = (t + 300, purpose)
        return c

    def take_challenge(self, c: str, purpose: str) -> None:
        v = self.challenges.pop(c, None)
        if not v or v[0] < now() or v[1] != purpose:
            raise ValueError("Challenge ungültig oder abgelaufen")

    @staticmethod
    def _check_client(client_json: bytes, typ: str, rp_id: str) -> dict:
        cd = json.loads(client_json)
        if cd.get("type") != typ:
            raise ValueError("Falscher Typ")
        origin = urlparse(cd.get("origin", ""))
        host = (origin.hostname or "").lower()
        if host != rp_id and not host.endswith("." + rp_id):
            raise ValueError(f"Origin {cd.get('origin')} passt nicht zu {rp_id}")
        if origin.scheme != "https" and host not in ("localhost", "127.0.0.1"):
            raise ValueError("Passkeys benötigen HTTPS")
        return cd

    def register_options(self, rp_id: str) -> dict:
        return {
            "challenge": self.new_challenge("register"),
            "rp": {"id": rp_id, "name": APP_NAME},
            "user": {"id": self.creds.data["user_handle"], "name": self.creds.username,
                     "displayName": f"{APP_NAME} ({self.creds.username})"},
            "pubKeyCredParams": [{"type": "public-key", "alg": a} for a in (-7, -8, -257)],
            "authenticatorSelection": {"residentKey": "required", "userVerification": "preferred"},
            "attestation": "none",
            "timeout": 120000,
            "excludeCredentials": [{"type": "public-key", "id": p["id"]}
                                   for p in self.creds.data.get("passkeys", [])],
        }

    def register_verify(self, body: dict, rp_id: str) -> dict:
        client_json = b64u_dec(body["clientDataJSON"])
        cd = self._check_client(client_json, "webauthn.create", rp_id)
        self.take_challenge(cd["challenge"], "register")
        att, _ = cbor_decode(b64u_dec(body["attestationObject"]))
        auth = att["authData"]
        if auth[:32] != hashlib.sha256(rp_id.encode()).digest():
            raise ValueError("rpIdHash stimmt nicht")
        flags = auth[32]
        if not flags & 0x01:
            raise ValueError("Benutzer nicht anwesend")
        if not flags & 0x40:
            raise ValueError("Keine Schlüsseldaten")
        sign_count = int.from_bytes(auth[33:37], "big")
        cred_len = int.from_bytes(auth[53:55], "big")
        cred_id = auth[55:55 + cred_len]
        _, end = cbor_decode(auth, 55 + cred_len)
        cose = auth[55 + cred_len:end]
        cbor_decode(cose)  # validieren
        pk = {"id": b64u(cred_id), "public_key": b64u(cose), "sign_count": sign_count,
              "name": (body.get("name") or "Passkey")[:60], "created": iso(now()), "rp_id": rp_id,
              "last_used": None}
        self.creds.data.setdefault("passkeys", []).append(pk)
        self.creds.save()
        return pk

    def login_options(self, rp_id: str) -> dict:
        return {"challenge": self.new_challenge("login"), "rpId": rp_id, "timeout": 120000,
                "userVerification": "preferred", "allowCredentials": []}

    def login_verify(self, body: dict, rp_id: str) -> dict:
        client_json = b64u_dec(body["clientDataJSON"])
        cd = self._check_client(client_json, "webauthn.get", rp_id)
        self.take_challenge(cd["challenge"], "login")
        cred_id = body.get("id") or body.get("rawId")
        pk = next((p for p in self.creds.data.get("passkeys", []) if p["id"] == cred_id), None)
        if not pk:
            raise ValueError("Unbekannter Passkey")
        auth = b64u_dec(body["authenticatorData"])
        if auth[:32] != hashlib.sha256(rp_id.encode()).digest():
            raise ValueError("rpIdHash stimmt nicht")
        if not auth[32] & 0x01:
            raise ValueError("Benutzer nicht anwesend")
        signed = auth + hashlib.sha256(client_json).digest()
        cose_verify(b64u_dec(pk["public_key"]), b64u_dec(body["signature"]), signed)
        cnt = int.from_bytes(auth[33:37], "big")
        if cnt and pk.get("sign_count") and cnt <= pk["sign_count"]:
            raise ValueError("Signaturzähler zurückgegangen – möglicher Klon")
        pk["sign_count"] = cnt
        pk["last_used"] = iso(now())
        self.creds.save()
        return pk


# ════════════════════════════════════════════════════════════════════════════
#  Live-Hub (Server-Sent Events)
# ════════════════════════════════════════════════════════════════════════════

class Hub:
    def __init__(self) -> None:
        self.clients: set[asyncio.Queue] = set()

    def publish(self, event: str, data: Any) -> None:
        msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        for q in list(self.clients):
            if q.qsize() < 1000:
                q.put_nowait(msg)


# ════════════════════════════════════════════════════════════════════════════
#  Apple-Anmeldung mit macOS-Identität (seit Oktober 2026 nötig)
# ════════════════════════════════════════════════════════════════════════════
#
# Apple lehnt seit ca. 12.10.2026 Anmeldungen mit der bisherigen Android-Anisette
# ab („Email verification failed …“, kein searchPartyToken). Lösung wie in
# FindMy.py #278/#279: Apples echte CoreADI-Bibliothek (macOS, aus dem offiziellen
# iTunes-12.8.3-Installer) läuft in einem x86-Emulator (Unicorn).
#   * Die Bibliothek lädt der Server einmalig direkt von Apple (~290 MB) und prüft
#     beide SHA-256-Summen. Ausgepackt wird in reinem Python (kein 7-Zip nötig).
#   * Emulator-Code: sacca97/os-findmy-e@374d838, tools/machoadi (MIT, © 2026 sacca),
#     mit den Anpassungen aus RJ TrackerApp (Paket-Importe, Datei schließen).
#   * Statt Download: Umgebungsvariable FMU_MACOS_ADI bzw. MACOS_ADI_BINARY auf eine
#     vorhandene CoreADI.x86_64 (z. B. aus RJ TrackerApp runtime/) zeigen lassen.

APPLE_DMG_URL = ("https://secure-appldnld.apple.com/itunes12/041-56365-20210413-79A5AC6D-6B0A-46EC-B399-"
                 "5A381183E3BE/iTunes12.8.3.dmg")
APPLE_DMG_SHA256 = "dd08b9967db3e5847955fa168ce880303abf5f36de12abb2061e7ef1a25be214"
APPLE_ADI_SHA256 = "2eafc3c79c7f41a8afbfbeaaf23ee5dab5ad5bda55ec8e54dbc0ddf1d20ce630"
APPLE_ADI_FRAMEWORK = "System/Library/PrivateFrameworks/CoreADI.framework/Versions/A/CoreADI"


def _udif_to_raw(dmg: Path, out: Any) -> None:
    """Apple-Disk-Image (UDIF) in ein Rohabbild schreiben (zlib/bzip2/unkomprimiert)."""
    import bz2
    with open(dmg, "rb") as f:
        f.seek(-512, 2)
        koly = f.read(512)
        if koly[:4] != b"koly":
            raise ValueError("Kein Apple-Disk-Image")
        xml_off, xml_len = struct.unpack_from(">QQ", koly, 0xD8)
        f.seek(xml_off)
        pl = plistlib.loads(f.read(xml_len))
        for blk in pl["resource-fork"]["blkx"]:
            mish = blk["Data"]
            if mish[:4] != b"mish":
                raise ValueError("Unbekannte Disk-Image-Tabelle")
            sector0, = struct.unpack_from(">Q", mish, 8)
            data_off, = struct.unpack_from(">Q", mish, 24)
            n, = struct.unpack_from(">I", mish, 200)
            for i in range(n):
                t, _, sn, _, co, cl = struct.unpack_from(">IIQQQQ", mish, 204 + 40 * i)
                if t in (0, 2, 0x7FFFFFFE, 0xFFFFFFFF):
                    continue
                f.seek(data_off + co)
                buf = f.read(cl)
                if t == 1:
                    data = buf
                elif t == 0x80000005:
                    data = zlib.decompress(buf)
                elif t == 0x80000006:
                    data = bz2.decompress(buf)
                else:
                    raise ValueError(f"Disk-Image-Kompression {t:#x} nicht unterstützt")
                out.seek((sector0 + sn) * 512)
                out.write(data)


def _adi_from_image(blob: Any) -> bytes:
    """CoreADI (x86_64) aus dem Rohabbild holen: xar-Paket → CoreADI.pkg/Payload → cpio → Mach-O."""
    import gzip
    import xml.etree.ElementTree as ET
    pos = 0
    payload = None
    while payload is None:
        pos = blob.find(b"xar!", pos)
        if pos < 0:
            raise ValueError("CoreADI.pkg im Apple-Installer nicht gefunden")
        try:
            hsize, _, tcl, _, _ = struct.unpack_from(">HHQQI", blob, pos + 4)
            if hsize < 28 or tcl > 50_000_000:
                raise ValueError
            toc = zlib.decompress(blob[pos + hsize:pos + hsize + tcl]).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pos += 4
            continue
        if "CoreADI.pkg" in toc:
            heap = pos + hsize + tcl
            for d in ET.fromstring(toc).iter("file"):
                if (d.findtext("name") or "") != "CoreADI.pkg":
                    continue
                for f in d.findall("file"):
                    if f.findtext("name") != "Payload":
                        continue
                    off, ln = int(f.findtext("data/offset")), int(f.findtext("data/length"))
                    sha1 = (f.findtext("data/archived-checksum") or "").strip().lower()
                    cand = blob[heap + off:heap + off + ln]
                    if hashlib.sha1(cand).hexdigest() == sha1:
                        payload = cand
                    else:  # Paket liegt im HFS+-Abbild nicht am Stück → über Prüfsumme suchen
                        p = 0
                        while payload is None and (p := blob.find(b"\x1f\x8b\x08", p)) >= 0:
                            if hashlib.sha1(blob[p:p + ln]).hexdigest() == sha1:
                                payload = blob[p:p + ln]
                            p += 1
        pos += 4
    data = gzip.decompress(payload)
    pos, framework = 0, None
    while pos + 76 <= len(data):
        if data[pos:pos + 6] != b"070707":
            raise ValueError("Unerwartetes cpio-Format")
        mode = int(data[pos + 18:pos + 24], 8)
        name_size = int(data[pos + 59:pos + 65], 8)
        size = int(data[pos + 65:pos + 76], 8)
        start, end = pos + 76, pos + 76 + name_size
        name = data[start:end - 1].decode()
        if name.removeprefix("./") == APPLE_ADI_FRAMEWORK and mode & 0o170000 == 0o100000:
            framework = data[end:end + size]
            break
        if name == "TRAILER!!!":
            break
        pos = end + size
    if framework is None or framework[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("CoreADI.framework nicht gefunden")
    count, = struct.unpack_from(">I", framework, 4)
    for i in range(count):
        cpu, _, off, size, _ = struct.unpack_from(">IIIII", framework, 8 + i * 20)
        if cpu == 0x01000007:
            binary = framework[off:off + size]
            if hashlib.sha256(binary).hexdigest() != APPLE_ADI_SHA256:
                raise ValueError("CoreADI-Version passt nicht (SHA-256)")
            return binary
    raise ValueError("Keine x86_64-CoreADI im Installer")


class AppleRuntime:
    """Bereitstellung der macOS-CoreADI und des Emulators für die Apple-Anmeldung."""

    def __init__(self) -> None:
        self.dir = DATA_DIR / "apple_adi"
        env = os.environ.get("FMU_MACOS_ADI") or os.environ.get("MACOS_ADI_BINARY")
        self.binary = Path(env).expanduser() if env else self.dir / "CoreADI.x86_64"
        self.state = "unknown"      # ready | missing | installing | error | incompatible
        self.message = ""
        self.progress = 0.0
        self._task: asyncio.Task | None = None
        self._activated = False

    def status(self) -> dict:
        return {"state": self.state, "message": self.message, "progress": round(self.progress, 3),
                "binary": str(self.binary)}

    def check(self) -> bool:
        if _deps_state() != "ok":
            self.state = "incompatible"
            self.message = ("Die installierte FindMy.py-Version kennt die neue Apple-Anmeldung nicht. "
                            "Server einmal ohne --no-bootstrap starten (aktualisiert automatisch).")
            return False
        try:
            ok = self.binary.is_file() and hashlib.sha256(self.binary.read_bytes()).hexdigest() == APPLE_ADI_SHA256
        except OSError:
            ok = False
        if not ok:
            if self.state not in ("installing", "error"):
                self.state = "missing"
                self.message = "macOS-Komponente fehlt – wird einmalig von Apple geladen (~290 MB)."
            return False
        self.activate()
        self.state, self.message, self.progress = "ready", "Bereit", 1.0
        return True

    def activate(self) -> None:
        """Emulator-Quellen schreiben und Anisette auf die macOS-CoreADI umstellen."""
        if self._activated:
            return
        pkg = self.dir / "apple_coreadi"
        pkg.mkdir(parents=True, exist_ok=True)
        for name, src in APPLE_COREADI_SOURCES.items():
            target = pkg / name
            if not target.exists() or target.read_text("utf-8") != src:
                target.write_text(src, "utf-8")
        bridge = self.dir / "fmu_apple_adi.py"
        if not bridge.exists() or bridge.read_text("utf-8") != APPLE_ADI_BRIDGE:
            bridge.write_text(APPLE_ADI_BRIDGE, "utf-8")
        if str(self.dir) not in sys.path:
            sys.path.insert(0, str(self.dir))
        os.environ["MACOS_ADI_BINARY"] = str(self.binary)
        import fmu_apple_adi  # type: ignore[import-not-found]
        fmu_apple_adi.install_itunes_adi_backend()
        self._activated = True

    def _install_sync(self) -> None:
        import tempfile
        import urllib.request
        self.dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="fmu-adi-", dir=self.dir) as tmp:
            dmg = Path(tmp) / "iTunes12.8.3.dmg"
            self.message = "Lade Apple-Installer (~290 MB) …"
            req = urllib.request.Request(APPLE_DMG_URL, headers={"User-Agent": f"FindMyUltra/{VERSION}"})
            h = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=60) as r, open(dmg, "wb") as f:
                total = int(r.headers.get("Content-Length") or 291523996)
                done = 0
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    self.progress = min(0.9, done / total * 0.9)
            if h.hexdigest() != APPLE_DMG_SHA256:
                raise ValueError("Apple-Installer: Prüfsumme stimmt nicht – Download beschädigt?")
            self.message = "Packe macOS-Komponente aus …"
            import mmap
            with tempfile.TemporaryFile(dir=tmp) as raw:
                _udif_to_raw(dmg, raw)
                raw.flush()
                with mmap.mmap(raw.fileno(), 0, access=mmap.ACCESS_READ) as blob:
                    binary = _adi_from_image(blob)
        self.binary.parent.mkdir(parents=True, exist_ok=True)
        secure_write(self.binary, binary)

    def start_install(self) -> None:
        if self._task and not self._task.done():
            return

        async def run() -> None:
            self.state, self.progress = "installing", 0.0
            try:
                await asyncio.to_thread(self._install_sync)
                self.check()
                log.info("macOS-Komponente für die Apple-Anmeldung eingerichtet.")
            except Exception as e:  # noqa: BLE001
                self.state, self.message = "error", f"Einrichtung fehlgeschlagen: {e}"
                log.warning("Apple-Komponente: %s", e)

        self._task = asyncio.create_task(run())


def apple_http_session(provider: Any) -> Any:
    """HTTP-Sitzung, die bei gsa.apple.com den User-Agent des Mac-Profils sendet."""
    from findmy.util.http import HttpSession

    class _IdentityHttp(HttpSession):
        async def request(self, method: str, url: str, **kwargs: Any) -> Any:
            if urlparse(url).hostname == "gsa.apple.com" and hasattr(provider, "user_agent"):
                headers = dict(kwargs.get("headers") or {})
                headers["User-Agent"] = provider.user_agent
                kwargs["headers"] = headers
            return await super().request(method, url, **kwargs)

    return _IdentityHttp()


def apple_session_is_mac(path: Path) -> bool:
    """True, wenn die gespeicherte Apple-Sitzung schon die macOS-Identität nutzt."""
    try:
        data = json.loads(path.read_text("utf-8"))
        inner = json.loads(base64.b64decode(data["anisette"]["prov_data"]))
        adi = json.loads(base64.b64decode(inner["adi_pb"]))
        return adi.get("provider") == "itunes-coreadi"
    except Exception:  # noqa: BLE001
        return False


def apple_has_search_token(acc: Any) -> bool:
    with contextlib.suppress(Exception):
        tokens = acc.to_json()["login"]["data"]["mobileme_data"]["tokens"]
        return bool(tokens.get("searchPartyToken"))
    return False


# Brücke Anisette ↔ CoreADI (aus RJ TrackerApp, Backend/apple_adi.py)
APPLE_ADI_BRIDGE = r'''"""Anisette V2 bridge for the verified iTunes 4.19 CoreADI build.

A fresh emulator per OTP prevents the upstream long-lived VM exhaustion.
Only provisioning keeps a VM across start/end; account state embeds the
machine UUID and ADI files, allowing restart without a fresh registration.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
from threading import RLock
import uuid

from anisette._adi import BaseADI, CPIM, OneTimePassword
from apple_coreadi.adi_run import CoreADI

STORE = '/Users/Shared/adi/'


def signed(value):
    return value - (1 << 64) if value >= 1 << 63 else value


def checked(result):
    if not result.ok:
        raise RuntimeError(f'Apple CoreADI {result.name} failed ({result.rc}/{result.ret})')
    return result.outputs


class ITunesADI(BaseADI):
    def __init__(self, identifier, adi_pb):
        self.identifier = identifier
        self.lock = RLock()
        self.pending = None
        self.files = {}
        self.host_uuid = uuid.uuid4().bytes
        self.routing = None
        if adi_pb:
            data = json.loads(adi_pb)
            if data.get('provider') != 'itunes-coreadi' or data.get('version') != 1 or data.get('identifier') != identifier:
                raise ValueError('Apple ADI session requires a new Apple login')
            self.host_uuid = bytes.fromhex(data['host_uuid'])
            if len(self.host_uuid) != 16:
                raise ValueError('Invalid Apple ADI machine UUID')
            self.files = {key: base64.b64decode(value, validate=True) for key, value in data['files'].items() if key.startswith(STORE) and key != STORE+'adi.pb'}
            self.routing = data.get('routing')

    @classmethod
    def create(cls, url=None):
        if url is not None:
            raise ValueError('Use setup_apple_adi.py for the official Apple runtime')
        return lambda identifier, adi_pb: cls(identifier, adi_pb)

    @property
    def routing_information(self):
        return self.routing

    @property
    def adi_pb(self):
        with self.lock:
            return json.dumps({'provider': 'itunes-coreadi', 'version': 1,
                'identifier': self.identifier, 'host_uuid': self.host_uuid.hex(),
                'routing': self.routing,
                'files': {k: base64.b64encode(v).decode() for k,v in self.files.items()}}, sort_keys=True).encode()

    def _core(self):
        core = CoreADI(Path(os.environ['MACOS_ADI_BINARY']))
        core.stubs.hostuuid = self.host_uuid
        core.stubs.files.update({k: bytearray(v) for k,v in self.files.items()})
        checked(core.initialize())
        return core

    def _save(self, core):
        self.files = {k: bytes(v) for k,v in core.stubs.files.items() if k.startswith(STORE) and k != STORE+'adi.pb'}

    async def _run(self, operation):
        def call():
            with self.lock:
                return operation()
        return await asyncio.get_running_loop().run_in_executor(None, call)

    async def is_machine_provisioned(self, ds_id=(1 << 64)-2):
        def call():
            result = self._core().is_machine_provisioned(signed(ds_id))
            if result.ret == -45061:
                return False
            checked(result)
            return True
        return await self._run(call)

    async def start_provisioning(self, spim, ds_id=(1 << 64)-2):
        def call():
            self.pending = self._core()
            result = checked(self.pending.provisioning_start(signed(ds_id), spim))
            return CPIM(result['cpim'], result['session_id'])
        return await self._run(call)

    async def end_provisioning(self, session, persistent_token_metadata, trust_key):
        def call():
            if self.pending is None:
                raise RuntimeError('No pending Apple ADI provisioning session')
            try:
                checked(self.pending.provisioning_end(session, persistent_token_metadata, trust_key))
                self._save(self.pending)
            finally:
                self.pending = None
        await self._run(call)

    async def set_idms_routing(self, routing_information):
        def call():
            core = self._core()
            checked(core.set_routing(-2, routing_information))
            self.routing = routing_information
            self._save(core)
        await self._run(call)

    async def request_otp(self, ds_id=(1 << 64)-2):
        def call():
            core = self._core()
            result = checked(core.request_otp(signed(ds_id)))
            self._save(core)
            return OneTimePassword(otp=result['otp'], machine_id=result['mid'])
        return await self._run(call)


def install_itunes_adi_backend():
    from anisette import AsyncAnisetteProvider
    AsyncAnisetteProvider.DEFAULT_ADI = ITunesADI
'''

# Emulator (MIT, © 2026 sacca – sacca97/os-findmy-e@374d838, tools/machoadi)
APPLE_COREADI_SOURCES: dict[str, str] = {
    '__init__.py': r'''"""Vendored MIT-licensed CoreADI emulator; see SOURCE.md."""
''',
    'macho.py': r'''"""Minimal Mach-O (64-bit) reader focused on what a Unicorn loader needs.

Only the pieces required to *map* a pre-11.0 Mach-O and resolve its external
symbols are implemented:

* segments / sections
* ``LC_SYMTAB`` (for names + symbol classification)
* classic ``LC_DYLD_INFO[_ONLY]`` rebase / bind / lazy-bind opcode streams
* the lists of linked dylibs

Chained fixups (macOS 12+), which this corpus predates, are not handled.

All offsets in the bind/rebase streams are decoded with the same state machine
dyld uses (see dyld's ``ImageLoaderMachOCompressed.cpp``).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MH_MAGIC_64 = 0xFEEDFACF
MH_EXECUTE = 0x2
MH_DYLIB = 0x6

LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB
LC_LOAD_DYLIB = 0xC
LC_ID_DYLIB = 0xD
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_REEXPORT_DYLIB = 0x8000001F
LC_LAZY_LOAD_DYLIB = 0x20
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_CODE_SIGNATURE = 0x1D
LC_FUNCTION_STARTS = 0x26
LC_DYLD_EXPORTS_TRIE = 0x80000033
LC_DYLD_CHAINED_FIXUPS = 0x80000034

# --- bind opcodes ---------------------------------------------------------
BIND_OPCODE_MASK = 0xF0
BIND_IMMEDIATE_MASK = 0x0F
BIND_OPCODE_DONE = 0x00
BIND_OPCODE_SET_DYLIB_ORDINAL_IMM = 0x10
BIND_OPCODE_SET_DYLIB_ORDINAL_ULEB = 0x20
BIND_OPCODE_SET_DYLIB_SPECIAL_IMM = 0x30
BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM = 0x40
BIND_OPCODE_SET_TYPE_IMM = 0x50
BIND_OPCODE_SET_ADDEND_SLEB = 0x60
BIND_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB = 0x70
BIND_OPCODE_ADD_ADDR_ULEB = 0x80
BIND_OPCODE_DO_BIND = 0x90
BIND_OPCODE_DO_BIND_ADD_ADDR_ULEB = 0xA0
BIND_OPCODE_DO_BIND_ADD_ADDR_IMM_SCALED = 0xB0
BIND_OPCODE_DO_BIND_ULEB_TIMES_SKIPPING_ULEB = 0xC0
BIND_OPCODE_THREADED = 0xD0

BIND_SYMBOL_FLAGS_WEAK_IMPORT = 0x1
BIND_SYMBOL_FLAGS_NON_WEAK_DEFINITION = 0x8

BIND_TYPE_POINTER = 1
BIND_TYPE_TEXT_ABSOLUTE32 = 2
BIND_TYPE_TEXT_PCREL32 = 3

# --- rebase opcodes -------------------------------------------------------
REBASE_OPCODE_MASK = 0xF0
REBASE_IMMEDIATE_MASK = 0x0F
REBASE_OPCODE_DONE = 0x00
REBASE_OPCODE_SET_TYPE_IMM = 0x10
REBASE_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB = 0x20
REBASE_OPCODE_ADD_ADDR_ULEB = 0x30
REBASE_OPCODE_ADD_ADDR_IMM_SCALED = 0x40
REBASE_OPCODE_DO_REBASE_IMM_TIMES = 0x50
REBASE_OPCODE_DO_REBASE_ULEB_TIMES = 0x60
REBASE_OPCODE_DO_REBASE_ADD_ADDR_ULEB = 0x70
REBASE_OPCODE_DO_REBASE_ULEB_TIMES_SKIPPING_ULEB = 0x80

REBASE_TYPE_POINTER = 1
REBASE_TYPE_TEXT_ABSOLUTE32 = 2
REBASE_TYPE_TEXT_PCREL32 = 3

_DYLIB_CMD_NAMES = {
    LC_LOAD_DYLIB: "load",
    LC_ID_DYLIB: "id",
    LC_LOAD_WEAK_DYLIB: "weak",
    LC_REEXPORT_DYLIB: "reexport",
    LC_LAZY_LOAD_DYLIB: "lazy",
}


def _u(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _q(data: bytes, off: int) -> int:
    return struct.unpack_from("<Q", data, off)[0]


def read_uleb(data: bytes, off: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = data[off]
        off += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if byte & 0x80 == 0:
            return result, off


def read_sleb(data: bytes, off: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = data[off]
        off += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if byte & 0x80 == 0:
            if shift < 64 and byte & 0x40:
                result |= -(1 << shift)
            return result, off


def _cstr(data: bytes, off: int) -> str:
    end = data.index(b"\x00", off)
    return data[off:end].decode("utf-8", "replace")


@dataclass
class Section:
    segname: str
    sectname: str
    addr: int
    size: int
    offset: int
    align: int
    flags: int

    @property
    def qual(self) -> str:
        return f"{self.segname}.{self.sectname}"


@dataclass
class Segment:
    name: str
    vmaddr: int
    vmsize: int
    fileoff: int
    filesize: int
    maxprot: int
    initprot: int
    sections: list[Section] = field(default_factory=list)


@dataclass
class Bind:
    address: int
    seg_index: int
    segname: str
    ordinal: int
    symbol: str
    flags: int
    addend: int
    type: int
    lazy: bool = False
    library: str | None = None

    @property
    def weak(self) -> bool:
        return bool(self.flags & BIND_SYMBOL_FLAGS_WEAK_IMPORT)


@dataclass
class Rebase:
    address: int
    seg_index: int
    segname: str
    type: int


class MachOError(RuntimeError):
    pass


class MachO:
    def __init__(self, data: bytes, path: str = "") -> None:
        self.data = data
        self.path = path
        self.slices: list[str] = []

        magic = _u(data, 0)
        if magic == 0xCAFEBABE or magic == 0xBEBAFECA:
            raise MachOError("fat Mach-O: use the thin slice")
        if magic != MH_MAGIC_64:
            raise MachOError(f"not a 64-bit Mach-O (magic={magic:#x})")

        (
            _magic,
            self.cputype,
            self.cpusubtype,
            self.filetype,
            self.ncmds,
            self.sizeofcmds,
            self.flags,
            _reserved,
        ) = struct.unpack_from("<IIIIIIII", data, 0)

        self.segments: list[Segment] = []
        self.dylibs: list[tuple[int, str]] = []
        self.symoff = self.nsyms = self.stroff = self.strsize = 0
        self._dyld_info: dict[str, tuple[int, int]] = {}
        self._parse_load_commands()

        # Full symtab view.
        self.symbols: list[tuple[str, int, int, int, int]] = []
        self._parse_symtab()

    # -- load commands ----------------------------------------------------
    def _parse_load_commands(self) -> None:
        off = 32
        for _ in range(self.ncmds):
            cmd = _u(self.data, off)
            cmdsize = _u(self.data, off + 4)
            if cmd == LC_SEGMENT_64:
                self._parse_segment(off)
            elif cmd in _DYLIB_CMD_NAMES:
                nameoff = _u(self.data, off + 8)
                name = _cstr(self.data, off + nameoff)
                if cmd != LC_ID_DYLIB:
                    self.dylibs.append((cmd, name))
            elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
                fields = struct.unpack_from("<10I", self.data, off + 8)
                for i, key in enumerate(["rebase", "bind", "weak_bind", "lazy_bind", "export"]):
                    self._dyld_info[key] = (fields[i * 2], fields[i * 2 + 1])
            elif cmd == LC_SYMTAB:
                (
                    self.symoff,
                    self.nsyms,
                    self.stroff,
                    self.strsize,
                ) = struct.unpack_from("<IIII", self.data, off + 8)
            off += cmdsize

    def _parse_segment(self, off: int) -> None:
        name = self.data[off + 8 : off + 24].rstrip(b"\x00").decode("ascii", "replace")
        vmaddr, vmsize, fileoff, filesize, maxprot, initprot, nsects, _flags = struct.unpack_from(
            "<QQQQIIII", self.data, off + 24
        )
        seg = Segment(name, vmaddr, vmsize, fileoff, filesize, maxprot, initprot)
        so = off + 72
        for _ in range(nsects):
            sectname = self.data[so : so + 16].rstrip(b"\x00").decode("ascii", "replace")
            segname = self.data[so + 16 : so + 32].rstrip(b"\x00").decode("ascii", "replace")
            addr, size = struct.unpack_from("<QQ", self.data, so + 32)
            (offset,) = struct.unpack_from("<I", self.data, so + 48)
            align, _reloff, _nreloc, flags, _r1, _r2, _r3 = struct.unpack_from(
                "<IIIIIII", self.data, so + 52
            )
            seg.sections.append(Section(segname, sectname, addr, size, offset, align, flags))
            so += 80
        self.segments.append(seg)

    def _parse_symtab(self) -> None:
        for i in range(self.nsyms):
            base = self.symoff + 16 * i
            strx, n_type, n_sect, n_desc, n_value = struct.unpack_from("<IBBHQ", self.data, base)
            name = _cstr(self.data, self.stroff + strx)
            self.symbols.append((name, n_type, n_sect, n_desc, n_value))

    # -- lookups ----------------------------------------------------------
    @property
    def undefined_symbols(self) -> list[tuple[str, int, int]]:
        """(name, n_desc, n_type) for every N_UNDF|N_EXT symbol."""
        out = []
        for name, n_type, _n_sect, n_desc, _value in self.symbols:
            if n_type & 0x0E == 0x00 and n_type & 0x01:  # N_UNDF | N_EXT
                out.append((name, n_desc, n_type))
        return out

    def segment_for(self, addr: int) -> tuple[int, Segment] | None:
        for i, seg in enumerate(self.segments):
            if seg.vmaddr <= addr < seg.vmaddr + seg.vmsize:
                return i, seg
        return None

    def section_for(self, addr: int) -> Section | None:
        hit = self.segment_for(addr)
        if hit is None:
            return None
        for sect in hit[1].sections:
            if sect.addr <= addr < sect.addr + sect.size:
                return sect
        return None

    def read_cstr_at(self, addr: int) -> str:
        seg_i = self.segment_for(addr)
        if seg_i is None:
            raise MachOError(f"address {addr:#x} not in any segment")
        _i, seg = seg_i
        file_off = seg.fileoff + (addr - seg.vmaddr)
        return _cstr(self.data, file_off)

    def dylib_name(self, ordinal: int) -> str | None:
        """ordinal is 1-based index into the load-dylib list."""
        if 1 <= ordinal <= len(self.dylibs):
            return self.dylibs[ordinal - 1][1]
        return None

    # -- dyld info --------------------------------------------------------
    def _stream(self, name: str) -> tuple[int, int]:
        return self._dyld_info.get(name, (0, 0))

    def iter_rebases(self) -> list[Rebase]:
        off, size = self._stream("rebase")
        if size == 0:
            return []
        data = self.data
        end = off + size
        out: list[Rebase] = []
        seg_index = 0
        seg_offset = 0
        rtype = REBASE_TYPE_POINTER
        while off < end:
            byte = data[off]
            opcode = byte & REBASE_OPCODE_MASK
            imm = byte & REBASE_IMMEDIATE_MASK
            off += 1
            if opcode == REBASE_OPCODE_DONE:
                break
            elif opcode == REBASE_OPCODE_SET_TYPE_IMM:
                rtype = imm
            elif opcode == REBASE_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB:
                seg_index = imm
                seg_offset, off = read_uleb(data, off)
            elif opcode == REBASE_OPCODE_ADD_ADDR_ULEB:
                val, off = read_uleb(data, off)
                seg_offset += val
            elif opcode == REBASE_OPCODE_ADD_ADDR_IMM_SCALED:
                seg_offset += imm * 8
            elif opcode == REBASE_OPCODE_DO_REBASE_IMM_TIMES:
                for _ in range(imm):
                    out.append(self._mk_rebase(seg_index, seg_offset, rtype))
                    seg_offset += 8
            elif opcode == REBASE_OPCODE_DO_REBASE_ULEB_TIMES:
                count, off = read_uleb(data, off)
                for _ in range(count):
                    out.append(self._mk_rebase(seg_index, seg_offset, rtype))
                    seg_offset += 8
            elif opcode == REBASE_OPCODE_DO_REBASE_ADD_ADDR_ULEB:
                out.append(self._mk_rebase(seg_index, seg_offset, rtype))
                val, off = read_uleb(data, off)
                seg_offset += val + 8
            elif opcode == REBASE_OPCODE_DO_REBASE_ULEB_TIMES_SKIPPING_ULEB:
                count, off = read_uleb(data, off)
                skip, off = read_uleb(data, off)
                for _ in range(count):
                    out.append(self._mk_rebase(seg_index, seg_offset, rtype))
                    seg_offset += skip + 8
            else:
                raise MachOError(f"bad rebase opcode {opcode:#x} at {off - 1:#x}")
        return out

    def _mk_rebase(self, seg_index: int, seg_offset: int, rtype: int) -> Rebase:
        seg = self.segments[seg_index]
        return Rebase(seg.vmaddr + seg_offset, seg_index, seg.name, rtype)

    def _iter_binds(self, stream: str, lazy: bool) -> list[Bind]:
        off, size = self._stream(stream)
        if size == 0:
            return []
        data = self.data
        end = off + size

        out: list[Bind] = []
        ordinal = 0
        symbol = ""
        sym_flags = 0
        btype = BIND_TYPE_POINTER
        addend = 0
        seg_index = 0
        seg_offset = 0
        while off < end:
            byte = data[off]
            opcode = byte & BIND_OPCODE_MASK
            imm = byte & BIND_IMMEDIATE_MASK
            off += 1
            if opcode == BIND_OPCODE_DONE:
                if lazy:
                    # each lazy entry terminates with DONE; keep going
                    continue
                break
            elif opcode == BIND_OPCODE_SET_DYLIB_ORDINAL_IMM:
                ordinal = imm
            elif opcode == BIND_OPCODE_SET_DYLIB_ORDINAL_ULEB:
                ordinal, off = read_uleb(data, off)
            elif opcode == BIND_OPCODE_SET_DYLIB_SPECIAL_IMM:
                ordinal = imm if imm == 0 else (0xF0 | imm) - 0x100
            elif opcode == BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM:
                sym_flags = imm
                # The symbol name follows inline, NUL-terminated.
                end_pos = data.index(b"\x00", off)
                symbol = data[off:end_pos].decode("ascii", "replace")
                off = end_pos + 1
            elif opcode == BIND_OPCODE_SET_TYPE_IMM:
                btype = imm
            elif opcode == BIND_OPCODE_SET_ADDEND_SLEB:
                addend, off = read_sleb(data, off)
            elif opcode == BIND_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB:
                seg_index = imm
                seg_offset, off = read_uleb(data, off)
            elif opcode == BIND_OPCODE_ADD_ADDR_ULEB:
                val, off = read_uleb(data, off)
                seg_offset = (seg_offset + val) & 0xFFFFFFFFFFFFFFFF
            elif opcode == BIND_OPCODE_DO_BIND:
                out.append(self._mk_bind(seg_index, seg_offset, ordinal, symbol, sym_flags, addend, btype, lazy))
                seg_offset += 8
            elif opcode == BIND_OPCODE_DO_BIND_ADD_ADDR_ULEB:
                out.append(self._mk_bind(seg_index, seg_offset, ordinal, symbol, sym_flags, addend, btype, lazy))
                val, off = read_uleb(data, off)
                seg_offset = (seg_offset + val + 8) & 0xFFFFFFFFFFFFFFFF
            elif opcode == BIND_OPCODE_DO_BIND_ADD_ADDR_IMM_SCALED:
                out.append(self._mk_bind(seg_index, seg_offset, ordinal, symbol, sym_flags, addend, btype, lazy))
                seg_offset += imm * 8 + 8
            elif opcode == BIND_OPCODE_DO_BIND_ULEB_TIMES_SKIPPING_ULEB:
                count, off = read_uleb(data, off)
                skip, off = read_uleb(data, off)
                for _ in range(count):
                    out.append(self._mk_bind(seg_index, seg_offset, ordinal, symbol, sym_flags, addend, btype, lazy))
                    seg_offset += skip + 8
            elif opcode == BIND_OPCODE_THREADED:
                raise MachOError("threaded bind opcode (chained fixups) is not supported")
            else:
                raise MachOError(f"bad bind opcode {opcode:#x} at {off - 1:#x}")
        return out

    def _mk_bind(
        self,
        seg_index: int,
        seg_offset: int,
        ordinal: int,
        symbol: str,
        flags: int,
        addend: int,
        btype: int,
        lazy: bool,
    ) -> Bind:
        seg = self.segments[seg_index]
        return Bind(
            address=seg.vmaddr + seg_offset,
            seg_index=seg_index,
            segname=seg.name,
            ordinal=ordinal,
            symbol=symbol,
            flags=flags,
            addend=addend,
            type=btype,
            lazy=lazy,
            library=self.dylib_name(ordinal) if ordinal > 0 else None,
        )

    def iter_binds(self) -> list[Bind]:
        return self._iter_binds("bind", lazy=False)

    def iter_lazy_binds(self) -> list[Bind]:
        return self._iter_binds("lazy_bind", lazy=True)

    def all_binds(self) -> list[Bind]:
        return self.iter_binds() + self.iter_lazy_binds()

    def bind_symbols(self) -> list[str]:
        seen: dict[str, None] = {}
        for b in self.all_binds():
            seen.setdefault(b.symbol, None)
        return list(seen)
''',
    'harness.py': r'''"""Unicorn-backed x86_64 Mach-O runtime for the Mac CoreADI whitebox.

This runs Apple's own (old, Intel, pre-chained-fixups) CoreADI binary under
emulation, so that its ADI dispatcher can be called from Python.

Loading strategy
----------------
The dylib's preferred base is 0, so we map every segment at its literal
``vmaddr`` and skip rebasing entirely (slide == 0). Import slots (dyld binds)
are redirected to a synthetic stub page: each imported symbol gets a unique
address holding ``ret``; a code hook fires on the way in, runs a Python handler,
and the ``ret`` returns to the caller (correct for both ``call`` and tail-call
``jmp`` positions).

Data imports (``kCF*`` constants, ``___stack_chk_guard``, ...) instead point at
a per-symbol 8-byte cell so normal dereferences see a plausible object.
"""

from __future__ import annotations

import logging
import struct
from collections.abc import Callable
from typing import Any

from unicorn import (
    UC_ARCH_X86,
    UC_HOOK_CODE,
    UC_HOOK_MEM_FETCH_UNMAPPED,
    UC_HOOK_MEM_READ_UNMAPPED,
    UC_HOOK_MEM_WRITE_UNMAPPED,
    UC_MEM_FETCH_UNMAPPED,
    UC_MEM_READ_UNMAPPED,
    UC_MEM_WRITE_UNMAPPED,
    UC_MODE_64,
    Uc,
)
from unicorn.x86_const import (
    UC_X86_REG_EFLAGS,
    UC_X86_REG_R10,
    UC_X86_REG_R11,
    UC_X86_REG_R12,
    UC_X86_REG_R13,
    UC_X86_REG_R14,
    UC_X86_REG_R15,
    UC_X86_REG_R8,
    UC_X86_REG_R9,
    UC_X86_REG_RAX,
    UC_X86_REG_RBP,
    UC_X86_REG_RBX,
    UC_X86_REG_RCX,
    UC_X86_REG_RDI,
    UC_X86_REG_RDX,
    UC_X86_REG_RIP,
    UC_X86_REG_RSI,
    UC_X86_REG_RSP,
)

from .macho import MachO

logger = logging.getLogger(__name__)

PAGE = 0x1000

# --- emulator address layout (kept well clear of the 0-based image) --------
RETURN_ADDRESS = 0x40000000
HEAP_ADDRESS = 0x40010000
HEAP_SIZE = 0x01000000
STACK_ADDRESS = 0x50000000
STACK_SIZE = 0x00200000
STUB_ADDRESS = 0x60000000
STUB_SIZE = 0x00020000
DATA_ADDRESS = 0x60020000
DATA_SIZE = 0x00020000
SCRATCH_ADDRESS = 0x60040000
SCRATCH_SIZE = 0x00040000
OBJECT_ADDRESS = 0x60080000
OBJECT_SIZE = 0x00040000

_STUB_SLOT = 0x10  # bytes between adjacent stubs
_RET = b"\xc3"

# Imports that denote a *variable* rather than a function entry point.
# Keys are normalised (leading Mach-O underscores stripped).
_DATA_SYMBOLS = {
    "stack_chk_guard",
    "kCFAllocatorDefault",
    "kCFBooleanFalse",
    "kCFBooleanTrue",
    "kCFErrorDomainOSStatus",
    "kCFURLFileSecurityKey",
    "kCFURLIsDirectoryKey",
    "kCFURLIsHiddenKey",
    "kCFURLTypeIdentifierKey",
    "kUTTypePlainText",
}


def _norm(symbol: str) -> str:
    """Strip Mach-O's leading underscores for handler/table lookup."""
    return symbol.lstrip("_")


def _is_data_symbol(symbol: str) -> bool:
    return _norm(symbol) in _DATA_SYMBOLS

_ARG_REGS = (UC_X86_REG_RDI, UC_X86_REG_RSI, UC_X86_REG_RDX, UC_X86_REG_RCX, UC_X86_REG_R8, UC_X86_REG_R9)


class EmulationError(RuntimeError):
    pass


class UnmappedAccess(EmulationError):
    pass


class MachOImage:
    def __init__(self, path: str, data: bytes | None = None) -> None:
        self.path = path
        if data is None:
            with open(path, "rb") as image_file:
                data = image_file.read()
        self.data = data
        self.macho = MachO(self.data, path)

    def map_into(self, uc: Uc) -> None:
        for seg in self.macho.segments:
            start = seg.vmaddr
            size = (seg.vmsize + PAGE - 1) // PAGE * PAGE
            if size == 0:
                continue
            uc.mem_map(start, size)
            if seg.filesize:
                blob = self.data[seg.fileoff : seg.fileoff + seg.filesize]
                uc.mem_write(start, blob.ljust(min(seg.vmsize, seg.filesize), b"\x00"))


class Harness:
    def __init__(self, image: MachOImage, *, log_stubs: bool = False, apply_binds: bool = True) -> None:
        self.image = image
        self.log_stubs = log_stubs
        self.fault: dict[str, int | str] | None = None
        self._fault_count = 0
        self._permissive = False
        self._max_faults = 64
        self._faults = 0
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)

        self._handlers: dict[str, Callable[[Harness], int | None]] = {}
        self._stub_addr: dict[str, int] = {}
        self._stub_by_index: dict[int, str] = {}
        self._data_addr: dict[str, int] = {}
        self._resolved: dict[int, str] = {}  # bind location -> symbol
        self._heap_cur = HEAP_ADDRESS
        self._scratch_cur = SCRATCH_ADDRESS
        self._obj_cur = OBJECT_ADDRESS
        self._calls: list[str] = []
        self._permissive_pages: set[int] = set()

        self._map_all()
        self._setup_stubs()
        self._install_default_handlers()
        if apply_binds:
            self._apply_binds()
        self._install_hooks()

    # -- setup ------------------------------------------------------------
    def _map_all(self) -> None:
        uc = self.uc
        uc.mem_map(RETURN_ADDRESS, PAGE)
        uc.mem_map(HEAP_ADDRESS, HEAP_SIZE)
        uc.mem_map(STACK_ADDRESS, STACK_SIZE)
        uc.mem_map(STUB_ADDRESS, STUB_SIZE)
        uc.mem_map(DATA_ADDRESS, DATA_SIZE)
        uc.mem_map(SCRATCH_ADDRESS, SCRATCH_SIZE)
        uc.mem_map(OBJECT_ADDRESS, OBJECT_SIZE)
        self.image.map_into(uc)

    def _setup_stubs(self) -> None:
        self.uc.mem_write(STUB_ADDRESS, _RET * STUB_SIZE)
        for i, sym in enumerate(self.image.macho.bind_symbols()):
            if _is_data_symbol(sym):
                cell = DATA_ADDRESS + i * _STUB_SLOT
                self._data_addr[sym] = cell
                self.uc.mem_write(cell, struct.pack("<Q", OBJECT_ADDRESS + i * _STUB_SLOT))
            else:
                addr = STUB_ADDRESS + i * _STUB_SLOT
                self._stub_addr[sym] = addr
                self._stub_by_index[addr] = sym

    def _apply_binds(self) -> None:
        for bind in self.image.macho.all_binds():
            sym = bind.symbol
            if sym in self._data_addr:
                target = self._data_addr[sym]
            elif sym in self._stub_addr:
                target = self._stub_addr[sym]
            else:
                # Not in the exported bind list (defensive): allocate a fresh stub.
                target = STUB_ADDRESS + (len(self._stub_addr) + 0x800) * _STUB_SLOT
                self._stub_addr[sym] = target
                self._stub_by_index[target] = sym
            # dyld semantics: the loader stores ``symbol + addend`` and the
            # whitebox later recovers the symbol with ``slot - addend``.  We
            # must reproduce that masking, otherwise the VM dereferences
            # ``stub - addend`` and runs off into unmapped memory.
            value = (target + bind.addend) & 0xFFFFFFFFFFFFFFFF
            self.uc.mem_write(bind.address, struct.pack("<Q", value))
            self._resolved[bind.address] = sym

    def _install_hooks(self) -> None:
        uc = self.uc
        uc.hook_add(UC_HOOK_CODE, self._hook_code, None, STUB_ADDRESS, STUB_ADDRESS + STUB_SIZE - 1)
        uc.hook_add(
            UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED,
            self._hook_invalid,
        )

    def _install_default_handlers(self) -> None:
        self.register("___stack_chk_fail", lambda h: self._abort("stack check failed"))
        for name in ("pthread_rwlock_init", "pthread_rwlock_rdlock", "pthread_rwlock_wrlock",
                     "pthread_rwlock_unlock", "pthread_rwlock_destroy"):
            self.register(name, lambda h: 0)
        self.register("getuid", lambda h: 501)  # _fpsd-ish uid; deterministic
        self.register("umask", lambda h: 0o022)
        self.register("arc4random", lambda h: 0x12345678)
        self.register("gethostuuid", self._gethostuuid)
        self.register("gettimeofday", self._gettimeofday)
        self.register("___error", self._errno_ptr)
        self.register("objc_msgSend", self._objc_msgSend)
        self.register("NSVersionOfRunTimeLibrary", lambda h: 0)
        self.register("CFErrorGetCode", lambda h: -1)
        self.register("CFErrorGetDomain", lambda h: 0)
        self.register("CFRelease", lambda h: 0)
        self.register("CSBackupIsItemExcluded", lambda h: 0)
        self.register("CSBackupSetItemExcluded", lambda h: 0)
        self.register("CFFileSecuritySetMode", lambda h: 1)
        self.register("malloc", self._malloc)
        self.register("free", self._free)

    # -- public API -------------------------------------------------------
    def register(self, symbol: str, handler: Callable[[Harness], int | None]) -> None:
        self._handlers[_norm(symbol)] = handler

    def mem_read(self, addr: int, size: int) -> bytes:
        return bytes(self.uc.mem_read(addr, size))

    def mem_write(self, addr: int, data: bytes) -> None:
        self.uc.mem_write(addr, data)

    def read_u64(self, addr: int) -> int:
        return struct.unpack("<Q", self.mem_read(addr, 8))[0]

    def read_u32(self, addr: int) -> int:
        return struct.unpack("<I", self.mem_read(addr, 4))[0]

    def write_u64(self, addr: int, value: int) -> None:
        self.mem_write(addr, struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF))

    def write_u32(self, addr: int, value: int) -> None:
        self.mem_write(addr, struct.pack("<I", value & 0xFFFFFFFF))

    def read_cstr(self, addr: int, max_len: int = 0x1000) -> str:
        out = bytearray()
        while len(out) < max_len:
            b = self.mem_read(addr + len(out), 1)
            if b == b"\x00":
                break
            out += b
        return out.decode("utf-8", "replace")

    def scratch(self, size: int) -> int:
        size = (size + 0xF) & ~0xF
        addr = self._scratch_cur
        self._scratch_cur += size
        return addr

    def object(self, size: int) -> int:
        size = (size + 0xF) & ~0xF
        addr = self._obj_cur
        self._obj_cur += size
        return addr

    def invoke(self, address: int, args: list[int], *, permissive: bool = False, max_faults: int = 64) -> int:
        uc = self.uc
        for reg, value in zip(_ARG_REGS, args):
            uc.reg_write(reg, value)
        rsp = STACK_ADDRESS + STACK_SIZE - 0x1000
        self.write_u64(rsp, RETURN_ADDRESS)
        uc.reg_write(UC_X86_REG_RSP, rsp)
        uc.reg_write(UC_X86_REG_RBP, 0)

        self._permissive = permissive
        self._max_faults = max_faults
        self._faults = 0
        try:
            uc.emu_start(address, RETURN_ADDRESS, timeout=0, count=0)
        except Exception as exc:  # noqa: BLE001
            fault = self.fault
            self.fault = None
            raise EmulationError(
                f"emulation failed at rip={uc.reg_read(UC_X86_REG_RIP):#x}: {exc}"
            ) from exc
        finally:
            self._permissive = False
        return uc.reg_read(UC_X86_REG_RAX)

    def _map_page(self, page: int) -> None:
        if page in self._permissive_pages:
            return
        self._permissive_pages.add(page)
        try:
            self.uc.mem_map(page, PAGE)
        except Exception:  # noqa: BLE001
            return

    def stack_trace(self) -> list[int]:
        return list(self._calls)

    # -- hooks ------------------------------------------------------------
    def _hook_code(self, uc: Uc, address: int, size: int, _user: Any) -> None:
        sym = self._stub_by_index.get(address)
        if sym is None:
            return
        self._calls.append(sym)
        handler = self._handlers.get(_norm(sym))
        if handler is None:
            if self.log_stubs:
                logger.info("stub %s (unhandled) -> 0", sym)
            return
        result = handler(self)
        if result is not None:
            uc.reg_write(UC_X86_REG_RAX, result & 0xFFFFFFFFFFFFFFFF)

    def _hook_invalid(self, uc: Uc, access: int, address: int, size: int, value: int, _user: Any) -> bool:
        self._fault_count += 1
        kind = {
            UC_MEM_READ_UNMAPPED: "read-unmapped",
            UC_MEM_WRITE_UNMAPPED: "write-unmapped",
            UC_MEM_FETCH_UNMAPPED: "fetch-unmapped",
        }.get(access, f"access-{access}")
        if self._permissive and kind.endswith("unmapped"):
            # The VM deliberately reads memory near the dyld-bound imports
            # (`*(symbol + addend - D)`), which only exists on a real macOS
            # shared cache. Materialise the page and let the access retry.
            self._faults += 1
            if self._faults > self._max_faults:
                raise EmulationError(f"too many faults ({self._faults})")
            self._map_page(address & ~(PAGE - 1))
            return True
        self.fault = {
            "kind": kind,
            "address": address,
            "size": size,
            "rip": uc.reg_read(UC_X86_REG_RIP),
            "rax": uc.reg_read(UC_X86_REG_RAX),
            "rbx": uc.reg_read(UC_X86_REG_RBX),
            "rcx": uc.reg_read(UC_X86_REG_RCX),
            "rdx": uc.reg_read(UC_X86_REG_RDX),
            "rsi": uc.reg_read(UC_X86_REG_RSI),
            "rdi": uc.reg_read(UC_X86_REG_RDI),
            "r8": uc.reg_read(UC_X86_REG_R8),
            "r9": uc.reg_read(UC_X86_REG_R9),
            "rbp": uc.reg_read(UC_X86_REG_RBP),
            "rsp": uc.reg_read(UC_X86_REG_RSP),
        }
        raise UnmappedAccess(f"{kind} at {address:#x} (size {size}) rip={self.fault['rip']:#x}")

    # -- handlers ---------------------------------------------------------
    def _abort(self, message: str) -> int:
        raise EmulationError(message)

    def _malloc(self, h: Harness) -> int:
        size = h.uc.reg_read(UC_X86_REG_RDI)
        addr = h._heap_cur
        h._heap_cur = (h._heap_cur + max(size, 0x20) + 0xF) & ~0xF
        return addr

    def _free(self, h: Harness) -> int:
        return 0

    def _errno_ptr(self, h: Harness) -> int:
        if not hasattr(h, "_errno_addr"):
            h._errno_addr = h.scratch(8)
            h.write_u64(h._errno_addr, 0)
        return h._errno_addr

    def _gethostuuid(self, h: Harness) -> int:
        out = h.uc.reg_read(UC_X86_REG_RDI)
        # A stable, obviously-synthetic UUID; caller-controlled in real use.
        h.mem_write(out, bytes.fromhex("41444d414341444941444d4143414449")[:16].ljust(16, b"\x00"))
        return 0

    def _gettimeofday(self, h: Harness) -> int:
        tv = h.uc.reg_read(UC_X86_REG_RDI)
        if tv:
            h.write_u64(tv, 1700000000)
            h.write_u64(tv + 8, 0)
        return 0

    _SEL_CACHE: dict[int, str] = {}

    def _objc_msgSend(self, h: Harness) -> int:
        sel = h.uc.reg_read(UC_X86_REG_RSI)
        name = h.read_cstr(sel)
        if h.log_stubs:
            logger.info("objc_msgSend sel=%s", name)
        if name == "processInfo":
            return h.object(0x100)
        if name == "operatingSystem":
            return 0x0D  # NSMavericks? see caller intent; logged for tuning
        if name == "isOperatingSystemAtLeastVersion:":
            return 1
        return 0
''',
    'stubs.py': r'''"""POSIX / CoreFoundation / Foundation stubs for the Mac CoreADI whitebox.

The dylib is a normal macOS userland component: once its imports are bound it
talks to libc (open/read/write/lstat/...), CoreFoundation (CFURL resource
properties) and a little Objective-C (NSProcessInfo) to decide where its
provisioning store lives and whether the machine already has an ADI blob.

Everything here is a *surrogate* for the host operating system, not a
reimplementation of ADI: the virtual filesystem is what a real Mac would have
under ``/Users/Shared/adi``, and the errno/stat plumbing mirrors BSD.
"""

from __future__ import annotations

import errno as _errno
import os
import struct
import time
import zlib
from typing import TYPE_CHECKING

from unicorn.x86_const import (
    UC_X86_REG_RDI,
    UC_X86_REG_RSI,
    UC_X86_REG_RDX,
    UC_X86_REG_RCX,
    UC_X86_REG_R8,
)

if TYPE_CHECKING:  # pragma: no cover
    from .harness import Harness

# macOS/x86_64 `struct stat` (the $INODE64 variant) is 144 bytes.
STAT_SIZE = 144
# macOS/x86_64 `struct statfs` is 2168 bytes; only the first fields matter here.
STATFS_SIZE = 2168

S_IFMT = 0o170000
S_IFDIR = 0o040000
S_IFREG = 0o100000

O_RDONLY = 0x0000
O_WRONLY = 0x0001
O_RDWR = 0x0002
O_CREAT = 0x0200
O_TRUNC = 0x0400
O_EXCL = 0x0800

_PROVISIONING_DIR = "/Users/Shared/adi"


class MacStubs:
    """A tiny synthetic macOS userland for the emulated CoreADI."""

    def __init__(self, harness: "Harness", *, log: bool = False) -> None:
        self.h = harness
        self.log = log
        self.files: dict[str, bytearray] = {}
        self.dirs: set[str] = {"/", "/Users", "/Users/Shared", _PROVISIONING_DIR}
        self.fds: dict[int, dict] = {}
        self.next_fd = 3
        self.urls: dict[int, str] = {}
        self._next_url = 0x60080000
        self._errno_addr: int | None = None
        self.home = "/Users/aditest"
        self.hostuuid = bytes.fromhex("00112233445566778899aabbccddeeff")
        # The whitebox loads a global such as `kCFURLIsDirectoryKey` as
        # `*(slot - mask)`, i.e. it sees the *object pointer* the cell holds,
        # not the cell address.  Build the reverse map it actually compares on.
        self.key_by_object = {
            harness.read_u64(cell): sym for sym, cell in harness._data_addr.items()
        }
        self._install()

    # -- helpers ----------------------------------------------------------
    def _a(self, index: int) -> int:
        regs = (UC_X86_REG_RDI, UC_X86_REG_RSI, UC_X86_REG_RDX, UC_X86_REG_RCX, UC_X86_REG_R8)
        return self.h.uc.reg_read(regs[index])

    def _s(self, addr: int, limit: int = 4096) -> str:
        try:
            return self.h.read_cstr(addr, limit)
        except Exception:  # noqa: BLE001
            return ""

    def _errno(self) -> int:
        if self._errno_addr is None:
            self._errno_addr = self.h.scratch(8)
        return self._errno_addr

    def set_errno(self, value: int) -> None:
        self.h.write_u32(self._errno(), value)

    def errno_ptr(self, h: "Harness") -> int:
        """`___error()` -- the address the caller dereferences to read errno."""
        return self._errno()

    def _fail(self, err: int) -> int:
        self.set_errno(err)
        return -1

    def _note(self, msg: str) -> None:
        if self.log:
            print("      [fs]", msg, flush=True)

    # -- virtual filesystem ----------------------------------------------
    def _exists(self, path: str) -> bool:
        return path in self.files or path in self.dirs

    def _inode(self, path: str) -> int:
        """A stable, per-path inode.

        The store logic compares entries by inode, so a single shared value
        makes distinct files look like hard links of one another.
        """
        return 0x10000 + (zlib.crc32(path.encode()) & 0xFFFFF)

    def _fill_stat(self, addr: int, path: str, *, is_dir: bool, size: int = 0) -> None:
        buf = bytearray(STAT_SIZE)
        struct.pack_into("<I", buf, 0, 0x1000003)          # st_dev
        struct.pack_into("<H", buf, 4, (S_IFDIR if is_dir else S_IFREG) | 0o755)
        struct.pack_into("<H", buf, 6, 2 if is_dir else 1)  # st_nlink
        struct.pack_into("<Q", buf, 8, self._inode(path))   # st_ino
        struct.pack_into("<I", buf, 16, 501)               # st_uid
        struct.pack_into("<I", buf, 20, 20)                # st_gid
        struct.pack_into("<q", buf, 96, size)              # st_size
        struct.pack_into("<q", buf, 104, (size + 511) // 512)
        struct.pack_into("<i", buf, 112, 4096)             # st_blksize
        self.h.mem_write(addr, bytes(buf))

    # -- registration -----------------------------------------------------
    def _install(self) -> None:
        h = self.h
        h.register("open", self.open)
        h.register("close", self.close)
        h.register("read", self.read)
        h.register("write", self.write)
        h.register("lstat$INODE64", self.lstat)
        h.register("stat$INODE64", self.lstat)
        h.register("fstat$INODE64", self.fstat)
        h.register("statfs$INODE64", self.statfs)
        h.register("mkdir", self.mkdir)
        h.register("unlink", self.unlink)
        h.register("chmod", self.chmod)
        h.register("fchmod", self.fchmod)
        h.register("fcntl", self.fcntl)
        h.register("ftruncate", self.ftruncate)
        h.register("lockf", self.lockf)
        h.register("getenv", self.getenv)
        h.register("gettimeofday", self.gettimeofday)
        h.register("gethostuuid", self.gethostuuid)
        h.register("___error", self.errno_ptr)
        h.register("notify_post", lambda hh: 0)
        h.register("umask", lambda hh: 0o022)
        h.register("getuid", lambda hh: 501)
        h.register("arc4random", self.arc4random)
        h.register("arc4random_buf", self.arc4random_buf)
        h.register("NSVersionOfRunTimeLibrary", lambda hh: 0x10000_0000)
        h.register("CSBackupIsItemExcluded", lambda hh: 0)
        h.register("CSBackupSetItemExcluded", lambda hh: 1)
        h.register("CFFileSecuritySetMode", lambda hh: 1)
        h.register("CFRelease", lambda hh: 0)
        h.register("CFErrorGetCode", lambda hh: 0)
        h.register("CFErrorGetDomain", lambda hh: 0)
        h.register("CFURLCreateFromFileSystemRepresentation", self.cfurl_create)
        h.register("CFURLCopyResourcePropertyForKey", self.cfurl_copy_prop)
        h.register("CFURLSetResourcePropertyForKey", self.cfurl_set_prop)
        h.register("objc_msgSend", self.objc_msgSend)

    # -- libc -------------------------------------------------------------
    def open(self, h: "Harness") -> int:
        path = self._s(self._a(0))
        flags = self._a(1)
        self._note(f"open({path!r}, {flags:#x})")
        if path in self.files:
            if flags & O_TRUNC:
                self.files[path] = bytearray()
        elif flags & O_CREAT:
            self.files[path] = bytearray()
        elif path in self.dirs:
            return self._fail(_errno.EISDIR)
        else:
            return self._fail(_errno.ENOENT)
        fd = self.next_fd
        self.next_fd += 1
        self.fds[fd] = {"path": path, "off": 0, "flags": flags}
        return fd

    def close(self, h: "Harness") -> int:
        self.fds.pop(self._a(0), None)
        return 0

    def read(self, h: "Harness") -> int:
        fd, buf, n = self._a(0), self._a(1), self._a(2)
        info = self.fds.get(fd)
        if info is None:
            return self._fail(_errno.EBADF)
        data = self.files.get(info["path"], bytearray())
        chunk = bytes(data[info["off"]: info["off"] + n])
        self.h.mem_write(buf, chunk)
        info["off"] += len(chunk)
        return len(chunk)

    def write(self, h: "Harness") -> int:
        fd, buf, n = self._a(0), self._a(1), self._a(2)
        info = self.fds.get(fd)
        if info is None:
            return self._fail(_errno.EBADF)
        data = self.files.setdefault(info["path"], bytearray())
        payload = self.h.mem_read(buf, n)
        off = info["off"]
        if off > len(data):
            data.extend(b"\x00" * (off - len(data)))
        data[off: off + len(payload)] = payload
        info["off"] = off + len(payload)
        self._note(f"write({info['path']!r}, {n}B) -> size {len(data)}")
        return n

    def lstat(self, h: "Harness") -> int:
        path = self._s(self._a(0))
        buf = self._a(1)
        if path in self.files:
            self._fill_stat(buf, path, is_dir=False, size=len(self.files[path]))
            self._note(f"lstat({path!r}) -> file {len(self.files[path])}B")
            return 0
        if path in self.dirs:
            self._fill_stat(buf, path, is_dir=True)
            return 0
        self._note(f"lstat({path!r}) -> ENOENT")
        return self._fail(_errno.ENOENT)

    def fstat(self, h: "Harness") -> int:
        fd, buf = self._a(0), self._a(1)
        info = self.fds.get(fd)
        if info is None:
            return self._fail(_errno.EBADF)
        size = len(self.files.get(info["path"], b""))
        self._fill_stat(buf, info["path"], is_dir=False, size=size)
        return 0

    def statfs(self, h: "Harness") -> int:
        buf = self._a(1)
        raw = bytearray(STATFS_SIZE)
        struct.pack_into("<I", raw, 0, 0x1000003)  # f_bsize etc. left zero
        self.h.mem_write(buf, bytes(raw))
        return 0

    def mkdir(self, h: "Harness") -> int:
        path = self._s(self._a(0))
        self._note(f"mkdir({path!r})")
        if self._exists(path):
            return self._fail(_errno.EEXIST)
        self.dirs.add(path)
        return 0

    def unlink(self, h: "Harness") -> int:
        path = self._s(self._a(0))
        self._note(f"unlink({path!r})")
        if path in self.files:
            del self.files[path]
            return 0
        return self._fail(_errno.ENOENT)

    def chmod(self, h: "Harness") -> int:
        return 0 if self._exists(self._s(self._a(0))) else self._fail(_errno.ENOENT)

    def fchmod(self, h: "Harness") -> int:
        return 0

    def fcntl(self, h: "Harness") -> int:
        return 0

    def ftruncate(self, h: "Harness") -> int:
        fd, length = self._a(0), self._a(1)
        info = self.fds.get(fd)
        if info is None:
            return self._fail(_errno.EBADF)
        data = self.files.setdefault(info["path"], bytearray())
        del data[length:]
        data.extend(b"\x00" * (length - len(data)))
        return 0

    def lockf(self, h: "Harness") -> int:
        return 0

    def getenv(self, h: "Harness") -> int:
        name = self._s(self._a(0))
        values = {"HOME": self.home, "USER": "aditest", "TMPDIR": "/tmp/"}
        self._note(f"getenv({name!r})")
        value = values.get(name)
        if value is None:
            return 0
        addr = self.h.scratch(len(value) + 1)
        self.h.mem_write(addr, value.encode() + b"\x00")
        return addr

    def gettimeofday(self, h: "Harness") -> int:
        tv = self._a(0)
        if tv:
            # Real time by default. A frozen clock makes the whitebox OTP a constant, which Apple accepts
            # for only ~a minute after provisioning (EVIDENCE.md sections 8, 9). ADI_FROZEN_TIME=1 restores
            # the old behaviour (deterministic traces, reproducing the lease).
            now = 1700000000 if os.environ.get("ADI_FROZEN_TIME") else time.time()
            self.h.write_u64(tv, int(now))
            self.h.write_u64(tv + 8, int((now % 1) * 1_000_000))
        return 0

    def gethostuuid(self, h: "Harness") -> int:
        out = self._a(0)
        self.h.mem_write(out, self.hostuuid)
        self._note(f"gethostuuid -> {self.hostuuid.hex()}")
        return 0

    def arc4random(self, h: "Harness") -> int:
        return 0x12345678

    def arc4random_buf(self, h: "Harness") -> int:
        buf, n = self._a(0), self._a(1)
        self.h.mem_write(buf, bytes((i * 7 + 3) & 0xFF for i in range(n)))
        return 0

    # -- CoreFoundation ---------------------------------------------------
    def cfurl_create(self, h: "Harness") -> int:
        buf, length, is_dir = self._a(1), self._a(2), self._a(3)
        path = self.h.mem_read(buf, length).decode("utf-8", "replace")
        self._next_url += 0x10
        self.urls[self._next_url] = path
        self._note(f"CFURLCreate({path!r}, dir={bool(is_dir)}) -> {self._next_url:#x}")
        return self._next_url

    def _key_name(self, key: int) -> str | None:
        name = self.key_by_object.get(key)
        return None if name is None else name.lstrip("_")

    def cfurl_copy_prop(self, h: "Harness") -> int:
        url, key, out = self._a(0), self._a(1), self._a(2)
        path = self.urls.get(url, f"<{url:#x}>")
        name = self._key_name(key)
        self._note(f"CFURLGet({path!r}, {name})")
        is_dir = path in self.dirs
        true_val = self.h.read_u64(h._data_addr["_kCFBooleanTrue"])
        false_val = self.h.read_u64(h._data_addr["_kCFBooleanFalse"])
        if name == "kCFURLIsDirectoryKey":
            self.h.write_u64(out, true_val if is_dir else false_val)
            return 1
        if name == "kCFURLIsHiddenKey":
            self.h.write_u64(out, false_val)
            return 1
        if name in ("kCFURLFileSecurityKey", "kCFURLTypeIdentifierKey"):
            self.h.write_u64(out, 0x60080000)
            return 1
        return 0

    def cfurl_set_prop(self, h: "Harness") -> int:
        return 1

    def objc_msgSend(self, h: "Harness") -> int:
        sel = self.h.read_cstr(self._a(1))
        self._note(f"objc_msgSend({sel!r})")
        if sel == "processInfo":
            return self.h.object(0x100)
        if sel == "operatingSystem":
            return 0x0D
        if sel == "isOperatingSystemAtLeastVersion:":
            return 1
        return 0
''',
    'adi_run.py': r'''#!/usr/bin/env python3
"""Drive Apple's genuine Mac CoreADI whitebox under Unicorn (Linux).

Nothing about the ADI algorithm is reimplemented here: the Mach-O
``CoreADI.framework`` slice is mapped at its literal vmaddr and executed by
Unicorn, with a synthetic macOS userland (libc + CoreFoundation + a few ObjC
selectors) provided by ``stubs.MacStubs``.

The wire format between the caller and the dispatcher export
``_vdfut768ig(function_code, CoreADIParameters *)`` follows Dadoum/apple-crates
(`adi/src/core_adi.rs`, `adi/src/calls.rs`) -- the same framing the genuine
Windows/Android builds use:

    payload[0:4]   u32 big-endian encryption_type (1 = Clear)
    payload[4:8]   u32 big-endian marker (1)
    payload[8:]    bincode request message, fixed-int, big-endian
    CoreADIParameters { u8* payload; u32 input_size; u32 output_size; u32 flags; }

Pointers inside the message are serialised as their 8-byte big-endian numeric
value, so they must be real addresses *inside the emulated process*.

The dispatcher status is written to payload[0:4] as a big-endian i32; a negative
status means the operation failed and ``payload[0:4]`` holds the error code.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path



from .harness import EmulationError, Harness, MachOImage  # noqa: E402
from .stubs import MacStubs  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
COREADI = Path(
    os.environ.get("COREADI_PATH")
    or ROOT
    / "ext/itunes/mac/coreadi-pkg/rootfs/System/Library/PrivateFrameworks"
    / "CoreADI.framework/Versions/A/CoreADI.x86_64"
)

# _vdfut768ig is at a different offset in every build, so the offset is looked up from the sha256
# of the file actually loaded. A build that is not listed is refused rather than run at a wrong
# entry point; COREADI_DISPATCH=0x... overrides the lookup for trying a new one.
BUILDS = {
    "2eafc3c79c7f41a8afbfbeaaf23ee5dab5ad5bda55ec8e54dbc0ddf1d20ce630": ("iTunes 12.8.3, CoreADI 4.19 (x86_64 slice)", 0x979A0),
    "6fe4b27f2d75b5f365917a92389bed75542f3ba08197f136262be3b34d19cb5c": ("macOS 15.8.1 24H32 (fat file)", 0x17BF60),
}


def identify_build(data: bytes) -> tuple[str, int]:
    """(name, dispatcher offset) for a CoreADI image; raises if the build is unknown."""
    digest = hashlib.sha256(data).hexdigest()
    override = os.environ.get("COREADI_DISPATCH")
    if override:
        return BUILDS.get(digest, ("unlisted build", 0))[0], int(override, 0)
    if digest not in BUILDS:
        raise EmulationError(f"unknown CoreADI build sha256 {digest}; set COREADI_DISPATCH to its _vdfut768ig offset")
    return BUILDS[digest]


# Function codes (Dadoum/apple-crates, `adi/src/calls.rs`).
MAGIC = {
    "Initialize": 0x12DB31C5,
    "TearDown": 0x08C0FE9E,
    "IsMachineProvisioned": 0xB0EDA7AF,
    "GetAllProvisionedAccounts": 0x72096FE6,
    "ProvisioningStart": 0x716BD86C,
    "ProvisioningEnd": 0x0B2B3196,
    "SessionDestroy": 0x55A637C0,
    "SetIDMSRouting": 0x632B8D6E,
    "GetIDMSRouting": 0x85FE63B0,
    "Synchronize": 0xA54951EC,
    "Erase": 0x7715488C,
    "RequestOTP": 0xCFE0B46A,
    "StorageDispose": 0x3E58E7F9,
    "AccountsDispose": 0x9679D4B5,
    "Gen2FACode": 0x385B2CE8,
    # Android-only (present here only to confirm they are *absent* on macOS).
    "SetAndroidID": 0xC774D292,
    "SetProvisioningPath": 0xB23C691E,
}

# Known dispatcher/operation error codes.
ERR_NOT_PROVISIONED = -45061
ERR_GENERIC = -45002


def w32(value: int) -> bytes:
    return struct.pack(">I", value & 0xFFFFFFFF)


def w64(value: int) -> bytes:
    return struct.pack(">Q", value & 0xFFFFFFFFFFFFFFFF)


def wi64(value: int) -> bytes:
    return struct.pack(">q", value)


def s32(value: int) -> int:
    return value - 0x1_0000_0000 if value >= 0x8000_0000 else value


@dataclass
class Result:
    name: str
    rc: int
    ret: int
    outputs: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.rc >= 0 and self.ret >= 0

    def __str__(self) -> str:
        status = "ok " if self.ok else "ERR"
        out = " ".join(f"{k}={v}" for k, v in self.outputs.items())
        return f"{self.name:24} {status} rc={self.rc:>7} ret={self.ret:>7} {out}".rstrip()


class CoreADI:
    """A live Mac ADI dispatcher running on a synthetic macOS."""

    def __init__(self, path: Path = COREADI, *, log: bool = False) -> None:
        image = MachOImage(str(path))
        self.build, self.dispatch = identify_build(image.data)
        self.harness = Harness(image)
        self.stubs = MacStubs(self.harness, log=log)
        self.last_insns = 0

    # -- low level --------------------------------------------------------
    def _dispatch(self, name: str, message: bytes) -> tuple[int, int, int]:
        h = self.harness
        buf = bytearray(max(0x800, 8 + len(message)))
        buf[3] = 1  # encryption_type = Clear
        buf[7] = 1  # marker = 1
        buf[8 : 8 + len(message)] = message
        buf_addr = h.scratch(len(buf))
        h.mem_write(buf_addr, bytes(buf))

        params = h.scratch(0x20)
        h.mem_write(params, b"\x00" * 0x20)
        h.write_u64(params + 0x00, buf_addr)
        h.write_u32(params + 0x08, 8 + len(message))
        h.write_u32(params + 0x0C, 4)
        h.write_u32(params + 0x10, 0)

        rc = s32(h.invoke(self.dispatch, [MAGIC[name], params]))
        ret = struct.unpack(">i", h.mem_read(buf_addr, 4))[0]
        h.mem_write(buf_addr + 4, b"\x00" * 4)
        return rc, ret, buf_addr

    def _out_ptr(self, value: int = 0) -> int:
        """A fresh 8-byte cell whose address can be handed to the dispatcher."""
        addr = self.harness.scratch(8)
        self.harness.write_u64(addr, value)
        return addr

    def _out_u32(self, value: int = 0) -> int:
        addr = self.harness.scratch(8)
        self.harness.write_u32(addr, value)
        return addr

    def _read_u64(self, addr: int) -> int:
        return self.harness.read_u64(addr)

    def _read_u32(self, addr: int) -> int:
        return self.harness.read_u32(addr)

    def _slice(self, ptr_addr: int, len_addr: int) -> bytes:
        ptr = self._read_u64(ptr_addr)
        length = self._read_u32(len_addr)
        if not ptr or not length:
            return b""
        return bytes(self.harness.mem_read(ptr, length))

    # -- operations -------------------------------------------------------
    def initialize(self) -> Result:
        rc, ret, _ = self._dispatch("Initialize", b"")
        return Result("Initialize", rc, ret)

    def teardown(self) -> Result:
        rc, ret, _ = self._dispatch("TearDown", b"")
        return Result("TearDown", rc, ret)

    def is_machine_provisioned(self, ds_id: int) -> Result:
        rc, ret, _ = self._dispatch("IsMachineProvisioned", wi64(ds_id))
        return Result("IsMachineProvisioned", rc, ret, {"ds_id": ds_id})

    def get_all_provisioned_accounts(self) -> Result:
        list_ptr = self._out_ptr()
        list_len = self._out_u32()
        rc, ret, _ = self._dispatch(
            "GetAllProvisionedAccounts", w64(list_ptr) + w64(list_len)
        )
        return Result("GetAllProvisionedAccounts", rc, ret)

    def request_otp(self, ds_id: int) -> Result:
        mid_ptr, mid_len = self._out_ptr(), self._out_u32()
        otp_ptr, otp_len = self._out_ptr(), self._out_u32()
        rc, ret, _ = self._dispatch(
            "RequestOTP",
            wi64(ds_id)
            + w64(mid_ptr)
            + w64(mid_len)
            + w64(otp_ptr)
            + w64(otp_len),
        )
        mid_n, otp_n = self._read_u32(mid_len), self._read_u32(otp_len)
        mid = self._slice(mid_ptr, mid_len)
        otp = self._slice(otp_ptr, otp_len)
        # The library hands back pointers into its own storage; release them so
        # repeated calls in one process do not accumulate.
        if mid and otp:
            self.storage_dispose(self._read_u64(mid_ptr))
        return Result(
            "RequestOTP",
            rc,
            ret,
            {
                "mid_len": mid_n,
                "otp_len": otp_n,
                "mid": mid,
                "otp": otp,
            },
        )

    def provisioning_start(self, ds_id: int, spim: bytes = b"") -> Result:
        spim_buf = self.harness.scratch(max(len(spim), 16))
        if spim:
            self.harness.mem_write(spim_buf, spim)
        cpim_ptr, cpim_len = self._out_ptr(), self._out_u32()
        session = self._out_u32()
        rc, ret, _ = self._dispatch(
            "ProvisioningStart",
            wi64(ds_id)
            + w64(spim_buf)
            + w32(len(spim))
            + w64(cpim_ptr)
            + w64(cpim_len)
            + w64(session),
        )
        return Result(
            "ProvisioningStart",
            rc,
            ret,
            {
                "spim_len": len(spim),
                "cpim_len": self._read_u32(cpim_len),
                "session": self._read_u32(session),
                "cpim": self._slice(cpim_ptr, cpim_len),
                "session_id": self._read_u32(session),
            },
        )

    def provisioning_end(self, session: int, ptm: bytes, tk: bytes) -> Result:
        ptm_buf = self.harness.scratch(max(len(ptm), 16))
        if ptm:
            self.harness.mem_write(ptm_buf, ptm)
        tk_buf = self.harness.scratch(max(len(tk), 16))
        if tk:
            self.harness.mem_write(tk_buf, tk)
        rc, ret, _ = self._dispatch(
            "ProvisioningEnd",
            w32(session)
            + w64(ptm_buf)
            + w32(len(ptm))
            + w64(tk_buf)
            + w32(len(tk)),
        )
        return Result(
            "ProvisioningEnd",
            rc,
            ret,
            {"session": session, "ptm_len": len(ptm), "tk_len": len(tk)},
        )

    def synchronize(self, ds_id: int, sim: bytes) -> Result:
        sim_buf = self.harness.scratch(max(len(sim), 16))
        if sim:
            self.harness.mem_write(sim_buf, sim)
        mid_ptr, mid_len = self._out_ptr(), self._out_u32()
        srm_ptr, srm_len = self._out_ptr(), self._out_u32()
        rc, ret, _ = self._dispatch(
            "Synchronize",
            wi64(ds_id)
            + w64(sim_buf)
            + w32(len(sim))
            + w64(mid_ptr)
            + w64(mid_len)
            + w64(srm_ptr)
            + w64(srm_len),
        )
        return Result(
            "Synchronize",
            rc,
            ret,
            {
                "mid_len": self._read_u32(mid_len),
                "srm_len": self._read_u32(srm_len),
                "mid": self._slice(mid_ptr, mid_len),
                "srm": self._slice(srm_ptr, srm_len),
            },
        )

    def storage_dispose(self, ptr: int) -> Result:
        rc, ret, _ = self._dispatch("StorageDispose", w64(ptr))
        return Result("StorageDispose", rc, ret)

    def erase(self, ds_id: int) -> Result:
        rc, ret, _ = self._dispatch("Erase", wi64(ds_id))
        return Result("Erase", rc, ret)

    def set_routing(self, ds_id: int, routing: int) -> Result:
        rc, ret, _ = self._dispatch("SetIDMSRouting", wi64(ds_id) + w64(routing))
        return Result("SetIDMSRouting", rc, ret, {"routing": routing})

    def get_routing(self, ds_id: int) -> Result:
        route = self._out_ptr()
        rc, ret, _ = self._dispatch("GetIDMSRouting", wi64(ds_id) + w64(route))
        return Result("GetIDMSRouting", rc, ret, {"routing": self._read_u64(route)})

    def gen_2fa(self, ds_id: int) -> Result:
        code = self._out_u32()
        rc, ret, _ = self._dispatch("Gen2FACode", wi64(ds_id) + w64(code))
        return Result("Gen2FACode", rc, ret, {"code": self._read_u32(code)})

    # -- convenience ------------------------------------------------------
    def __enter__(self) -> CoreADI:
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            self.teardown()
        except EmulationError:
            pass


def _probe(args: argparse.Namespace) -> int:
    adi = CoreADI(log=args.log)
    ds_id = args.ds_id
    steps = [
        adi.initialize,
        lambda: adi.is_machine_provisioned(ds_id),
        lambda: adi.get_all_provisioned_accounts(),
        lambda: adi.get_routing(ds_id),
        lambda: adi.request_otp(ds_id),
        lambda: adi.provisioning_start(ds_id),
        lambda: adi.gen_2fa(ds_id),
        adi.teardown,
    ]
    for step in steps:
        try:
            print(step())
        except EmulationError as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ds-id", type=int, default=-2, help="DSID (Grand Slam uses -2)")
    ap.add_argument("--log", action="store_true", help="log the synthetic syscalls")
    return _probe(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
''',
    'LICENSE': r'''MIT License

Copyright (c) 2026 sacca

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
''',
}


# ════════════════════════════════════════════════════════════════════════════
#  Apple-Konto
# ════════════════════════════════════════════════════════════════════════════

class Apple:
    def __init__(self, st: "State") -> None:
        self.st = st
        self.account: Any = None
        self.methods: list[Any] = []
        self.path = DATA_DIR / "apple_account.json"
        self.error: str | None = None
        self.lock = asyncio.Lock()
        self.runtime = AppleRuntime()

    def _provider(self) -> Any:
        from findmy import LocalAnisetteProvider
        if (self.st.store.settings().get("anisette_server") or "").strip():
            # Anisette-Server liefern eine Android-Identität – die lehnt Apple seit Okt. 2026 ab.
            log.info("Anisette-Server wird ignoriert: Apple verlangt eine macOS-Identität.")
        return LocalAnisetteProvider()

    def _need_runtime(self) -> None:
        if self.runtime.check():
            return
        if self.runtime.state == "missing":
            self.runtime.start_install()
        if self.runtime.state == "installing":
            raise ValueError(f"Die macOS-Komponente für die Apple-Anmeldung wird gerade eingerichtet "
                             f"({int(self.runtime.progress * 100)} %). Bitte in ein paar Minuten erneut anmelden.")
        raise ValueError(self.runtime.message or "macOS-Komponente für die Apple-Anmeldung fehlt.")

    async def restore(self) -> None:
        from findmy import AsyncAppleAccount, LoginState
        if not self.runtime.check() and self.runtime.state == "missing":
            self.runtime.start_install()
        if not self.path.exists():
            return
        if not apple_session_is_mac(self.path):
            # Alte Android-Sitzung: liefert keine Standorte mehr → einmal neu anmelden
            self.error = ("Apple hat die Anmeldung im Oktober 2026 umgestellt. Bitte einmal neu anmelden "
                          "(Objekte, Schlüssel und Verlauf bleiben erhalten).")
            log.warning("Gespeicherte Apple-Sitzung nutzt die alte Android-Identität – neue Anmeldung nötig.")
            return
        if self.runtime.state != "ready":
            self.error = "Apple-Sitzung wartet auf die macOS-Komponente …"
            return
        try:
            acc = AsyncAppleAccount.from_json(self.path)
            acc._http = apple_http_session(acc._anisette)
            if acc.login_state == LoginState.LOGGED_IN:
                self.account = acc
                self.error = None
                log.info("Apple-Konto wiederhergestellt: %s", acc.account_name)
            else:
                await acc.close()
        except Exception as e:  # noqa: BLE001
            log.warning("Gespeicherte Apple-Sitzung unbrauchbar: %s", e)
            self.error = "Gespeicherte Apple-Sitzung unbrauchbar – bitte neu anmelden."

    @property
    def logged_in(self) -> bool:
        from findmy import LoginState
        return self.account is not None and self.account.login_state == LoginState.LOGGED_IN

    def status(self) -> dict:
        if self.account is None:
            return {"state": "logged_out", "error": self.error, "runtime": self.runtime.status()}
        from findmy import LoginState
        s = self.account.login_state
        out: dict = {"state": {LoginState.LOGGED_OUT: "logged_out", LoginState.REQUIRE_2FA: "require_2fa",
                               LoginState.AUTHENTICATED: "authenticated",
                               LoginState.LOGGED_IN: "logged_in"}[s], "error": self.error,
                     "runtime": self.runtime.status()}
        if s == LoginState.LOGGED_IN:
            with contextlib.suppress(Exception):
                out.update(account_name=self.account.account_name, first_name=self.account.first_name,
                           last_name=self.account.last_name)
        if s == LoginState.REQUIRE_2FA:
            out["methods"] = self.describe_methods()
        return out

    def describe_methods(self) -> list[dict]:
        from findmy import SmsSecondFactorMethod, TrustedDeviceSecondFactorMethod
        out = []
        for i, m in enumerate(self.methods):
            if isinstance(m, TrustedDeviceSecondFactorMethod):
                out.append({"index": i, "type": "trusted_device", "label": "Vertrauenswürdiges Gerät"})
            elif isinstance(m, SmsSecondFactorMethod):
                out.append({"index": i, "type": "sms", "label": f"SMS an {m.phone_number}",
                            "phone": m.phone_number})
            else:
                out.append({"index": i, "type": "other", "label": type(m).__name__})
        return out

    def save(self) -> None:
        if self.account is not None:
            with contextlib.suppress(Exception):
                self.account.to_json(self.path)
                os.chmod(self.path, 0o600)

    async def login(self, email: str, password: str) -> dict:
        from findmy import AsyncAppleAccount, LoginState
        async with self.lock:
            if self.account is not None:
                with contextlib.suppress(Exception):
                    await self.account.close()
            self.account, self.methods, self.error = None, [], None
            self._need_runtime()
            provider = self._provider()
            acc = AsyncAppleAccount(anisette=provider)
            acc._http = apple_http_session(provider)
            try:
                state = await acc.login(email.strip(), password)
            except Exception as e:  # noqa: BLE001
                with contextlib.suppress(Exception):
                    await acc.close()
                self.error = f"Anmeldung fehlgeschlagen: {e}"
                raise
            self.account = acc
            if state == LoginState.REQUIRE_2FA:
                self.methods = list(await acc.get_2fa_methods())
                # Vertrauenswürdige Geräte bekommen den Code meist automatisch – trotzdem anfordern
            elif state == LoginState.LOGGED_IN:
                self._finish()
            return self.status()

    def _finish(self) -> None:
        """Nach erfolgreicher Anmeldung: Ortungs-Token prüfen und Sitzung speichern."""
        self.methods = []
        if not apple_has_search_token(self.account):
            self.error = ("Angemeldet, aber Apple hat keinen Ortungs-Token geliefert. Bitte später erneut "
                          "anmelden – sonst können keine Standorte abgerufen werden.")
            log.warning("Apple-Anmeldung ohne searchPartyToken.")
        else:
            self.error = None
        self.save()

    async def request_code(self, index: int) -> None:
        await self.methods[index].request()

    async def submit_code(self, index: int, code: str) -> dict:
        from findmy import LoginState
        async with self.lock:
            state = await self.methods[index].submit(code.strip())
            if state == LoginState.LOGGED_IN:
                self._finish()
                self.st.wake(full=True)
            return self.status()

    async def logout(self) -> None:
        async with self.lock:
            if self.account is not None:
                with contextlib.suppress(Exception):
                    await self.account.close()
            self.account, self.methods, self.error = None, [], None
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()


# ════════════════════════════════════════════════════════════════════════════
#  Geräte (Schlüssel) & Abruf
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class Tracked:
    id: str
    accessory: Any
    last_quick: float = 0.0
    last_day: float = 0.0
    last_full: float = 0.0
    align_saved: tuple = ()
    errors: int = 0


def accessory_id(acc: Any) -> str:
    """Stabile, URL-sichere ID (Apple-Identifier enthalten z. B. „~#“)."""
    ident = getattr(acc, "identifier", None)
    if ident:
        return hashlib.sha1(str(ident).encode()).hexdigest()[:20]
    mk = getattr(acc, "master_key", None)
    if mk:
        return hashlib.sha1(mk).hexdigest()[:20]
    return hashlib.sha1(repr(acc).encode()).hexdigest()[:20]


def alignment_of(acc: Any) -> tuple:
    d = getattr(acc, "_alignment_date", None)
    return (d.timestamp() if d else 0.0, getattr(acc, "_alignment_index", 0) or 0)


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", s)[:120]


def parse_key_file(raw: bytes, filename: str = "") -> list[tuple[Any, dict]]:
    """Gibt [(accessory, meta)] zurück. Unterstützt FindMy.py-JSON (auch Listen) und .plist."""
    from findmy import FindMyAccessory, FixedRollingKeyPairAccessory

    out: list[tuple[Any, dict]] = []
    text = raw.lstrip()
    if text[:1] in (b"{", b"["):
        data = json.loads(raw.decode("utf-8-sig"))
        items = data if isinstance(data, list) else [data]
        for it in items:
            if not isinstance(it, dict):
                continue
            typ = it.get("type")
            meta = {"emoji": it.get("emoji"), "name": it.get("name")}
            if typ == "accessory":
                out.append((FindMyAccessory.from_json(it), meta))
            elif typ == "custom_rolling_key_accessory":
                out.append((FixedRollingKeyPairAccessory.from_json(it), meta))
            elif "privateKey" in it or "master_key" in it:
                raise ValueError("Unbekanntes JSON-Format")
        if not out:
            raise ValueError("Keine Zubehör-Schlüssel im JSON gefunden (type=accessory)")
        return out
    pl = plistlib.loads(raw)
    if isinstance(pl, dict) and "privateKey" in pl:
        name = pl.get("name") or Path(filename).stem or None
        out.append((FindMyAccessory.from_plist(pl, name=name), {"name": name}))
        return out
    raise ValueError("Datei ist weder FindMy.py-JSON noch entschlüsselte .plist")


class Registry:
    """Hält alle Zubehör-Schlüssel (data/accessories/*.json)."""

    def __init__(self, st: "State") -> None:
        self.st = st
        self.dir = DATA_DIR / "accessories"
        self.tracked: dict[str, Tracked] = {}

    def load(self) -> None:
        from findmy import FindMyAccessory, FixedRollingKeyPairAccessory
        self.dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self.dir, 0o700)
        for p in sorted(self.dir.glob("*.json")):
            try:
                data = json.loads(p.read_text("utf-8"))
                acc = (FindMyAccessory.from_json(data) if data.get("type") == "accessory"
                       else FixedRollingKeyPairAccessory.from_json(data))
            except Exception as e:  # noqa: BLE001
                log.warning("Schlüssel %s nicht lesbar: %s", p.name, e)
                continue
            did = accessory_id(acc)
            self.tracked[did] = Tracked(did, acc, align_saved=alignment_of(acc))
            if not self.st.store.device_row(did):
                self.st.store.upsert_device(did, acc.name or getattr(acc, "model", None) or did[:8],
                                            getattr(acc, "model", None), data.get("emoji"),
                                            getattr(acc, "serial_number", None), self._kind(acc))
        log.info("%d Gerät(e) mit Schlüsseln geladen.", len(self.tracked))

    @staticmethod
    def _kind(acc: Any) -> str:
        m = (getattr(acc, "model", None) or "").lower()
        if "airtag" in m or m == "":
            return "airtag" if type(acc).__name__ == "FindMyAccessory" else "custom"
        return "accessory"

    def save(self, t: Tracked, emoji: str | None = None) -> None:
        data = t.accessory.to_json()
        if emoji:
            data["emoji"] = emoji
        else:
            p = self.dir / f"{safe_name(t.id)}.json"
            if p.exists():
                with contextlib.suppress(Exception):
                    old = json.loads(p.read_text("utf-8"))
                    if old.get("emoji"):
                        data["emoji"] = old["emoji"]
        secure_write(self.dir / f"{safe_name(t.id)}.json", json.dumps(data, indent=2, ensure_ascii=False))
        t.align_saved = alignment_of(t.accessory)

    def save_changed(self) -> None:
        for t in self.tracked.values():
            if alignment_of(t.accessory) != t.align_saved:
                self.save(t)

    def import_bytes(self, raw: bytes, filename: str = "", category: str = "item") -> list[dict]:
        added = []
        for acc, meta in parse_key_file(raw, filename):
            did = accessory_id(acc)
            existing = self.tracked.get(did)
            if existing and alignment_of(existing.accessory) > alignment_of(acc):
                acc = existing.accessory  # neuere Ausrichtung behalten
            t = existing or Tracked(did, acc)
            t.accessory = acc
            t.last_quick = t.last_day = t.last_full = 0.0
            self.tracked[did] = t
            self.save(t, emoji=meta.get("emoji"))
            name = meta.get("name") or acc.name or getattr(acc, "model", None) or did[:8]
            new = not self.st.store.device_row(did)
            self.st.store.upsert_device(did, name, getattr(acc, "model", None), meta.get("emoji"),
                                        getattr(acc, "serial_number", None), self._kind(acc))
            if not new and meta.get("emoji"):
                self.st.store.update_device(did, emoji=meta["emoji"])
            if category != "item":
                row = self.st.store.device_row(did)
                alerts = row["alerts"] if row else copy.deepcopy(DEFAULT_ALERTS)
                if new:
                    alerts["battery"]["enabled"] = False  # Statusbyte bei Apple-Geräten nicht aussagekräftig
                self.st.store.update_device(did, category=category, alerts=alerts)
            added.append({"id": did, "name": name, "new": new})
        return added

    def remove(self, did: str) -> None:
        self.tracked.pop(did, None)
        with contextlib.suppress(FileNotFoundError):
            (self.dir / f"{safe_name(did)}.json").unlink()


def report_to_dict(rep: Any) -> dict:
    status = rep.status
    return {"ts": round(rep.timestamp.timestamp(), 3), "lat": round(rep.latitude, 7),
            "lon": round(rep.longitude, 7), "accuracy": rep.horizontal_accuracy,
            "confidence": rep.confidence, "status": status,
            "battery": BATTERY.get((status >> 6) & 0b11) if status is not None else None}


async def fetch_combined(account: Any, plan: list[tuple[Tracked, int, int]]) -> tuple[dict[str, list], int, int]:
    """
    Fragt die Schlüssel ALLER geplanten Geräte/Fenster gebündelt ab.
    Jede Anfrage enthält bis zu CHUNKS_PER_REQUEST Blöcke à max. 290 primäre und
    290 sekundäre Schlüssel – dadurch weniger Anfragen und schnellere Zyklen.
    Gibt ({device_id: [LocationReport]}, anzahl_schlüssel, anzahl_anfragen) zurück.
    """
    from findmy import KeyPairType
    from findmy.errors import EmptyResponseError

    id_map: dict[bytes, tuple[Tracked, Any]] = {}
    key_ind: dict[tuple[str, Any], set[int]] = {}
    chunks: list[tuple[list[str], list[str]]] = []
    for t, hi, lo in plan:
        prim: set[str] = set()
        sec: set[str] = set()
        for ind in range(hi, lo - 1, -1):
            batch = t.accessory.keys_at(ind)
            np_ = {k.hashed_adv_key_b64 for k in batch if k.key_type == KeyPairType.PRIMARY}
            ns_ = {k.hashed_adv_key_b64 for k in batch if k.key_type != KeyPairType.PRIMARY}
            if len(prim | np_) > MAX_KEYS_PER_CHUNK or len(sec | ns_) > MAX_KEYS_PER_CHUNK:
                chunks.append((list(prim), list(sec)))
                prim, sec = set(), set()
            for k in batch:
                key_ind.setdefault((t.id, k), set()).add(ind)
                id_map[k.hashed_adv_key_bytes] = (t, k)
            prim |= np_
            sec |= ns_
        if prim or sec:
            chunks.append((list(prim), list(sec)))

    results: dict[str, list] = {t.id: [] for t, _, _ in plan}
    requests = 0
    for i in range(0, len(chunks), CHUNKS_PER_REQUEST):
        group = chunks[i:i + CHUNKS_PER_REQUEST]
        requests += 1
        try:
            raw = await asyncio.wait_for(account.fetch_raw_reports(group), timeout=120)
        except EmptyResponseError:
            raw = []
        for rep in raw:
            hit = id_map.get(rep.hashed_adv_key_bytes)
            if not hit:
                continue
            t, k = hit
            try:
                rep.decrypt(k)
            except Exception:  # noqa: BLE001
                continue
            for ind in sorted(key_ind.get((t.id, k), ()), reverse=True):
                with contextlib.suppress(Exception):
                    t.accessory.update_alignment(rep.timestamp, ind)
            results[t.id].append(rep)
        if i + CHUNKS_PER_REQUEST < len(chunks):
            await asyncio.sleep(0.25)
    return results, len(id_map), requests


def index_range(acc: Any, mode: str, quick_hours: float) -> tuple[int, int]:
    end = dt.datetime.now(dt.timezone.utc)
    hi = acc.get_max_index(end)
    align_idx = alignment_of(acc)[1]
    if mode == "full":
        span = 7 * 96
        drift = max(96, (hi - align_idx) // 50)  # ~2 % Toleranz bei veralteter Ausrichtung
    else:
        hours = 24 if mode == "day" else max(1.0, quick_hours)
        span = int(hours * 4) + 1
        drift = 16
    lo = max(acc.get_min_index(end - dt.timedelta(days=7)), hi - span - drift, 0)
    return hi, lo


# ════════════════════════════════════════════════════════════════════════════
#  Benachrichtigungen (Bark) & Alarme
# ════════════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════════════
#  Apple-Geräte: Online-Ortung (iCloud „Wo ist?“) + Offline (AirTag-Schlüssel)
# ════════════════════════════════════════════════════════════════════════════

AIRPODS_ROLES = ("left", "right", "case")


class OnlineDevices:
    """
    Online-Ortung der Apple-Geräte über den Web-Dienst von iCloud.com („Geräte suchen“)
    mit der Bibliothek pyicloud (wird bei Bedarf automatisch installiert).

    * Einmalig verbinden: Apple-ID + Passwort (Standard: aus der Apple-Anmeldung des Servers),
      dann 2FA-Code bestätigen. Danach bleibt die Sitzung über Cookies vertrauenswürdig
      (data/icloud), ohne dass das Passwort erneut gesendet werden muss.
    * Schutz vor Konto-Sperren: Das Passwort wird nie automatisch wiederholt gesendet;
      nach Fehlern wird die Abfrage stark gedrosselt.
    """

    MIN_INTERVAL = 30

    def __init__(self, st: "State") -> None:
        self.st = st
        self.api: Any = None
        self.state = "disconnected"        # disconnected | needs_2fa | connected | connecting
        self.account: str | None = st.store.kv_get("icloud_account")
        self.delivery: str | None = None   # trusted_device | sms
        self.error: str | None = None
        self.last_refresh: float | None = None
        self.last_attempt = 0.0
        self.failures = 0
        self.event = asyncio.Event()
        self.lock = asyncio.Lock()
        self.cookie_dir = DATA_DIR / "icloud"

    # --- Status -------------------------------------------------------------------
    def status(self) -> dict:
        cfg = self.st.store.settings()["online_devices"]
        return {"enabled": bool(cfg.get("enabled")), "interval": cfg.get("interval"),
                "state": self.state, "account": self.account, "delivery": self.delivery,
                "error": self.error, "last_refresh": self.last_refresh}

    def _publish(self) -> None:
        self.st.hub.publish("apple_devices", {"changed": True})

    # --- pyicloud laden ------------------------------------------------------------
    @staticmethod
    def _ensure_lib() -> Any:
        try:
            import pyicloud  # noqa: F401
        except ImportError:
            log.info("Installiere pyicloud (einmalig) …")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--prefer-binary", "pyicloud"],
                           check=True, capture_output=True, timeout=600)
        from pyicloud import PyiCloudService
        return PyiCloudService

    def _default_creds(self) -> tuple[str | None, str | None]:
        acc = getattr(self.st.apple, "account", None)
        return getattr(acc, "_username", None), getattr(acc, "_password", None)

    # --- Verbinden (einmalig mit 2FA) ---------------------------------------------
    async def connect(self, apple_id: str | None = None, password: str | None = None) -> dict:
        if self.st.args.demo:
            raise ValueError("Im Demo-Modus nicht verfügbar")
        uid, pw = self._default_creds()
        apple_id = (apple_id or uid or "").strip()
        password = password or pw
        if not apple_id or not password:
            raise ValueError("Apple-ID und Passwort angeben (oder zuerst den Apple-Account im Server anmelden).")
        async with self.lock:
            self.state, self.error = "connecting", None
            self._publish()
            try:
                svc = await asyncio.to_thread(self._ensure_lib)
                self.cookie_dir.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(OSError):
                    os.chmod(self.cookie_dir, 0o700)
                api = await asyncio.to_thread(lambda: svc(apple_id, password, cookie_directory=str(self.cookie_dir),
                                                          refresh_interval=None, with_family=True))
                self.api, self.account = api, apple_id
                self.st.store.kv_set("icloud_account", apple_id)
                if api.requires_2fa:
                    self.state = "needs_2fa"
                    try:
                        await asyncio.to_thread(api.request_2fa_code)
                        self.delivery = getattr(api, "two_factor_delivery_method", None)
                    except Exception as e:  # noqa: BLE001
                        log.info("2FA-Anforderung: %s – ein bereits angezeigter Code funktioniert trotzdem.", e)
                        with contextlib.suppress(Exception):
                            api.use_existing_trusted_device_code()
                else:
                    await self._finish()
            except Exception as e:  # noqa: BLE001
                self.api, self.state = None, "disconnected"
                self.error = self._friendly(e)
                log.warning("iCloud-Verbindung fehlgeschlagen: %s", e)
            self._publish()
            return self.status()

    async def request_sms(self) -> dict:
        if not self.api:
            raise ValueError("Zuerst verbinden")
        await asyncio.to_thread(self.api._request_sms_2fa_code)
        self.delivery = "sms"
        return self.status()

    async def submit_code(self, code: str) -> dict:
        if not self.api or self.state != "needs_2fa":
            raise ValueError("Keine 2FA-Anfrage offen – bitte erneut verbinden.")
        async with self.lock:
            ok = await asyncio.to_thread(self.api.validate_2fa_code, code.strip())
            if not ok:
                self.error = "Code falsch – bitte erneut eingeben."
                return self.status()
            if not self.api.is_trusted_session:
                await asyncio.to_thread(self.api.trust_session)
            await self._finish()
            self._publish()
            return self.status()

    async def _finish(self) -> None:
        self.state, self.error, self.failures, self.delivery = "connected", None, 0, None
        log.info("iCloud-Online-Ortung verbunden (%s).", self.account)
        self.event.set()

    async def disconnect(self) -> None:
        async with self.lock:
            self.api, self.state, self.error = None, "disconnected", None
            import shutil
            shutil.rmtree(self.cookie_dir, ignore_errors=True)
            self.st.store.kv_set("icloud_account", None)
            self.account = None
            self._publish()

    async def resume(self) -> None:
        """Beim Start: vertrauenswürdige Sitzung aus den Cookies wiederverwenden (ohne 2FA)."""
        if self.st.args.demo or not self.account or not self.cookie_dir.exists():
            return
        uid, pw = self._default_creds()
        if not pw or (uid and uid.lower() != self.account.lower()):
            self.error = "Bitte Online-Ortung einmal neu verbinden."
            return
        try:
            svc = await asyncio.to_thread(self._ensure_lib)
            api = await asyncio.to_thread(lambda: svc(self.account, pw, cookie_directory=str(self.cookie_dir),
                                                      refresh_interval=None, with_family=True))
            if api.requires_2fa:
                self.state, self.error = "disconnected", "Sitzung abgelaufen – bitte Online-Ortung neu verbinden (2FA)."
                return
            self.api = api
            await self._finish()
        except Exception as e:  # noqa: BLE001
            self.state, self.error = "disconnected", self._friendly(e)
            log.warning("iCloud-Sitzung nicht wiederherstellbar: %s", e)

    # --- Abfrage --------------------------------------------------------------------
    @staticmethod
    def _parse(d: dict) -> dict:
        loc = d.get("location") or None
        online = None
        if loc and loc.get("latitude") is not None:
            online = {"lat": round(float(loc["latitude"]), 7), "lon": round(float(loc["longitude"]), 7),
                      "accuracy": round(float(loc.get("horizontalAccuracy") or 0)),
                      "ts": float(loc.get("timeStamp") or 0) / 1000.0,
                      "position_type": loc.get("positionType"), "is_old": bool(loc.get("isOld")),
                      "inaccurate": bool(loc.get("isInaccurate"))}
        bl = d.get("batteryLevel")
        feats = d.get("features") or {}
        lost = d.get("lostDevice") or {}
        extra = {
            "low_power_mode": d.get("lowPowerMode"),
            "battery_status": d.get("batteryStatus"),
            "altitude": (loc or {}).get("altitude"),
            "vertical_accuracy": (loc or {}).get("verticalAccuracy"),
            "floor_level": (loc or {}).get("floorLevel"),
            "position_type": (loc or {}).get("positionType"),
            "location_enabled": d.get("locationEnabled"),
            "is_locating": d.get("isLocating"),
            "lost_mode_capable": d.get("lostModeCapable"),
            "lost_mode_enabled": d.get("lostModeEnabled"),
            "lost_message": lost.get("text") if isinstance(lost, dict) else None,
            "lost_number": lost.get("ownerNbr") if isinstance(lost, dict) else None,
            "activation_locked": d.get("activationLocked"),
            "can_sound": bool(feats.get("SND")), "can_message": bool(feats.get("MSG")),
            "can_locate": bool(feats.get("LOC")), "can_lost": bool(d.get("lostModeCapable")),
            "device_color": d.get("deviceColor"),
            "model_display_name": d.get("modelDisplayName"),
            "prs_id": d.get("prsId"),
            "audio_channels": [
                {"name": c.get("name"), "available": c.get("available"), "playing": c.get("playing"),
                 "muted": c.get("muted")} for c in (d.get("audioChannels") or []) if isinstance(c, dict)],
        }
        return {"extra": extra, "raw": OnlineDevices._sanitize(d),
                "id": str(d.get("id")), "name": d.get("name") or d.get("deviceDisplayName") or "Gerät",
                "model": d.get("rawDeviceModel") or d.get("deviceModel"),
                "display_name": d.get("deviceDisplayName"), "device_class": d.get("deviceClass"),
                "battery_level": float(bl) if isinstance(bl, (int, float)) and bl > 0 else None,
                "battery_status": d.get("batteryStatus"), "device_status": str(d.get("deviceStatus") or ""),
                "online": online}

    SENSITIVE = ("id", "baUUID", "deviceDiscoveryId", "prsId", "token", "Token", "passcode", "mesg",
                 "snd", "msg", "lostDevice", "wipedTimestamp", "encodedDeviceId", "commandLookupId")

    @staticmethod
    def _sanitize(v: Any, key: str = "") -> Any:
        """Rohdaten ohne IDs/Tokens (zur Anzeige in der App)."""
        if isinstance(v, dict):
            return {k: ("•••" if any(s in k for s in OnlineDevices.SENSITIVE) and not isinstance(x, (bool, int, float))
                        else OnlineDevices._sanitize(x, k)) for k, x in v.items()}
        if isinstance(v, list):
            return [OnlineDevices._sanitize(x, key) for x in v]
        return v

    def _fetch(self) -> list[dict]:
        mgr = self.api.devices
        mgr.refresh(locate=True)
        members = {}
        with contextlib.suppress(Exception):
            ui = mgr.user_info or {}
            for pid, m in (ui.get("membersInfo") or {}).items():
                members[str(pid)] = " ".join(x for x in (m.get("firstName"), m.get("lastName")) if x)
        out = []
        for dev in mgr:
            item = self._parse(dict(dev.data))
            pid = item["extra"].pop("prs_id", None)
            item["extra"]["owner"] = members.get(str(pid)) if pid else None
            item["extra"]["family"] = bool(pid and members and str(pid) in members)
            out.append(item)
        return out

    async def refresh(self, force: bool = False) -> int:
        if self.st.args.demo or self.state != "connected" or self.api is None:
            return 0
        if not force and now() - self.last_attempt < self.MIN_INTERVAL:
            return 0
        async with self.lock:
            self.last_attempt = now()
            try:
                items = await asyncio.wait_for(asyncio.to_thread(self._fetch), timeout=90)
                for it in items:
                    self.st.store.apple_upsert_fmip(it)
                    self.st.store.apple_update(it["id"], extra=it.get("extra") or {}, raw=it.get("raw") or {})
                    if it.get("online") and it["online"].get("ts"):
                        self.st.store.add_online_report(it["id"], it["online"], it.get("battery_level"))
                self.error, self.failures, self.last_refresh = None, 0, now()
                self._publish()
                return len(items)
            except Exception as e:  # noqa: BLE001
                self.failures += 1
                self.error = self._friendly(e)
                log.warning("Online-Ortung fehlgeschlagen: %s (%s)", self.error, e)
                name = type(e).__name__
                if "Auth" in name or "Login" in name or "2FA" in name or "Token" in name:
                    self.state = "disconnected"  # nicht automatisch mit Passwort neu anmelden
                self._publish()
                return 0

    def _dev(self, aid: str) -> Any:
        if self.state != "connected" or self.api is None:
            raise RuntimeError("Online-Ortung ist nicht verbunden")
        dev = next((d for d in self.api.devices if str(d.data.get("id")) == aid), None)
        if dev is None:
            raise RuntimeError("Gerät nicht gefunden")
        return dev

    async def send_message(self, aid: str, subject: str, text: str, sound: bool) -> None:
        await asyncio.to_thread(lambda: self._dev(aid).display_message(subject=subject or "FindMy Ultra",
                                                                       message=text, sounds=sound))

    async def lost_mode(self, aid: str, number: str, text: str) -> None:
        await asyncio.to_thread(lambda: self._dev(aid).lost_device(number=number, text=text))

    async def play_sound(self, aid: str) -> None:
        if self.state != "connected" or self.api is None:
            raise RuntimeError("Online-Ortung ist nicht verbunden")

        def _do() -> None:
            dev = next((d for d in self.api.devices if str(d.data.get("id")) == aid), None)
            if dev is None:
                raise RuntimeError("Gerät nicht gefunden")
            dev.play_sound(subject="FindMy Ultra")
        await asyncio.to_thread(_do)

    @staticmethod
    def _friendly(e: Exception) -> str:
        n = type(e).__name__
        if "AccountLocked" in n:
            return "Apple hat den Account vorübergehend gesperrt – bitte später erneut verbinden."
        if "FailedLogin" in n or "Password" in n:
            return "Apple-ID oder Passwort falsch."
        if "Connection" in n or isinstance(e, (OSError, asyncio.TimeoutError)):
            return "iCloud nicht erreichbar – Netzwerk/Firewall prüfen (idmsa.apple.com, *.icloud.com)."
        if "ServiceUnavailable" in n:
            return "„Wo ist?“ ist für diesen Account nicht verfügbar."
        return f"{n}: {e}"

    async def loop(self) -> None:
        await asyncio.sleep(5)
        await self.resume()
        while True:
            cfg = self.st.store.settings()["online_devices"]
            if cfg.get("enabled") and self.state == "connected":
                await self.refresh()
            wait = max(self.MIN_INTERVAL, int(cfg.get("interval", 120))) * min(2 ** self.failures, 16)
            # Laufende Aufzeichnung mit Online-Quelle → häufiger abfragen
            if not self.failures and any(se["active"] and se["source"] in ("online", "both")
                                         for se in self.st.store.recordings()):
                wait = min(wait, 60)
            self.event.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.event.wait(), timeout=wait)


def apple_device_public(st: "State", d: dict) -> dict:
    """Fügt Online- und Offline-Standorte (AirTag-Schlüssel) zusammen."""
    parts = []
    for role, did in (d.get("links") or {}).items():
        last = st.store.db.execute("SELECT * FROM reports WHERE device_id=? ORDER BY ts DESC LIMIT 1",
                                   (did,)).fetchone()
        dev = st.store.device_row(did)
        bat = st.store.db.execute("SELECT battery, ts FROM reports WHERE device_id=? AND battery IS NOT NULL "
                                  "ORDER BY ts DESC LIMIT 1", (did,)).fetchone()
        stt = st.store.db.execute("SELECT status FROM reports WHERE device_id=? AND status IS NOT NULL "
                                  "ORDER BY ts DESC LIMIT 1", (did,)).fetchone()
        status_type = STATUS_TYPES.get(((stt[0] or 0) >> 4) & 0b11) if stt else None
        parts.append({"role": role, "device_id": did, "name": dev["name"] if dev else None,
                      "last": dict(last) if last else None,
                      "battery": bat[0] if bat else None, "battery_ts": bat[1] if bat else None,
                      "status_type": status_type,
                      "total": st.store.db.execute("SELECT COUNT(*) FROM reports WHERE device_id=?",
                                                   (did,)).fetchone()[0]})
    order = {"main": 0, "left": 1, "right": 2, "case": 3}
    parts.sort(key=lambda p: order.get(p["role"], 9))
    cands = []
    on = d.get("online")
    if on and on.get("ts"):
        cands.append({**{k: on[k] for k in ("lat", "lon", "accuracy", "ts")}, "source": "online", "role": None})
    for p in parts:
        if p["last"]:
            l = p["last"]
            cands.append({"lat": l["lat"], "lon": l["lon"], "accuracy": l["accuracy"], "ts": l["ts"],
                          "source": "offline", "role": p["role"]})
    best = max(cands, key=lambda c: c["ts"]) if cands else None
    out = {k: d.get(k) for k in ("id", "kind", "mode", "emoji", "model", "display_name", "device_class",
                                 "battery_level", "battery_status", "device_status", "hidden", "sort",
                                 "updated_at")}
    sess = st.store.recordings(d["id"])
    active = next((x for x in sess if x["active"]), None)
    online_count = st.store.db.execute("SELECT COUNT(*) FROM online_reports WHERE apple_id=?",
                                       (d["id"],)).fetchone()[0]
    out.update(name=d.get("custom_name") or d.get("name"), apple_name=d.get("name"), online=on,
               parts=parts, best=best, reachable=d.get("device_status") in ("200", "201"),
               settings=d.get("settings") or DEFAULT_APPLE_SETTINGS,
               case_status=airpods_case_status(parts, (d.get("settings") or DEFAULT_APPLE_SETTINGS)["case"],
                                               (d.get("extra") or {}).get("audio_channels"),
                                               (on or {}).get("ts"))
               if d.get("mode") == "airpods" else None,
               active_session=active, sessions_count=len(sess), online_points=online_count,
               extra=d.get("extra") or {},
               separation=airpods_separation(st, d, (d.get("settings") or DEFAULT_APPLE_SETTINGS)["case"])
               if d.get("mode") == "airpods" else None)
    return out


STATUS_TYPES = {0b00: "apple", 0b01: "airtag", 0b10: "third_party", 0b11: "airpods"}


def airpods_separation(st: "State", d: dict, cfg: dict) -> list[dict] | None:
    """
    Erkennt, ob AirPods-Teile getrennt sind: Zwei Teile gelten als getrennt, wenn sie zu
    ähnlicher Zeit (≤ 15 min Abstand) an verschiedenen Orten geortet wurden – erst bestätigt nach
    mind. `sep_min_obs` solchen Beobachtungen in Folge (einzelne Ausreißer zählen nicht).
    """
    links = d.get("links") or {}
    roles = [r for r in ("left", "right", "case") if r in links]
    if len(roles) < 2:
        return None
    lookback = now() - float(cfg.get("sep_lookback_h", 6)) * 3600
    min_obs = int(cfg.get("sep_min_obs", 2))
    base_m = float(cfg.get("sep_distance_m", 150))
    reps = {r: [dict(x) for x in st.store.db.execute(
        "SELECT ts, lat, lon, accuracy FROM reports WHERE device_id=? AND ts>=? ORDER BY ts", (links[r], lookback))]
        for r in roles}
    out = []
    for i, a in enumerate(roles):
        for b in roles[i + 1:]:
            obs = []
            for x in reps[a]:
                near = min(reps[b], key=lambda y: abs(y["ts"] - x["ts"]), default=None)
                if near is None or abs(near["ts"] - x["ts"]) > 900:
                    continue
                dist = haversine(x["lat"], x["lon"], near["lat"], near["lon"])
                thr = base_m + (x["accuracy"] or 0) + (near["accuracy"] or 0)
                obs.append((max(x["ts"], near["ts"]), dist, dist > thr))
            obs.sort()
            streak = 0
            for _, _, sep in reversed(obs):
                if not sep:
                    break
                streak += 1
            if not obs:
                state = "unknown"
            elif streak >= min_obs:
                state = "separated"
            elif obs[-1][2]:
                state = "maybe"
            else:
                state = "together"
            out.append({"a": a, "b": b, "state": state, "distance": round(obs[-1][1]) if obs else None,
                        "observations": len(obs), "streak": streak, "since": obs[-streak][0] if streak else None,
                        "last_ts": obs[-1][0] if obs else None})
    return out


def airpods_case_status(parts: list[dict], cfg: dict, channels: list | None = None,
                        online_ts: float | None = None) -> dict | None:
    """
    Schätzt aus den Offline-Ortungen, ob die Ohrhörer im Case sind.
    Grundlage: Ohrhörer senden eigene Wo-ist-Signale vor allem, wenn sie außerhalb des Case
    sind. Ein frischer Bericht eines Ohrhörers ⇒ „draußen“. Hat das Case danach neuere
    Berichte, während der Ohrhörer schweigt ⇒ „vermutlich im Case“. Sonst „unbekannt“.
    """
    by = {p["role"]: p for p in parts}
    case_last = (by.get("case") or {}).get("last")
    if not any(by.get(r) for r in ("left", "right")):
        return None
    win = float(cfg.get("window_min", 20)) * 60
    t = now()
    out: dict = {}
    for r in ("left", "right"):
        p = by.get(r)
        last = (p or {}).get("last")
        if not p:
            out[r] = {"state": "no_key", "since": None, "reason": "Keine Schlüsseldatei"}
            continue
        if last and t - last["ts"] <= win:
            reason = f"vor {int((t - last['ts']) / 60)} min eigenständig geortet"
            if p.get("status_type") and p["status_type"] != "airpods":
                reason += " (Statusbyte: kein AirPods-Typ?)"
            if case_last and abs(case_last["ts"] - last["ts"]) < 900:
                d = haversine(case_last["lat"], case_last["lon"], last["lat"], last["lon"])
                if d > 40 + (case_last.get("accuracy") or 0) + (last.get("accuracy") or 0):
                    reason += f", {fmt_dist(d)} vom Case entfernt"
            out[r] = {"state": "out", "since": last["ts"], "reason": reason}
        elif case_last and (not last or case_last["ts"] > last["ts"]):
            out[r] = {"state": "in_case", "since": last["ts"] if last else None,
                      "reason": "Case meldet sich, Ohrhörer nicht"}
        else:
            out[r] = {"state": "unknown", "since": last["ts"] if last else None,
                      "reason": "Zu wenige aktuelle Ortungen"}
    # Online-Hinweis: iCloud meldet einen Audiokanal als verfügbar ⇒ Ohrhörer aktiv/außerhalb des Case
    if channels and online_ts and t - online_ts <= win:
        for ch in channels:
            side = (ch.get("name") or "").lower()
            r = "left" if side.startswith("l") else "right" if side.startswith("r") else None
            if r and ch.get("available") and out.get(r, {}).get("state") != "no_key":
                out[r] = {"state": "out", "since": online_ts, "reason": "iCloud: Kanal aktiv (online)"}
    states = {out[r]["state"] for r in ("left", "right") if out[r]["state"] != "no_key"}
    if states == {"in_case"}:
        summary = "Im Case"
    elif states == {"out"}:
        summary = "Draußen"
    elif "out" in states:
        summary = "Teilweise draußen"
    else:
        summary = "Unbekannt"
    out["summary"] = summary
    out["estimated"] = True
    return out


async def check_case_alerts(st: "State") -> None:
    """Erkennt Wechsel Case ↔ draußen und benachrichtigt (immer oder einmalig)."""
    for d in st.store.apple_rows():
        if d.get("mode") != "airpods" or not d.get("links"):
            continue
        pub = apple_device_public(st, d)
        cs = pub.get("case_status")
        if not cs:
            continue
        cfg = d["settings"]["case"]
        state = d.get("state") or {}
        prev: dict = state.get("case", {})
        fired: dict = state.get("fired", {})
        changed = False
        for r in ("left", "right"):
            cur = cs[r]["state"]
            if cur in ("unknown", "no_key"):
                continue
            old = prev.get(r)
            if old != cur:
                prev[r] = cur
                changed = True
                if old is None:
                    continue  # erste Einschätzung → kein Alarm
                direction = "out" if cur == "out" else "in"
                a = cfg["alert_out" if direction == "out" else "alert_in"]
                if a.get("enabled") and not (cfg.get("once") and fired.get(f"{r}_{direction}")):
                    fired[f"{r}_{direction}"] = True
                    side = "Linker" if r == "left" else "Rechter"
                    last = next((p["last"] for p in pub["parts"] if p["role"] == r), None) or {}
                    await st.notifier.notify(
                        device={"id": d["id"], "name": pub["name"], "emoji": d.get("emoji") or "🎧"},
                        kind="airpods_case", level=a.get("level", "active"),
                        title=(f"🎧 {side} AirPod wurde aus dem Case genommen" if direction == "out"
                               else f"🎧 {side} AirPod ist wieder im Case"),
                        body=f"{pub['name']} · {cs[r]['reason']}",
                        lat=last.get("lat"), lon=last.get("lon"),
                        url=f"findmyultra://apple/{quote(d['id'], safe='')}")
        # Trennung (z. B. linker AirPod woanders als rechter/Case)
        seps: dict = state.get("sep", {})
        for sp in pub.get("separation") or []:
            key = f"{sp['a']}-{sp['b']}"
            cur = sp["state"]
            if cur not in ("separated", "together"):
                continue
            old = seps.get(key)
            if old != cur:
                seps[key] = cur
                changed = True
                a = cfg.get("alert_separated") or {}
                if old == "together" and cur == "separated" and a.get("enabled") \
                        and not (cfg.get("once") and fired.get(f"sep_{key}")):
                    fired[f"sep_{key}"] = True
                    names = {"left": "Linker AirPod", "right": "Rechter AirPod", "case": "Case"}
                    await st.notifier.notify(
                        device={"id": d["id"], "name": pub["name"], "emoji": d.get("emoji") or "🎧"},
                        kind="airpods_separated", level=a.get("level", "timeSensitive"),
                        title=f"🎧 {names[sp['a']]} und {names[sp['b']]} sind getrennt",
                        body=f"{pub['name']} · {fmt_dist(sp['distance'] or 0)} auseinander "
                             f"({sp['streak']} Ortungen bestätigt)",
                        url=f"findmyultra://apple/{quote(d['id'], safe='')}")
        if changed:
            st.store.apple_update(d["id"], state={**state, "case": prev, "fired": fired, "sep": seps})


def session_points(st: "State", se: dict) -> list[dict]:
    """Alle Punkte einer Aufzeichnung (online + offline je nach Quelle), im Report-Format."""
    row = st.store.apple_row(se["apple_id"])
    if not row:
        return []
    lo, hi = se["start_ts"], se["effective_end"] or now() + 60
    pts: list[dict] = []
    if se["source"] in ("offline", "both"):
        for role, did in (row.get("links") or {}).items():
            for r in st.store.db.execute("SELECT * FROM reports WHERE device_id=? AND ts BETWEEN ? AND ?",
                                         (did, lo, hi)).fetchall():
                x = dict(r)
                x.update(device_id=se["apple_id"], source="offline", role=role, position_type=None)
                pts.append(x)
    if se["source"] in ("online", "both"):
        for r in st.store.db.execute("SELECT * FROM online_reports WHERE apple_id=? AND ts BETWEEN ? AND ?",
                                     (se["apple_id"], lo, hi)).fetchall():
            bl = r["battery_level"]
            pts.append({"id": -int(r["id"]), "device_id": se["apple_id"], "ts": r["ts"], "lat": r["lat"],
                        "lon": r["lon"], "accuracy": r["accuracy"], "confidence": None, "status": None,
                        "battery": None if bl is None else ("full" if bl > .6 else "medium" if bl > .3 else
                                                            "low" if bl > .1 else "critical"),
                        "battery_level": bl, "received_at": r["received_at"], "batch_id": None,
                        "batch_size": 1, "late": 0, "source": "online", "role": None,
                        "position_type": r["position_type"]})
    pts.sort(key=lambda p: p["ts"])
    return pts


# ════════════════════════════════════════════════════════════════════════════
#  Aufenthalte (Stay-Point-Erkennung mit Ausreißer-Toleranz)
# ════════════════════════════════════════════════════════════════════════════

def _weighted_center(pts: list[dict]) -> tuple[float, float]:
    """Gewichteter Mittelpunkt (genauere Berichte zählen mehr), robust per Median-Vorfilter."""
    if len(pts) >= 5:
        mlat = sorted(p["lat"] for p in pts)[len(pts) // 2]
        mlon = sorted(p["lon"] for p in pts)[len(pts) // 2]
        dists = sorted(haversine(mlat, mlon, p["lat"], p["lon"]) for p in pts)
        cut = max(dists[int(len(dists) * 0.8)] * 1.5, 30)
        core = [p for p in pts if haversine(mlat, mlon, p["lat"], p["lon"]) <= cut] or pts
    else:
        core = pts
    w = [1.0 / max(float(p.get("accuracy") or 50), 5.0) ** 2 for p in core]
    tw = sum(w)
    return (sum(p["lat"] * x for p, x in zip(core, w)) / tw,
            sum(p["lon"] * x for p, x in zip(core, w)) / tw)


def compute_stays(reports: list[dict], cfg: dict, now_ts: float | None = None) -> dict:
    """
    Erkennt Aufenthalte („stationäre Orte“) aus einer Berichtsliste.

    * Ein Aufenthalt beginnt mit einem genauen Bericht; folgende Berichte innerhalb
      radius (+ halbe Ungenauigkeit) gehören dazu, der Mittelpunkt wird laufend
      gewichtet neu berechnet.
    * Bis zu max_outliers Berichte außerhalb, die zusammen höchstens
      outlier_minutes dauern, gelten als Ausreißer, wenn danach wieder ein Bericht
      am Ort folgt – sie brechen den Aufenthalt nicht.
    * Ungenaue Berichte (> max_accuracy_m) zählen mit, wenn sie passen, sonst
      werden sie ignoriert (weder Ausreißer noch Abbruch).
    * Funkstille > max_gap_hours trennt; Aufenthalte am selben Ort mit
      Lücke ≤ merge_minutes werden zusammengefasst.
    * Häufige Orte: Aufenthalte mit nahen Mittelpunkten bilden „Orte“ mit
      Besuchsanzahl und Gesamtdauer.
    """
    radius = float(cfg.get("radius_m", 120))
    min_dur = float(cfg.get("min_minutes", 5)) * 60
    min_pts = int(cfg.get("min_points", 2))
    max_out = int(cfg.get("max_outliers", 3))
    out_win = float(cfg.get("outlier_minutes", 30)) * 60
    max_gap = float(cfg.get("max_gap_hours", 12)) * 3600
    max_acc = float(cfg.get("max_accuracy_m", 500))
    merge_gap = float(cfg.get("merge_minutes", 45)) * 60
    now_ts = now_ts or now()
    pts = sorted(reports, key=lambda r: r["ts"])

    def fits(c: dict, p: dict) -> bool:
        acc = float(p.get("accuracy") or 0)
        return haversine(c["lat"], c["lon"], p["lat"], p["lon"]) <= radius + min(acc, radius) * 0.5

    clusters: list[dict] = []
    cur: dict | None = None
    pending: list[dict] = []

    def close() -> None:
        nonlocal cur
        if cur is not None:
            clusters.append(cur)
        cur = None

    def start(p: dict) -> dict:
        return {"pts": [p], "lat": p["lat"], "lon": p["lon"], "outliers": 0, "next_ts": None}

    queue = list(pts)
    i = 0
    while i < len(queue):
        p = queue[i]
        i += 1
        weak = float(p.get("accuracy") or 0) > max_acc
        if cur is None:
            if not weak:
                cur = start(p)
            continue
        if p["ts"] - cur["pts"][-1]["ts"] > max_gap and not pending:
            close()
            if not weak:
                cur = start(p)
            continue
        if fits(cur, p):
            if pending:
                cur["outliers"] += len([x for x in pending if float(x.get("accuracy") or 0) <= max_acc])
                pending = []
            cur["pts"].append(p)
            cur["lat"], cur["lon"] = _weighted_center(cur["pts"])
            continue
        if weak:
            continue  # ungenauer Bericht außerhalb: ignorieren
        pending.append(p)
        if len(pending) > max_out or pending[-1]["ts"] - pending[0]["ts"] > out_win \
                or pending[0]["ts"] - cur["pts"][-1]["ts"] > max_gap:
            cur["next_ts"] = pending[0]["ts"]
            close()
            # Ausstehende Berichte neu auswerten – sie können einen neuen Aufenthalt bilden
            queue[i:i] = pending
            pending = []
    if cur is not None:
        if pending:
            cur["next_ts"] = pending[0]["ts"]
        clusters.append(cur)

    # Zusammenfassen: gleicher Ort, kurze Lücke
    merged: list[dict] = []
    for c in clusters:
        if merged:
            m = merged[-1]
            gap = c["pts"][0]["ts"] - m["pts"][-1]["ts"]
            if gap <= merge_gap and haversine(m["lat"], m["lon"], c["lat"], c["lon"]) <= radius:
                m["pts"] += c["pts"]
                m["outliers"] += c["outliers"]
                m["next_ts"] = c["next_ts"]
                m["lat"], m["lon"] = _weighted_center(m["pts"])
                continue
        merged.append(c)

    last_ts = pts[-1]["ts"] if pts else None
    stays = []
    for c in merged:
        cp = c["pts"]
        dur = cp[-1]["ts"] - cp[0]["ts"]
        if len(cp) < min_pts or dur < min_dur:
            continue
        d = sorted(haversine(c["lat"], c["lon"], p["lat"], p["lon"]) for p in cp)
        spread = d[min(len(d) - 1, int(len(d) * 0.9))]
        accs = sorted(float(p.get("accuracy") or 0) for p in cp)
        ongoing = cp[-1]["ts"] == last_ts and c["next_ts"] is None and now_ts - cp[-1]["ts"] < 6 * 3600
        stays.append({
            "id": f"{int(cp[0]['ts'])}-{len(cp)}",
            "lat": round(c["lat"], 7), "lon": round(c["lon"], 7),
            "radius": round(max(25.0, min(spread + accs[len(accs) // 2] * 0.5, radius * 1.5)), 1),
            "start": cp[0]["ts"], "end": cp[-1]["ts"], "duration": dur,
            "left_at": c["next_ts"], "points": len(cp), "outliers": c["outliers"],
            "first_report_id": cp[0].get("id"), "last_report_id": cp[-1].get("id"),
            "ongoing": bool(ongoing), "place_id": None,
        })

    # Häufige Orte
    places: list[dict] = []
    for st in sorted(stays, key=lambda x: -x["duration"]):
        pl = next((p for p in places if haversine(p["lat"], p["lon"], st["lat"], st["lon"]) <= radius), None)
        if pl is None:
            pl = {"id": f"p{len(places) + 1}", "lat": st["lat"], "lon": st["lon"], "visits": 0,
                  "total_duration": 0.0, "last_seen": 0.0, "radius": st["radius"]}
            places.append(pl)
        pl["visits"] += 1
        pl["total_duration"] += st["duration"]
        pl["last_seen"] = max(pl["last_seen"], st["end"])
        st["place_id"] = pl["id"]
    places.sort(key=lambda p: -p["total_duration"])
    stays.sort(key=lambda x: x["start"])
    return {"stays": stays, "places": places,
            "total_stay_time": sum(x["duration"] for x in stays), "params": {
                "radius_m": radius, "min_minutes": min_dur / 60, "min_points": min_pts,
                "max_outliers": max_out, "outlier_minutes": out_win / 60,
                "max_gap_hours": max_gap / 3600, "max_accuracy_m": max_acc, "merge_minutes": merge_gap / 60}}


class Notifier:
    def __init__(self, st: "State") -> None:
        self.st = st
        self.http: ClientSession | None = None
        self.geo_cache: dict[tuple, str] = {}

    async def session(self) -> ClientSession:
        if self.http is None or self.http.closed:
            self.http = ClientSession(timeout=ClientTimeout(total=15),
                                      headers={"User-Agent": f"FindMyUltra/{VERSION}"})
        return self.http

    async def address(self, lat: float, lon: float) -> str | None:
        if not self.st.store.settings().get("geocode"):
            return None
        key = (round(lat, 4), round(lon, 4))
        if key in self.geo_cache:
            return self.geo_cache[key]
        try:
            s = await self.session()
            async with s.get("https://nominatim.openstreetmap.org/reverse",
                             params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18,
                                     "accept-language": "de"}) as r:
                j = await r.json()
            a = j.get("address", {})
            parts = [" ".join(x for x in (a.get("road"), a.get("house_number")) if x),
                     a.get("city") or a.get("town") or a.get("village") or a.get("suburb")]
            txt = ", ".join(p for p in parts if p) or j.get("display_name")
            self.geo_cache[key] = txt
            return txt
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _in_quiet(qh: dict) -> bool:
        if not qh.get("enabled"):
            return False
        try:
            n = dt.datetime.now().strftime("%H:%M")
            s, e = qh["start"], qh["end"]
            return (s <= n < e) if s < e else (n >= s or n < e)
        except Exception:  # noqa: BLE001
            return False

    async def notify(self, *, device: dict | None, kind: str, level: str, title: str, body: str,
                     lat: float | None = None, lon: float | None = None, url: str | None = None) -> None:
        level = level if level in LEVELS else "active"
        if lat is not None and lon is not None:
            addr = await self.address(lat, lon)
            if addr:
                body = f"{body}\n📍 {addr}"
        nid = self.st.store.add_notification(ts=now(), device_id=device["id"] if device else None,
                                             kind=kind, level=level, title=title, body=body,
                                             lat=lat, lon=lon, delivered=0, error=None)
        payload = {"id": nid, "ts": now(), "device_id": device["id"] if device else None, "kind": kind,
                   "level": level, "title": title, "body": body, "lat": lat, "lon": lon}
        self.st.hub.publish("notification", payload)
        log.info("🔔 [%s] %s – %s", level, title, body.replace("\n", " | "))
        if url and device is not None:
            device = {**device, "url": url}
        ok, err = await self.send_bark(title, body, level, device, lat, lon)
        self.st.store.set_delivery(nid, ok, err)

    async def send_bark(self, title: str, body: str, level: str, device: dict | None,
                        lat: float | None, lon: float | None, force: bool = False) -> tuple[bool, str | None]:
        cfg = self.st.store.settings()
        bark = cfg["bark"]
        if not force:
            if not bark.get("enabled") or not bark.get("device_keys"):
                return False, "Bark nicht eingerichtet"
            if LEVELS.index(level) < LEVELS.index(bark.get("min_level", "passive")):
                return False, "unter Mindest-Stufe"
            if level != "critical" and self._in_quiet(cfg.get("quiet_hours", {})):
                level = "passive"
        server = (bark.get("server") or "https://api.day.app").rstrip("/")
        errors = []
        s = await self.session()
        for key in bark.get("device_keys", []):
            data: dict = {"device_key": key, "title": title, "body": body, "level": level,
                          "group": bark.get("group") or APP_NAME}
            if device:
                data["url"] = device.get("url") or f"findmyultra://device/{quote(device['id'])}"
                data["subtitle"] = f"{device.get('emoji') or ''} {device.get('name') or ''}".strip()
            elif lat is not None:
                data["url"] = f"https://maps.apple.com/?ll={lat},{lon}"
            if bark.get("icon"):
                data["icon"] = bark["icon"]
            if level == "critical":
                data["volume"] = max(0, min(10, int(bark.get("critical_volume", 8))))
                if bark.get("critical_sound"):
                    data["sound"] = bark["critical_sound"]
                data["call"] = "1"  # wiederholt den Ton (Bark „Anruf“-Modus)
            elif bark.get("sound"):
                data["sound"] = bark["sound"]
            try:
                async with s.post(f"{server}/push", json=data) as r:
                    j = await r.json(content_type=None)
                    if r.status != 200 or j.get("code") not in (200, None):
                        errors.append(f"{r.status}: {j.get('message')}")
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
        if errors:
            log.warning("Bark-Fehler: %s", "; ".join(errors))
        return (not errors and bool(bark.get("device_keys"))), ("; ".join(errors) or None)


class Alerts:
    """Wertet neue Berichte aus und löst Benachrichtigungen aus."""

    def __init__(self, st: "State") -> None:
        self.st = st

    async def on_reports(self, dev_id: str, new: list[dict], prev_newest: float) -> None:
        dev = self.st.store.device_row(dev_id)
        if not dev or not new:
            return
        a, lost, state = dev["alerts"], dev["lost"], dev["state"]
        fresh = sorted([r for r in new if r["ts"] > prev_newest], key=lambda r: r["ts"])
        name = f"{dev.get('emoji') or ''} {dev['name']}".strip()
        t = now()
        changed = False

        if state.get("offline_alerted") and fresh:
            state["offline_alerted"] = False
            changed = True
            if a["offline"]["enabled"]:
                r = fresh[-1]
                await self.st.notifier.notify(device=dev, kind="online", level="active",
                                              title=f"{name} ist wieder da",
                                              body=f"Neuer Standort von {fmt_time(r['ts'])}",
                                              lat=r["lat"], lon=r["lon"])

        if fresh:
            r = fresh[-1]
            acc = f"±{r['accuracy']} m" if r.get("accuracy") is not None else ""
            maps = f"{r['lat']:.5f}, {r['lon']:.5f}"

            # Verloren-Modus: jeder neue Standort = Fund
            if lost.get("enabled") and (lost.get("notify_every_report") or not state.get("lost_found")):
                if t - state.get("lost_last", 0) > 45:
                    state["lost_last"], state["lost_found"] = t, True
                    changed = True
                    await self.st.notifier.notify(
                        device=dev, kind="lost_found", level=lost.get("level", "critical"),
                        title=f"🚨 {name} wurde gesichtet!",
                        body=f"Verloren-Modus: neuer Standort {fmt_time(r['ts'])} {acc}\n{maps}"
                             + (f" · Batch ×{len(new)}" if len(new) > 1 else ""),
                        lat=r["lat"], lon=r["lon"])

            # Wache / Diebstahlschutz
            g = a["guard"]
            if g.get("enabled") and g.get("lat") is not None:
                d = haversine(g["lat"], g["lon"], r["lat"], r["lon"])
                if d > float(g.get("radius_m", 120)) + (r.get("accuracy") or 0) * 0.5:
                    if t - state.get("guard_last", 0) > 120:
                        state["guard_last"] = t
                        changed = True
                        await self.st.notifier.notify(
                            device=dev, kind="guard", level=g.get("level", "critical"),
                            title=f"⚠️ {name} wird bewegt!",
                            body=f"{fmt_dist(d)} vom gesicherten Ort entfernt ({fmt_time(r['ts'])}, {acc})",
                            lat=r["lat"], lon=r["lon"])

            # Plötzliche Bewegung in kurzer Zeit
            mv = a["movement"]
            if mv.get("enabled"):
                window = float(mv.get("window_min", 30)) * 60
                ref = self.st.store.db.execute(
                    "SELECT * FROM reports WHERE device_id=? AND ts>=? AND ts<? ORDER BY ts",
                    (dev_id, r["ts"] - window, r["ts"])).fetchall()
                best = None
                for x in ref:
                    d = haversine(x["lat"], x["lon"], r["lat"], r["lon"])
                    noise = (x["accuracy"] or 0) + (r.get("accuracy") or 0)
                    if d - noise >= float(mv.get("distance_m", 250)) and (best is None or d > best[0]):
                        best = (d, x)
                if best and t - state.get("move_last", 0) > window:
                    state["move_last"] = t
                    changed = True
                    mins = max(1, round((r["ts"] - best[1]["ts"]) / 60))
                    await self.st.notifier.notify(
                        device=dev, kind="movement", level=mv.get("level", "critical"),
                        title=f"🏃 {name} entfernt sich",
                        body=f"{fmt_dist(best[0])} in {mins} min (bis {fmt_time(r['ts'])})",
                        lat=r["lat"], lon=r["lon"])

            # Zonen
            zones = self.st.store.settings().get("zones", [])
            if zones:
                inside_prev: dict = state.get("zones", {})
                inside_now = {}
                for z in zones:
                    d = haversine(z["lat"], z["lon"], r["lat"], r["lon"])
                    inside_now[z["id"]] = d <= float(z.get("radius", 150))
                    was = inside_prev.get(z["id"])
                    if a["zones"].get("enabled") and was is not None and was != inside_now[z["id"]]:
                        verb = "hat {} betreten" if inside_now[z["id"]] else "hat {} verlassen"
                        await self.st.notifier.notify(
                            device=dev, kind="zone", level=a["zones"].get("level", "timeSensitive"),
                            title=f"{name} {verb.format(z['name'])}",
                            body=f"{fmt_time(r['ts'])} {acc}", lat=r["lat"], lon=r["lon"])
                state["zones"] = inside_now
                changed = True

            # Jeder neue Standort
            nr = a["new_report"]
            if nr.get("enabled") and t - state.get("new_last", 0) >= float(nr.get("min_interval_min", 30)) * 60:
                state["new_last"] = t
                changed = True
                await self.st.notifier.notify(
                    device=dev, kind="report", level=nr.get("level", "passive"),
                    title=f"{name}: neuer Standort",
                    body=f"{fmt_time(r['ts'])} {acc}" + (f" · {len(new)} Berichte" if len(new) > 1 else ""),
                    lat=r["lat"], lon=r["lon"])

        # Batterie
        bats = [r["battery"] for r in sorted(new, key=lambda x: x["ts"]) if r.get("battery")]
        if bats:
            b = bats[-1]
            if b != state.get("battery"):
                old = state.get("battery")
                state["battery"] = b
                changed = True
                if a["battery"].get("enabled") and b in ("low", "critical") and old not in (None, b):
                    await self.st.notifier.notify(
                        device=dev, kind="battery", level=a["battery"].get("level", "active"),
                        title=f"🔋 {name}: Batterie {'kritisch' if b == 'critical' else 'schwach'}",
                        body="Bitte bald die Knopfzelle (CR2032) tauschen." if dev.get("network") in (None, "apple", "samsung")
                        else "Bitte den Tracker bald aufladen bzw. die Batterie tauschen.")
        if changed:
            self.st.store.update_device(dev_id, state=state)

    async def check_offline(self) -> None:
        for dev in self.st.store.devices():
            o = dev["alerts"]["offline"]
            if not o.get("enabled") or not dev["enabled"] or not dev.get("last"):
                continue
            row = self.st.store.device_row(dev["id"])
            state = row["state"] if row else {}
            age = now() - dev["last"]["ts"]
            if age > float(o.get("hours", 12)) * 3600 and not state.get("offline_alerted"):
                state["offline_alerted"] = True
                self.st.store.update_device(dev["id"], state=state)
                name = f"{dev.get('emoji') or ''} {dev['name']}".strip()
                await self.st.notifier.notify(
                    device=dev, kind="offline", level=o.get("level", "active"),
                    title=f"{name} meldet sich nicht",
                    body=f"Letzter Standort vor {age / 3600:.1f} h ({fmt_time(dev['last']['ts'])})",
                    lat=dev["last"]["lat"], lon=dev["last"]["lon"])


# ════════════════════════════════════════════════════════════════════════════
#  Weitere Netze: Samsung SmartThings Find & Google Find Hub
# ════════════════════════════════════════════════════════════════════════════
#
# Tracker aus Google Find Hub und Samsung SmartThings Find werden als ganz
# normale Objekte in `devices` (Spalte `network`) mit Berichten in `reports`
# gespeichert. Karte, Verlauf, Aufenthalte, Alarme und Export funktionieren
# dadurch für alle Netze gleich. Übernommen und angepasst aus RJ TrackerApp.

NETWORKS = ("apple", "google", "samsung")
NETWORK_LABEL = {"apple": "Apple „Wo ist?“", "google": "Google Find Hub", "samsung": "Samsung SmartThings Find"}


def network_device_id(network: str, ext_id: str) -> str:
    """Stabile, URL-sichere Objekt-ID für einen Tracker eines fremden Netzes."""
    return f"{network[0]}-" + hashlib.sha1(f"{network}|{ext_id}".encode()).hexdigest()[:20]


def _private_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text("utf-8")) if path.exists() else {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_private_json(path: Path, data: dict) -> None:
    secure_write(path, json.dumps(data, indent=2, ensure_ascii=False))


def mask_account(s: str | None) -> str:
    s = str(s or "")
    if not s:
        return ""
    if "@" not in s:
        return (s[:2] + "•••") if len(s) > 2 else "•••"
    local, domain = s.split("@", 1)
    return f"{local[:2]}•••@{domain}"


class NetworkError(RuntimeError):
    def __init__(self, msg: str, status: int = 0, payload: dict | None = None) -> None:
        super().__init__(msg)
        self.status = status
        self.payload = payload or {}


def http_json(url: str, method: str = "GET", headers: dict | None = None, data: Any = None,
              timeout: float = 45, form: bool = False) -> dict:
    """Kleiner, synchroner JSON-Client (läuft per asyncio.to_thread)."""
    import urllib.error
    import urllib.parse
    import urllib.request
    h = {"Accept": "application/json", "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
         "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 8 Pro) AppleWebKit/537.36 Chrome/138 Mobile Safari/537.36"}
    h.update(headers or {})
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
            h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(8 * 1024 * 1024)
            out = json.loads(raw.decode("utf-8")) if raw else {}
            return out if isinstance(out, dict) else {"items": out}
    except urllib.error.HTTPError as e:
        raw = e.read(2 * 1024 * 1024)
        try:
            p = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:  # noqa: BLE001
            p = {"message": raw.decode("utf-8", "replace")[:300]}
        if not isinstance(p, dict):
            p = {"message": str(p)[:300]}
        msg = p.get("message") or p.get("error_description") or p.get("error") or f"HTTP {e.code}"
        raise NetworkError(str(msg)[:300], e.code, p) from None
    except urllib.error.URLError as e:
        raise NetworkError(f"Dienst nicht erreichbar ({e.reason}) – Firewall/Internet prüfen") from None


def network_ignored(store: "Store", network: str) -> set[str]:
    return set((store.kv_get("network_ignored", {}) or {}).get(network, []))


def set_network_ignored(store: "Store", network: str, ext_id: str | None, ignored: bool = True,
                        clear: bool = False) -> None:
    data = store.kv_get("network_ignored", {}) or {}
    cur = set(data.get(network, []))
    if clear:
        cur = set()
    elif ext_id:
        (cur.add if ignored else cur.discard)(ext_id)
    data[network] = sorted(cur)
    store.kv_set("network_ignored", data)


async def ingest_network_reports(st: "State", dev_id: str, items: list[dict]) -> int:
    """Neue Berichte speichern, live melden und Alarme auswerten."""
    items = [i for i in items if -90 <= float(i["lat"]) <= 90 and -180 <= float(i["lon"]) <= 180]
    if not items:
        return 0
    prev = st.store.newest_ts(dev_id)
    new = st.store.insert_reports(dev_id, items)
    if new:
        st.hub.publish("reports", {"device_id": dev_id, "reports": new})
        with contextlib.suppress(Exception):
            await st.alerts.on_reports(dev_id, new, prev)
    return len(new)


# ── Samsung SmartThings Find ──────────────────────────────────────────────────

SAMSUNG_LOGIN_CLIENT_ID = "yfrtglt53o"
SAMSUNG_SMARTTHINGS_CLIENT_ID = "6iado3s6jc"
SAMSUNG_FIND_CLIENT_ID = "27zmg0v1oo"
SAMSUNG_SMARTTHINGS_SCOPE = "iot.client"
SAMSUNG_FIND_SCOPE = "offline.access"
SAMSUNG_REDIRECT_URI = "ms-app://s-1-15-2-4027708247-2189610-1983755848-2937435718-1578786913-2158692839-1974417358"
SAMSUNG_ENTRYPOINT_URL = "https://account.samsung.com/accounts/ANDROIDSDK/getEntryPoint"
SAMSUNG_INSTALLED_APPS_URL = "https://api.smartthings.com/installedapps?allowed=true"
SAMSUNG_CLIENT_DEVICES_URL = ("https://client.smartthings.com/devices?includeAllowedActions=true&includeMfuLocations=true"
                              "&includeUserDevices=false&excludeLocationDevices=false&includeGroups=true"
                              "&includeHidden=true&exclusiveToHidden=false")
SAMSUNG_TAG_OCF_TYPE = "x.com.st.d.tag"
SAMSUNG_PLUGIN_ID = "com.samsung.android.plugin.fme"
SAMSUNG_ST_VERSION = os.environ.get("FMU_SMARTTHINGS_VERSION", "1.8.47.24")
SAMSUNG_BATTERY = {"FULL": "full", "MEDIUM": "medium", "LOW": "low", "VERY_LOW": "critical",
                   "03": "full", "02": "medium", "01": "low", "00": "critical"}


def _rand(n: int) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _pkce(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


class Samsung:
    """
    Galaxy SmartTags über das eigene Samsung-Konto (SmartThings Find).
    Anmeldung: Login-Seite von Samsung (in der App), die Rückleitung „ms-app://…“
    wird abgefangen und hier entschlüsselt. Ende-zu-Ende-verschlüsselte Standorte
    werden mit der Samsung-Find-PIN entschlüsselt.
    """

    def __init__(self, st: "State") -> None:
        self.st = st
        self.dir = DATA_DIR / "samsung"
        self.auth = _private_json(self.dir / "auth.json")
        self.pin = str(_private_json(self.dir / "pin.json").get("pin") or "")
        self.error: str | None = None
        self.pin_required = False
        self.last_refresh: float | None = None
        self.last_sync: float | None = None
        self.last_count = 0
        self.failures = 0
        self.event = asyncio.Event()
        self.alock = asyncio.Lock()
        self._tlock = __import__("threading").Lock()

    # Zustand ------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        return bool(self.auth.get("userauth_token"))

    def cfg(self) -> dict:
        return self.st.store.settings()["networks"]["samsung"]

    def status(self) -> dict:
        pending = _private_json(self.dir / "pending.json")
        c = self.cfg()
        return {"network": "samsung", "enabled": bool(c.get("enabled")), "connected": self.connected,
                "account": mask_account(self.auth.get("login_id")), "pin": bool(self.pin),
                "pin_required": self.pin_required, "history": bool(c.get("history")),
                "interval": int(c.get("interval", 120)), "error": self.error,
                "last_refresh": self.last_refresh, "last_sync": self.last_sync,
                "devices": len(self.st.store.network_devices("samsung")),
                "login_pending": bool(pending) and int(pending.get("created_ts", 0)) > now() - 1800}

    def _save_auth(self) -> None:
        _save_private_json(self.dir / "auth.json", self.auth)

    # Anmeldung ------------------------------------------------------------------
    def login_url(self) -> str:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding as apad
        entry = http_json(SAMSUNG_ENTRYPOINT_URL, timeout=20)
        public_key = serialization.load_der_public_key(base64.b64decode(entry["pkiPublicKey"]))
        check = str(entry["chkDoNum"])
        state_key, verifier = _rand(20), _rand(43)
        android_id = str(self.auth.get("android_id") or secrets.token_hex(8))
        svc = {"birthDate": None, "clientId": SAMSUNG_LOGIN_CLIENT_ID, "code_challenge": _pkce(verifier),
               "code_challenge_method": "S256", "competitorDeviceYNFlag": "Y", "countryCode": "de",
               "deviceInfo": "Google|com.android.chrome", "deviceModelID": "Pixel 8 Pro",
               "deviceName": "Google Pixel 8 Pro", "deviceOSVersion": "35",
               "devicePhysicalAddressText": f"ANID:{android_id}", "deviceType": "APP",
               "deviceUniqueID": android_id, "redirect_uri": SAMSUNG_REDIRECT_URI,
               "replaceableClientConnectYN": "N", "replaceableClientId": "",
               "replaceableDevicePhysicalAddressText": "", "responseEncryptionType": "1",
               "responseEncryptionYNFlag": "Y", "scope": "", "state": state_key, "svcIptLgnID": "",
               "iosYNFlag": "Y"}
        salt = secrets.token_bytes(16)
        password = base64.b64encode(hashlib.sha256(check.encode()).digest())
        key = hashlib.pbkdf2_hmac("sha256", password, salt, int(check), dklen=16)
        enc_key = public_key.encrypt(base64.b64encode(key), apad.PKCS1v15())
        iv = secrets.token_bytes(16)
        payload = self._aes_cbc(key, iv, json.dumps(svc, ensure_ascii=False, separators=(",", ":")).encode())
        envelope = {"chkDoNum": check, "svcEncParam": base64.b64encode(payload).decode(),
                    "svcEncKY": base64.b64encode(enc_key).decode(), "svcEncIV": iv.hex()}
        encoded = quote(base64.b64encode(json.dumps(envelope, separators=(",", ":")).encode()).decode(), safe="")
        url = f"{entry['signInURI']}?locale=de-DE&svcParam={encoded}&mode=C"
        _save_private_json(self.dir / "pending.json", {"state": state_key, "code_verifier": verifier,
                                                       "android_id": android_id, "created_ts": int(now())})
        self.auth.setdefault("android_id", android_id)
        if self.auth:
            self._save_auth()
        return url

    @staticmethod
    def _aes_cbc(key: bytes, iv: bytes, value: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        p = PKCS7(128).padder()
        e = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return e.update(p.update(value) + p.finalize()) + e.finalize()

    @staticmethod
    def _ecb_hex(value: str, key_text: str) -> str:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        key = str(key_text).encode()[:16].ljust(16, b"0")
        d = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        u = PKCS7(128).unpadder()
        padded = d.update(bytes.fromhex(str(value))) + d.finalize()
        return (u.update(padded) + u.finalize()).decode()

    @staticmethod
    def _osp_headers() -> dict:
        return {"X-Osp-Clientosversion": "35", "X-Osp-Clientmodel": "Pixel 8 Pro",
                "X-Osp-Appid": SAMSUNG_LOGIN_CLIENT_ID, "X-Osp-Packagename": "com.samsung.android.oneconnect",
                "X-Osp-Packageversion": SAMSUNG_ST_VERSION,
                "User-Agent": f"OneConnect/{SAMSUNG_ST_VERSION} (Android 15; Pixel 8 Pro)"}

    @staticmethod
    def _base(auth: dict) -> str:
        b = str(auth.get("auth_server_url") or "").rstrip("/")
        return b if b.startswith("https://") else "https://" + b

    def _exchange(self, auth: dict, client_id: str, scope: str) -> dict:
        import urllib.parse
        verifier = _rand(43)
        params = {"response_type": "code", "serviceType": "M", "client_id": client_id,
                  "code_challenge_method": "S256", "childAccountSupported": "Y",
                  "userauth_token": auth["userauth_token"], "code_challenge": _pkce(verifier),
                  "physical_address_text": auth["android_id"], "scope": scope, "login_id": auth.get("login_id") or ""}
        base = self._base(auth)
        r = http_json(base + "/auth/oauth2/v2/authorize?" + urllib.parse.urlencode(params),
                      headers=self._osp_headers(), timeout=30)
        if not r.get("code") and r.get("privacyAccepted") == "N":
            params.pop("login_id", None)
            r = http_json(base + "/auth/oauth2/v2/authorize?" + urllib.parse.urlencode(params),
                          headers=self._osp_headers(), timeout=30)
        if not r.get("code"):
            raise NetworkError("Samsung hat keinen API-Autorisierungscode geliefert.")
        return http_json(base + "/auth/oauth2/token", "POST", self._osp_headers(), form=True, timeout=30, data={
            "grant_type": "authorization_code", "code": r["code"], "client_id": client_id,
            "code_verifier": verifier, "physical_address_text": auth["android_id"]})

    def complete_login(self, redirect: str) -> dict:
        from urllib.parse import parse_qs
        pending = _private_json(self.dir / "pending.json")
        if not pending or int(pending.get("created_ts", 0)) < now() - 1800:
            raise NetworkError("Der Samsung-Login ist abgelaufen. Bitte neu starten.")
        value = str(redirect or "").strip()
        if "?" not in value:
            value = "ms-app://callback?" + value.lstrip("?")
        q = parse_qs(urlparse(value).query)
        enc = {k: (q.get(k) or [""])[0] for k in ("state", "code", "auth_server_url", "retValue")}
        if not all(enc.values()):
            raise NetworkError("Die Samsung-Rückleitung enthält nicht alle Anmeldedaten.")
        rk = self._ecb_hex(enc["state"], pending["state"])
        code = self._ecb_hex(enc["code"], rk)
        auth_url = self._ecb_hex(enc["auth_server_url"], rk)
        login_id = self._ecb_hex(enc["retValue"], rk)
        auth = {"android_id": pending["android_id"], "auth_server_url": auth_url, "login_id": login_id}
        r = http_json(self._base(auth) + "/auth/oauth2/authenticate", "POST", self._osp_headers(), form=True,
                      timeout=30, data={"grant_type": "authorization_code", "serviceType": "M", "code": code,
                                        "client_id": SAMSUNG_LOGIN_CLIENT_ID,
                                        "code_verifier": pending["code_verifier"], "username": login_id,
                                        "physical_address_text": pending["android_id"]})
        if not r.get("userauth_token") or not r.get("userId"):
            raise NetworkError("Samsung hat keine dauerhafte Kontoberechtigung geliefert.")
        auth.update(userauth_token=r["userauth_token"], user_id=r["userId"], connected_ts=int(now()))
        iot = self._exchange(auth, SAMSUNG_SMARTTHINGS_CLIENT_ID, SAMSUNG_SMARTTHINGS_SCOPE)
        find = self._exchange(auth, SAMSUNG_FIND_CLIENT_ID, SAMSUNG_FIND_SCOPE)
        auth.update(iot_token=iot.get("access_token"), iot_refresh_token=iot.get("refresh_token"),
                    find_token=find.get("access_token"), find_refresh_token=find.get("refresh_token"),
                    token_updated_ts=int(now()), installed_app_id="")
        self.auth = auth
        self._save_auth()
        with contextlib.suppress(FileNotFoundError):
            (self.dir / "pending.json").unlink()
        self.error = None
        self.failures = 0
        return auth

    def logout(self) -> None:
        self.auth = {}
        self.pin = ""
        self.pin_required = False
        for f in ("auth.json", "pending.json", "pin.json"):
            with contextlib.suppress(FileNotFoundError):
                (self.dir / f).unlink()

    def set_pin(self, pin: str | None) -> None:
        self.pin = str(pin or "").strip()
        if self.pin:
            _save_private_json(self.dir / "pin.json", {"pin": self.pin})
        else:
            with contextlib.suppress(FileNotFoundError):
                (self.dir / "pin.json").unlink()

    # API ------------------------------------------------------------------------
    def _refresh_token(self) -> str:
        with self._tlock:
            auth = dict(self.auth)
            if not auth.get("userauth_token"):
                raise NetworkError("Samsung-Konto ist nicht verbunden.")
            token = None
            if auth.get("iot_refresh_token"):
                with contextlib.suppress(Exception):
                    token = http_json(self._base(auth) + "/auth/oauth2/token", "POST", self._osp_headers(),
                                      form=True, timeout=30,
                                      data={"grant_type": "refresh_token", "client_id": SAMSUNG_SMARTTHINGS_CLIENT_ID,
                                            "refresh_token": auth["iot_refresh_token"]})
            if not token or not token.get("access_token"):
                token = self._exchange(auth, SAMSUNG_SMARTTHINGS_CLIENT_ID, SAMSUNG_SMARTTHINGS_SCOPE)
            auth["iot_token"] = token.get("access_token")
            auth["iot_refresh_token"] = token.get("refresh_token") or auth.get("iot_refresh_token")
            auth["token_updated_ts"] = int(now())
            self.auth = auth
            self._save_auth()
            return auth["iot_token"]

    def _headers(self, refresh: bool = False) -> dict:
        token = self.auth.get("iot_token")
        if refresh or not token:
            token = self._refresh_token()
        return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.smartthings+json;v=1",
                "Accept-Language": "de-DE", "X-St-Client-Appversion": SAMSUNG_ST_VERSION,
                "X-St-Client-Devicemodel": "Google Pixel 8 Pro husky", "X-St-Client-Os": "Android 15",
                "X-St-Correlation": secrets.token_hex(16),
                "User-Agent": f"Android/OneApp/{SAMSUNG_ST_VERSION}/Main (Pixel 8 Pro; Android VANILLA_ICE_CREAM/15) SmartKit/4.423.1"}

    def _get(self, url: str, timeout: float = 45) -> dict:
        try:
            return http_json(url, headers=self._headers(), timeout=timeout)
        except NetworkError as e:
            if e.status == 401:
                return http_json(url, headers=self._headers(refresh=True), timeout=timeout)
            raise

    def _installed_app(self, force: bool = False) -> str:
        if self.auth.get("installed_app_id") and not force:
            return self.auth["installed_app_id"]
        url: str | None = SAMSUNG_INSTALLED_APPS_URL
        items: list = []
        while url:
            r = self._get(url, 30)
            items += r.get("items", [])
            url = ((r.get("links") or {}).get("next") or {}).get("href")
        match = next((i for i in items if (i.get("ui") or {}).get("pluginId") == SAMSUNG_PLUGIN_ID), None)
        if not match or not match.get("installedAppId"):
            raise NetworkError("SmartThings Find ist im Samsung-Konto nicht aktiv. Bitte einmal in der "
                               "SmartThings-App „Find“ öffnen.")
        self.auth["installed_app_id"] = match["installedAppId"]
        self._save_auth()
        return match["installedAppId"]

    def execute(self, method: str, uri: str, extra_uri: str | None = None, extra: dict | None = None) -> dict:
        app_id = self._installed_app()
        off = dt.datetime.now().astimezone().utcoffset() or dt.timedelta()
        mins = int(off.total_seconds() // 60)
        tz = f"UTC{'+' if mins >= 0 else '-'}{abs(mins) // 60:02d}:{abs(mins) % 60:02d}"
        params = {"requester": self.auth.get("user_id") or "", "clientType": "aPlugin", "extraUri": extra_uri,
                  "method": method, "encodedHeaders": "", "requesterToken": self.auth.get("iot_token") or "",
                  "encodedBody": "", "clientVersion": "1", "uri": uri}
        params.update({str(k): str(v) for k, v in (extra or {}).items()})
        payload = {"client": {"displayMode": "DARK", "language": "de-DE",
                              "mobileDeviceId": self.auth.get("android_id") or "", "os": "Android",
                              "samsungAccountId": self.auth.get("user_id"),
                              "supportedTemplates": [f"BASIC_V{i}" for i in range(1, 8)],
                              "timeZoneOffset": tz, "version": SAMSUNG_ST_VERSION},
                   "parameters": params}
        url = f"https://api.smartthings.com/installedapps/{app_id}/execute"
        try:
            r = http_json(url, "POST", self._headers(), payload, timeout=60)
        except NetworkError as e:
            if e.status == 401:
                params["requesterToken"] = self._refresh_token()
                r = http_json(url, "POST", self._headers(), payload, timeout=60)
            elif e.status in (403, 404):
                self._installed_app(force=True)
                r = http_json(url, "POST", self._headers(), payload, timeout=60)
            else:
                raise
        code = int(r.get("statusCode", 200) or 200)
        if code != 200:
            raise NetworkError(str(r.get("message") or r.get("errorCode") or f"Samsung-Fehler {code}"))
        res = r.get("message")
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except Exception:  # noqa: BLE001
                return {"message": res}
        return res if isinstance(res, dict) else {}

    @staticmethod
    def _is_tag(item: dict) -> bool:
        if str(item.get("ocfDeviceType") or "").strip().lower() == SAMSUNG_TAG_OCF_TYPE:
            return True
        caps = [str(c.get("id") or "") for comp in (item.get("components") or []) if isinstance(comp, dict)
                for c in (comp.get("capabilities") or []) if isinstance(c, dict)]
        return bool(item.get("bleD2D")) and any(c.startswith("tag.") for c in caps)

    def list_tags(self) -> list[dict]:
        """Alle SmartTags des Kontos (SmartThings-Geräteliste + Find-Fallbackliste)."""
        tags: dict[str, dict] = {}
        client_error = None
        try:
            url: str | None = SAMSUNG_CLIENT_DEVICES_URL
            pages = 0
            while url and pages < 20:
                pages += 1
                r = self._get(url)
                for it in r.get("items") or []:
                    if not isinstance(it, dict) or not self._is_tag(it):
                        continue
                    did = str(it.get("deviceId") or "").strip()
                    if not did:
                        continue
                    meta = ((it.get("bleD2D") or {}).get("metadata") or {}) if isinstance(it.get("bleD2D"), dict) else {}
                    vendor = meta.get("vendor") or {}
                    bat = (meta.get("battery") or {}).get("level")
                    tags[did] = {"ext_id": did, "name": str(it.get("label") or it.get("name") or "Galaxy SmartTag")[:80],
                                 "model": str(vendor.get("modelName") or "Galaxy SmartTag")[:80],
                                 "battery": SAMSUNG_BATTERY.get(str(bat or "").upper())}
                links = r.get("_links") or r.get("links") or {}
                nxt = (links.get("next") or {}).get("href") if isinstance(links, dict) else None
                if nxt and str(nxt).startswith("/"):
                    nxt = "https://client.smartthings.com" + str(nxt)
                url = str(nxt) if nxt else None
        except Exception as e:  # noqa: BLE001
            client_error = str(e)
        fme = []
        with contextlib.suppress(Exception):
            fme = [i for i in (self.execute("GET", "/devices").get("devices") or []) if isinstance(i, dict)]
        for it in fme:
            if str(it.get("locationType") or "").upper() != "TRACKER":
                continue
            did = str(it.get("stDid") or "").strip()
            if did and did not in tags:
                tags[did] = {"ext_id": did, "name": str(it.get("stDevName") or "Galaxy SmartTag")[:80],
                             "model": "Galaxy SmartTag", "battery": None}
        if not tags and client_error and not fme:
            raise NetworkError(f"SmartThings-Geräteliste nicht lesbar: {client_error}")
        return list(tags.values())

    # Entschlüsselung (Ende-zu-Ende, Samsung-Find-PIN) -----------------------------
    @staticmethod
    def _private_key(pair: dict, pin: str) -> Any:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        priv = str(pair.get("privateKey") or "")
        iv = str(pair.get("iv") or "")
        if not priv or not iv or not pin:
            return None
        v2 = priv.endswith("_v2")
        if v2:
            priv = priv[:-3]
        material = str(pin) + (str(pair.get("userId") or "") if v2 else "")
        key = hashlib.sha256(material.encode()).digest()
        d = Cipher(algorithms.AES(key), modes.CBC(base64.b64decode(iv))).decryptor()
        padded = d.update(base64.b64decode(priv)) + d.finalize()
        u = PKCS7(128).unpadder()
        k = serialization.load_der_private_key(u.update(padded) + u.finalize(), password=None)
        if not isinstance(k, ec.EllipticCurvePrivateKey):
            raise ValueError("Samsung-Find-Schlüssel ist kein EC-Schlüssel")
        return k

    @staticmethod
    def _ecies(value: Any, key: Any) -> str:
        from cryptography.hazmat.primitives.asymmetric import ec
        enc = base64.b64decode(str(value))
        size = (key.curve.key_size + 7) // 8
        plen = 1 + 2 * size if enc[:1] == b"\x04" else 1 + size
        if len(enc) <= plen + 20:
            raise ValueError("ECIES-Wert zu kurz")
        eph, ct, mac = enc[:plen], enc[plen:-20], enc[-20:]
        shared = key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(key.curve, eph))
        out, counter, seed = bytearray(), 1, eph + shared
        while len(out) < len(ct) + 16:
            out += hashlib.sha1(seed + counter.to_bytes(4, "big")).digest()
            counter += 1
        if not hmac.compare_digest(mac, hmac.new(bytes(out[:16]), ct + b"\x00" * 8, hashlib.sha1).digest()):
            raise ValueError("Samsung-Find-PIN falsch")
        return bytes(a ^ b for a, b in zip(ct, out[16:])).decode()

    def _point(self, raw: dict, key: Any) -> tuple[dict | None, bool]:
        encrypted = False
        try:
            lat, lon = float(raw.get("latitude")), float(raw.get("longitude"))
        except (TypeError, ValueError):
            encrypted = True
            if key is None:
                return None, True
            try:
                lat, lon = float(self._ecies(raw.get("latitude"), key)), float(self._ecies(raw.get("longitude"), key))
            except Exception:  # noqa: BLE001
                return None, True
        try:
            ts = float(raw.get("lastUpdateTime") or now())
            ts = ts / 1000 if ts > 1e11 else ts
            acc = max(0.0, float(raw.get("accuracy") or 0))
        except (TypeError, ValueError):
            return None, False
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None, encrypted
        return {"ts": round(ts, 3), "lat": round(lat, 7), "lon": round(lon, 7), "accuracy": int(acc),
                "battery": SAMSUNG_BATTERY.get(str(raw.get("battery") or "").upper())}, False

    def fetch(self, ext_id: str, history_start: float | None) -> tuple[list[dict], bool]:
        cur = self.execute("GET", "/trackers/geolocation", extra={"stDids": ext_id})
        pair = next((p for p in cur.get("keyPairs") or [] if isinstance(p, dict) and p.get("privateKey")), None)
        key = None
        if pair and self.pin:
            with contextlib.suppress(Exception):
                key = self._private_key(pair, self.pin)
        raws = [g for it in cur.get("items") or [] if str(it.get("deviceId")) == ext_id
                for g in it.get("geolocations") or []]
        if history_start:
            end = int(now() * 1000)
            with contextlib.suppress(Exception):
                h = self.execute("GET", "/trackerapi",
                                 extra_uri=f"/trackers/{quote(ext_id, safe='')}/geolocations?order=asc&isSummary=false"
                                           f"&startTime={int(history_start * 1000)}&endTime={end}&limit=500")
                raws += h.get("geolocations") or []
        items, pin_needed = [], False
        for raw in raws:
            if not isinstance(raw, dict):
                continue
            p, enc = self._point(raw, key)
            pin_needed = pin_needed or enc
            if p:
                items.append(p)
        return items, pin_needed

    # Abläufe ----------------------------------------------------------------------
    async def sync(self, restore: bool = False) -> dict:
        tags = await asyncio.to_thread(self.list_tags)
        if restore:
            set_network_ignored(self.st.store, "samsung", None, clear=True)
        ignored = network_ignored(self.st.store, "samsung")
        added = 0
        for t in tags:
            if t["ext_id"] in ignored:
                continue
            _, new = self.st.store.upsert_network_device("samsung", t["ext_id"], t["name"], t["model"], "tag")
            added += int(new)
        self.last_sync = now()
        if added:
            self.st.hub.publish("devices", {"devices": self.st.store.devices()})
        return {"tags": len(tags), "added": added}

    async def refresh(self, ids: list[str] | None = None) -> int:
        if not self.connected:
            raise NetworkError("Samsung-Konto ist nicht verbunden.")
        async with self.alock:
            if not self.last_sync or now() - self.last_sync > 6 * 3600:
                await self.sync()
            c = self.cfg()
            total, pin_needed = 0, False
            for d in self.st.store.network_devices("samsung"):
                if not d["enabled"] or (ids and d["id"] not in ids):
                    continue
                start = None
                if c.get("history"):
                    newest = self.st.store.newest_ts(d["id"])
                    start = max(now() - 7 * 86400, (newest - 3600) if newest else 0)
                items, pn = await asyncio.to_thread(self.fetch, d["ext_id"], start)
                pin_needed = pin_needed or pn
                total += await ingest_network_reports(self.st, d["id"], items)
            self.pin_required = pin_needed
            self.last_refresh = now()
            self.last_count = total
            self.error = "Standorte sind verschlüsselt – bitte Samsung-Find-PIN eingeben." if pin_needed and total == 0 else None
            if total:
                self.st.hub.publish("devices", {"devices": self.st.store.devices()})
            self.st.hub.publish("networks", {"samsung": self.status()})
            return total

    async def loop(self) -> None:
        await asyncio.sleep(4)
        while True:
            c = self.cfg()
            if c.get("enabled") and self.connected:
                try:
                    await self.refresh()
                    self.failures = 0
                except Exception as e:  # noqa: BLE001
                    self.failures = min(self.failures + 1, 6)
                    self.error = f"{e}"
                    log.warning("Samsung-Abruf fehlgeschlagen: %s", e)
                    self.st.hub.publish("networks", {"samsung": self.status()})
            wait = max(30, int(c.get("interval", 120))) * (2 ** self.failures)
            self.event.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.event.wait(), timeout=min(wait, 3600))


# ── Google Find Hub (Server-Fallback über GoogleFindMyTools) ──────────────────

GOOGLE_TOOLS_REPO = os.environ.get("FMU_GOOGLE_REPOSITORY", "leonboe1/GoogleFindMyTools")
GOOGLE_TOOLS_COMMIT = os.environ.get("FMU_GOOGLE_COMMIT", "d46e9528578015b51d3b84dd91bf8f16e9ab850f")
GOOGLE_TOOLS_URL = f"https://github.com/{GOOGLE_TOOLS_REPO}/archive/{GOOGLE_TOOLS_COMMIT}.zip"
GOOGLE_FOREIGN_ENV = ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE", "PYTHONPLATLIBDIR",
                      "PYTHONUSERBASE", "__PYVENV_LAUNCHER__", "VIRTUAL_ENV", "FMU_BOOTSTRAPPED")


class GoogleServer:
    """
    Google Find Hub auf dem Server – als Ergänzung bzw. Fallback zur Ortung
    direkt in der App. Zugang: secrets.json (GoogleFindMyTools) oder die in der
    App angemeldeten Schlüssel („An Server übergeben“). Abgerufen wird über
    GoogleFindMyTools in einer eigenen Python-Umgebung (data/google/venv).
    Die App liefert zusätzlich lokal entschlüsselte Standorte (POST
    /api/google/app-reports); im Modus „auto“ ortet der Server nur, wenn die App
    länger nichts geliefert hat.
    """

    def __init__(self, st: "State") -> None:
        self.st = st
        self.dir = DATA_DIR / "google"
        self.secrets_path = self.dir / "secrets.json"
        self.tools = self.dir / "tools"
        self.venv = self.dir / "venv"
        self.setup: dict = {"status": "idle", "message": ""}
        self.error: str | None = None
        self.last_refresh: float | None = None
        self.last_sync: float | None = None
        self.app_push: dict[str, float] = st.store.kv_get("google_app_push", {}) or {}
        self.event = asyncio.Event()
        self.alock = asyncio.Lock()
        self.failures = 0
        self._setup_task: asyncio.Task | None = None

    def cfg(self) -> dict:
        return self.st.store.settings()["networks"]["google"]

    def secrets(self) -> dict:
        return _private_json(self.secrets_path)

    @property
    def has_access(self) -> bool:
        s = self.secrets()
        return bool(s.get("username") and s.get("aas_token") and (s.get("owner_key") or s.get("shared_key")))

    @property
    def python(self) -> Path:
        return self.venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    @property
    def tools_ready(self) -> bool:
        marker = _private_json(self.dir / "tools_meta.json")
        return (self.tools / "main.py").exists() and self.python.exists() and marker.get("commit") == GOOGLE_TOOLS_COMMIT \
            and marker.get("deps") is True

    def status(self) -> dict:
        c = self.cfg()
        s = self.secrets()
        return {"network": "google", "enabled": bool(c.get("enabled")), "server_mode": c.get("server_mode", "auto"),
                "interval": int(c.get("interval", 900)), "account": mask_account(s.get("username")),
                "secrets": bool(s.get("username") and s.get("aas_token")),
                "keys": bool(s.get("owner_key") or s.get("shared_key")),
                "tools_ready": self.tools_ready, "setup": self.setup, "error": self.error,
                "last_refresh": self.last_refresh, "last_sync": self.last_sync,
                "last_app_push": max(self.app_push.values()) if self.app_push else None,
                "devices": len(self.st.store.network_devices("google"))}

    # Zugang -------------------------------------------------------------------------
    def store_secrets(self, data: dict) -> None:
        if not isinstance(data, dict):
            raise ValueError("Die secrets.json muss ein JSON-Objekt sein.")
        cur = self.secrets()
        username = str(data.get("username") or cur.get("username") or "")
        if "@" not in username or not (data.get("aas_token") or cur.get("aas_token")):
            raise ValueError("username und aas_token fehlen.")
        for k in ("owner_key", "shared_key"):
            v = data.get(k)
            if v and not (isinstance(v, str) and len(v) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in v)):
                raise ValueError(f"{k} ist kein gültiger 32-Byte-Schlüssel (64 Hex-Zeichen).")
        new = dict(cur)
        if cur.get("username") and cur["username"].lower() != username.lower():
            new = {"fcm_credentials": cur.get("fcm_credentials")} if cur.get("fcm_credentials") else {}
        for k in ("username", "aas_token", "owner_key", "shared_key", "owner_key_version", "fcm_credentials"):
            if data.get(k):
                new[k] = data[k]
        new["username"] = username
        if cur.get("username") and cur["username"] != username:
            backup = self.dir / f"secrets-backup-{int(now())}.json"
            _save_private_json(backup, cur)
        _save_private_json(self.secrets_path, new)
        self.error = None
        self.failures = 0

    def delete_secrets(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.secrets_path.unlink()
        with contextlib.suppress(FileNotFoundError):
            (self.tools / "Auth" / "secrets.json").unlink()

    # Einrichtung (GoogleFindMyTools + eigene Python-Umgebung) ----------------------------
    def _env(self, pythonpath: Path | None = None) -> dict:
        env = os.environ.copy()
        for k in GOOGLE_FOREIGN_ENV:
            env.pop(k, None)
        env["PYTHONUNBUFFERED"] = "1"
        if pythonpath:
            env["PYTHONPATH"] = str(pythonpath)
        return env

    def _install_sync(self) -> None:
        import shutil
        import stat
        import tempfile
        import urllib.request
        import zipfile
        self.dir.mkdir(parents=True, exist_ok=True)
        meta = _private_json(self.dir / "tools_meta.json")
        if not ((self.tools / "main.py").exists() and meta.get("commit") == GOOGLE_TOOLS_COMMIT):
            self.setup = {"status": "running", "message": "GoogleFindMyTools wird geladen …"}
            tmp = Path(tempfile.mkdtemp(prefix="gfmt-", dir=self.dir))
            try:
                zpath = tmp / "tools.zip"
                req = urllib.request.Request(GOOGLE_TOOLS_URL, headers={"User-Agent": f"FindMyUltra/{VERSION}"})
                with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
                    total = 0
                    while chunk := r.read(1 << 20):
                        total += len(chunk)
                        if total > 30 << 20:
                            raise ValueError("Download unerwartet groß")
                        f.write(chunk)
                out = tmp / "x"
                with zipfile.ZipFile(zpath) as z:
                    for info in z.infolist():
                        parts = [p for p in info.filename.replace("\\", "/").split("/") if p not in ("", ".")]
                        if info.filename.startswith("/") or ".." in parts or stat.S_ISLNK(info.external_attr >> 16):
                            raise ValueError("Unsicherer Pfad im Archiv")
                        target = out.joinpath(*parts) if parts else out
                        if info.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(info) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                roots = [p.parent for p in out.rglob("main.py") if (p.parent / "NovaApi").is_dir()]
                if len(roots) != 1:
                    raise ValueError("GoogleFindMyTools-Archiv nicht erkannt")
                if self.tools.exists():
                    shutil.rmtree(self.tools, ignore_errors=True)
                shutil.move(str(roots[0]), str(self.tools))
                meta = {"commit": GOOGLE_TOOLS_COMMIT, "repository": GOOGLE_TOOLS_REPO, "deps": False}
                _save_private_json(self.dir / "tools_meta.json", meta)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        ok = False
        if self.python.exists():
            with contextlib.suppress(Exception):
                ok = subprocess.run([str(self.python), "-I", "-c", "import encodings, json, ssl"],
                                    capture_output=True, timeout=30, env=self._env()).returncode == 0
        if not ok:
            self.setup = {"status": "running", "message": "Python-Umgebung für Google wird erstellt …"}
            if self.venv.exists():
                shutil.rmtree(self.venv, ignore_errors=True)
            r = subprocess.run([sys.executable, "-m", "venv", str(self.venv)], capture_output=True, text=True,
                               timeout=600, env=self._env())
            if r.returncode != 0:
                raise RuntimeError("venv konnte nicht erstellt werden (python3-venv installieren): "
                                   + (r.stderr or r.stdout)[-300:])
        self.setup = {"status": "running", "message": "Abhängigkeiten werden installiert (einige Minuten) …"}
        r = subprocess.run([str(self.python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                            "--prefer-binary", "-r", str(self.tools / "requirements.txt"), "gpsoauth>=2.0.0,<3"],
                           cwd=str(self.tools), capture_output=True, text=True, timeout=3600, env=self._env())
        if r.returncode != 0:
            raise RuntimeError("Installation der Abhängigkeiten fehlgeschlagen: " + (r.stderr or r.stdout)[-400:])
        meta["deps"] = True
        _save_private_json(self.dir / "tools_meta.json", meta)

    def start_setup(self) -> None:
        if self._setup_task and not self._setup_task.done():
            return

        async def run() -> None:
            self.setup = {"status": "running", "message": "Einrichtung startet …", "started": now()}
            try:
                await asyncio.to_thread(self._install_sync)
                self.setup = {"status": "success", "message": "Google-Server-Ortung ist einsatzbereit.", "finished": now()}
                if self.has_access:
                    with contextlib.suppress(Exception):
                        await self.sync()
            except Exception as e:  # noqa: BLE001
                self.setup = {"status": "error", "message": f"{e}"[:400], "finished": now()}
                log.warning("Google-Einrichtung fehlgeschlagen: %s", e)
            self.st.hub.publish("networks", {"google": self.status()})

        self._setup_task = asyncio.create_task(run())

    # Bridge ---------------------------------------------------------------------------
    def bridge(self, payload: dict, timeout: float) -> dict:
        if not self.tools_ready:
            raise NetworkError("Google-Server-Ortung ist noch nicht eingerichtet (Netzwerke → Google → Einrichten).")
        canonical = self.secrets()
        if not canonical:
            raise NetworkError("Kein Google-Zugang auf dem Server – in der App „An Server übergeben“ oder secrets.json hochladen.")
        target = self.tools / "Auth" / "secrets.json"
        _save_private_json(target, canonical)
        try:
            proc = subprocess.run([str(self.python), "-c", GOOGLE_BRIDGE_SOURCE], cwd=str(self.tools),
                                  env=self._env(self.tools), input=json.dumps(payload), capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise NetworkError("Google-Abruf hat das Zeitlimit überschritten.") from None
        finally:
            # FCM-Zugangsdaten werden von GoogleFindMyTools aktualisiert → zurückübernehmen
            tool = _private_json(target)
            if isinstance(tool.get("fcm_credentials"), dict) and tool["fcm_credentials"] != canonical.get("fcm_credentials"):
                merged = dict(self.secrets() or canonical)
                merged["fcm_credentials"] = tool["fcm_credentials"]
                _save_private_json(self.secrets_path, merged)
        for line in reversed((proc.stdout or "").splitlines()):
            if line.startswith("__FUSION_JSON__"):
                res = json.loads(line[len("__FUSION_JSON__"):])
                if not res.get("ok"):
                    detail = str(res.get("detail") or res.get("error") or "Google-Fehler")
                    if "BadAuthentication" in detail or "NeedsBrowser" in detail:
                        detail = "Google hat den Zugang abgelehnt – in der App neu anmelden und erneut übergeben."
                    raise NetworkError(detail[:400])
                return res
        tail = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-400:]
        raise NetworkError("GoogleFindMyTools lieferte keine Antwort: " + tail.strip())

    async def sync(self, restore: bool = False) -> dict:
        async with self.alock:
            res = await asyncio.to_thread(self.bridge, {"operation": "list"}, 120)
        if restore:
            set_network_ignored(self.st.store, "google", None, clear=True)
        ignored = network_ignored(self.st.store, "google")
        added = 0
        for d in res.get("devices") or []:
            if not d.get("id") or d["id"] in ignored:
                continue
            model = " ".join(x for x in (d.get("manufacturer"), d.get("model")) if x) or None
            _, new = self.st.store.upsert_network_device("google", str(d["id"]), str(d.get("name") or "Google-Tracker")[:80],
                                                         model, "tracker")
            added += int(new)
        self.last_sync = now()
        if added:
            self.st.hub.publish("devices", {"devices": self.st.store.devices()})
        return {"trackers": len(res.get("devices") or []), "added": added}

    async def locate(self, dev: dict) -> int:
        async with self.alock:
            res = await asyncio.to_thread(self.bridge, {"operation": "locate", "device_id": dev["ext_id"],
                                                        "fcm_registration_timeout": 22, "fcm_ready_timeout": 24,
                                                        "fcm_response_timeout": 48}, 200)
        items = [{"ts": float(r["ts"]), "lat": round(float(r["lat"]), 7), "lon": round(float(r["lon"]), 7),
                  "accuracy": int(float(r.get("acc") or 0)), "status": None, "battery": None}
                 for r in res.get("reports") or [] if r.get("lat") is not None]
        return await ingest_network_reports(self.st, dev["id"], items)

    async def refresh(self, ids: list[str] | None = None, force: bool = True) -> int:
        if not self.has_access or not self.tools_ready:
            raise NetworkError("Google-Server-Ortung ist nicht eingerichtet.")
        if not self.last_sync or now() - self.last_sync > 12 * 3600:
            await self.sync()
        c = self.cfg()
        grace = float(c.get("app_grace_min", 30)) * 60
        total = 0
        errors = []
        for d in self.st.store.network_devices("google"):
            if not d["enabled"] or (ids and d["id"] not in ids):
                continue
            if not force and c.get("server_mode") == "auto" and now() - self.app_push.get(d["id"], 0) < grace:
                continue  # App liefert gerade selbst – Server muss nicht orten
            try:
                total += await self.locate(d)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{d['name']}: {e}")
        self.last_refresh = now()
        self.error = "; ".join(errors)[:400] if errors else None
        if total:
            self.st.hub.publish("devices", {"devices": self.st.store.devices()})
        self.st.hub.publish("networks", {"google": self.status()})
        return total

    async def app_reports(self, body: dict) -> dict:
        """Von der App lokal entschlüsselte Google-Standorte übernehmen."""
        ignored = network_ignored(self.st.store, "google")
        total, mapping = 0, []
        for d in body.get("devices") or []:
            ext = str(d.get("id") or "").strip()
            if not ext or ext in ignored:
                continue
            did, _ = self.st.store.upsert_network_device("google", ext, str(d.get("name") or "Google-Tracker")[:80],
                                                         (str(d["model"])[:80] if d.get("model") else None), "tracker")
            mapping.append({"ext_id": ext, "id": did})
            items = []
            for r in (d.get("reports") or [])[:5000]:
                with contextlib.suppress(TypeError, ValueError, KeyError):
                    items.append({"ts": round(float(r["ts"]), 3), "lat": round(float(r["lat"]), 7),
                                  "lon": round(float(r["lon"]), 7),
                                  "accuracy": int(float(r.get("accuracy") or 0)) if r.get("accuracy") is not None else None,
                                  "battery": r.get("battery") if r.get("battery") in BATTERY.values() else None})
            total += await ingest_network_reports(self.st, did, items)
            self.app_push[did] = now()
        self.st.store.kv_set("google_app_push", self.app_push)
        if mapping:
            self.st.hub.publish("devices", {"devices": self.st.store.devices()})
        return {"ok": True, "new": total, "devices": mapping}

    async def loop(self) -> None:
        await asyncio.sleep(20)
        while True:
            c = self.cfg()
            if c.get("enabled") and c.get("server_mode", "auto") != "off" and self.has_access and self.tools_ready:
                try:
                    await self.refresh(force=c.get("server_mode") == "always")
                    self.failures = 0
                except Exception as e:  # noqa: BLE001
                    self.failures = min(self.failures + 1, 4)
                    self.error = f"{e}"[:400]
                    log.warning("Google-Server-Abruf fehlgeschlagen: %s", e)
            wait = max(300, int(c.get("interval", 900))) * (2 ** self.failures)
            self.event.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.event.wait(), timeout=min(wait, 4 * 3600))


def networks_summary(st: "State") -> dict:
    nets = st.store.settings()["networks"]
    counts = {n: 0 for n in NETWORKS}
    for row in st.store.db.execute("SELECT network, COUNT(*) FROM devices GROUP BY network").fetchall():
        counts[row[0] or "apple"] = row[1]
    out = {"apple": {"network": "apple", "enabled": bool(nets["apple"].get("enabled", True)),
                     "connected": bool(st.apple and st.apple.logged_in), "devices": counts.get("apple", 0)}}
    if st.samsung:
        out["samsung"] = st.samsung.status()
    if st.google:
        out["google"] = st.google.status()
    return out


# Bridge-Skript für GoogleFindMyTools (läuft isoliert in data/google/venv).
# Übernommen aus RJ TrackerApp (Backend), inkl. der dort beschriebenen Fixes.
GOOGLE_BRIDGE_SOURCE = r'''
import asyncio
import contextlib
import datetime
import io
import json
import sys
import threading
import time
import traceback
import re

MARKER="__FUSION_JSON__"

# Python 3.14 no longer creates an implicit event loop for synchronous main
# threads.  GoogleFindMyTools' FCM receiver still expects one in some releases,
# so give the isolated bridge process its own loop before importing upstream
# modules.  The process is short-lived and therefore owns the loop completely.
try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

def install_google_oauth_guard():
    """Replace upstream's unsafe auth_response['Auth'] lookup for this bridge.

    GoogleFindMyTools currently indexes the response directly.  Google may
    legitimately answer with Error/NeedsBrowser/BadAuthentication instead,
    which otherwise becomes an unhelpful KeyError('Auth').  Keeping the patch
    inside this short-lived subprocess leaves the downloaded upstream bundle
    untouched while exposing a deterministic, sanitized error to the guardian.
    """
    import gpsoauth
    import Auth.token_retrieval as token_retrieval
    from Auth.aas_token_retrieval import get_aas_token
    from Auth.fcm_receiver import FcmReceiver

    def guarded_request_token(username, scope, play_services=False):
        aas_token = get_aas_token()
        android_id = FcmReceiver().get_android_id()
        request_app = 'com.google.android.gms' if play_services else 'com.google.android.apps.adm'
        last_response = None
        for attempt in range(2):
            response = gpsoauth.perform_oauth(
                username, aas_token, android_id,
                service='oauth2:https://www.googleapis.com/auth/' + scope,
                app=request_app,
                client_sig='38918a453d07199354f8b19af05ec6562ced5788',
            )
            last_response = response
            if isinstance(response, dict) and response.get('Auth'):
                return response['Auth']
            # One small retry catches occasional auth endpoint hiccups without
            # multiplying normal location traffic. Browser/account challenges
            # cannot be fixed by repeating the same request.
            error_name = str((response or {}).get('Error') or (response or {}).get('error') or 'MissingAuth') if isinstance(response, dict) else 'InvalidResponse'
            if attempt == 0 and error_name.lower() not in {'needsbrowser', 'captcharequired', 'accountdisabled', 'accountdeleted', 'servicedisabled'}:
                time.sleep(0.8)
                continue
            break

        response = last_response if isinstance(last_response, dict) else {}
        error_name = str(response.get('Error') or response.get('error') or 'MissingAuth')[:80]
        error_detail = str(response.get('ErrorDetail') or response.get('error_detail') or '')[:240]
        browser_required = bool(response.get('Url') or response.get('url'))
        detail = f"google_oauth_error:{error_name}"
        if error_detail:
            detail += f"; detail={error_detail}"
        if browser_required:
            detail += "; browser_required=true"
        raise RuntimeError(detail)

    token_retrieval.request_token = guarded_request_token

install_google_oauth_guard()

def install_fcm_android_header_guard():
    """Backport Google's Android API-key restriction headers at runtime.

    The pinned upstream remains unmodified on disk. Google began rejecting
    Firebase installation requests without the package/certificate identity;
    newer upstream revisions add the same two public Android headers.
    """
    try:
        import aiohttp
        original=aiohttp.ClientSession._request
        if getattr(original,"_uts_android_guard",False):
            return
        async def guarded(self,method,str_or_url,**kwargs):
            url=str(str_or_url)
            headers=dict(kwargs.get("headers") or {})
            lower={str(key).lower() for key in headers}
            if "googleapis.com" in url and "x-goog-api-key" in lower:
                headers.setdefault("X-Android-Package","com.google.android.apps.adm")
                headers.setdefault("X-Android-Cert","38918a453d07199354f8b19af05ec6562ced5788")
                kwargs["headers"]=headers
            return await original(self,method,str_or_url,**kwargs)
        guarded._uts_android_guard=True
        aiohttp.ClientSession._request=guarded
    except Exception:
        pass

install_fcm_android_header_guard()

def install_fcm_message_guard():
    """Backport the reviewed transport fixes from GoogleFindMyTools PR #114.

    Parse named Web Push parameters, accept unpadded base64url and isolate
    malformed/foreign packets so one notification cannot kill the listener.
    Only modifies the short-lived bridge; never rewrites installed upstream.
    """
    from Auth.firebase_messaging.fcmpushclient import FcmPushClient
    original = FcmPushClient._decrypt_raw_data
    def decode(credentials, crypto_key_str, salt_str, raw_data):
        def padded(value):
            return value + '=' * (-len(value) % 4)
        return original(credentials, padded(crypto_key_str), padded(salt_str), raw_data)
    FcmPushClient._decrypt_raw_data = staticmethod(decode)
    def parameter(header, name):
        for part in header.split(';'):
            key, separator, value = part.strip().partition('=')
            if separator and key == name:
                return value.strip().strip('"')
        return ''
    def handle(self, msg):
        try:
            fields = {item.key: item.value for item in msg.app_data}
            if fields.get('message_type') == 'deleted_messages' or not self.credentials:
                return
            if fields.get('subtype') != self.credentials.get('gcm', {}).get('app_id'):
                return
            key = parameter(fields.get('crypto-key', ''), 'dh')
            salt = parameter(fields.get('encryption', ''), 'salt')
            if not key or not salt:
                return
            decrypted = self._decrypt_raw_data(self.credentials, key, salt, msg.raw_data)
            try:
                value = json.loads(decrypted.decode('utf-8'))
            except (ValueError, UnicodeError):
                value = decrypted
            self.callback(value, msg.persistent_id, self.callback_context)
        except Exception:
            # No packet contents, keys or tokens in diagnostics.
            self._uts_invalid_messages = getattr(self, '_uts_invalid_messages', 0) + 1
    FcmPushClient._handle_data_message = handle

install_fcm_message_guard()

def emit(value):
    print(MARKER+json.dumps(value,ensure_ascii=False,separators=(",",":")))

def parse_locations(text,metadata):
    reports=[]
    current={}
    semantic=""
    for raw in text.splitlines():
        line=raw.strip()
        if line.startswith("Semantic Location:"):
            semantic=line.split(":",1)[1].strip()
        elif line.startswith("Latitude:"):
            current["lat"]=float(line.split(":",1)[1].strip())
        elif line.startswith("Longitude:"):
            current["lon"]=float(line.split(":",1)[1].strip())
        elif line.startswith("Altitude:"):
            current["alt"]=float(line.split(":",1)[1].strip())
        elif line.startswith("Time:"):
            value=line.split(":",1)[1].strip()
            current["ts"]=int(datetime.datetime.strptime(value,"%Y-%m-%d %H:%M:%S").timestamp())
        elif line.startswith("Status:"):
            value=line.split(":",1)[1].strip()
            try:
                current["status"]=int(value)
            except ValueError:
                current["status"]=value
        elif line.startswith("Is Own Report:"):
            current["is_own_report"]=line.split(":",1)[1].strip().lower()=="true"
            if "lat" in current and "lon" in current and "ts" in current:
                match=None
                for index,item in enumerate(metadata):
                    if int(item.get("ts",0))==int(current["ts"]) and str(item.get("status"))==str(current.get("status")) and bool(item.get("is_own_report"))==bool(current["is_own_report"]):
                        match=metadata.pop(index)
                        break
                if match is None and metadata:
                    match=metadata.pop(0)
                if match is not None:
                    current["acc"]=float(match.get("accuracy",0) or 0)
                if semantic:
                    current["semantic"]=semantic
                reports.append(current)
            current={}
            semantic=""
    return reports

def probe_battery_fields(message, prefix="", depth=0, out=None):
    """Best-effort protobuf introspection; never invent a battery value."""
    out=[] if out is None else out
    if depth > 5 or len(out) >= 24 or message is None or not hasattr(message, "ListFields"):
        return out
    try:
        fields=message.ListFields()
    except Exception:
        return out
    for field,value in fields:
        path=(prefix+"." if prefix else "")+field.name
        if getattr(field,"message_type",None) is not None:
            if getattr(field,"label",None)==getattr(field,"LABEL_REPEATED",3):
                for index,item in enumerate(list(value)[:8]):
                    probe_battery_fields(item,f"{path}[{index}]",depth+1,out)
            else:
                probe_battery_fields(value,path,depth+1,out)
            continue
        low=path.lower()
        if "battery" not in low and "charge" not in low:
            continue
        item={"path":path}
        try:
            if getattr(field,"enum_type",None) is not None:
                enum_value=field.enum_type.values_by_number.get(int(value))
                item["value"]=int(value)
                item["name"]=enum_value.name if enum_value else str(value)
            elif isinstance(value,(int,float,bool,str)):
                item["value"]=value
            else:
                item["value"]=str(value)[:120]
        except Exception:
            item["value"]=str(value)[:120]
        out.append(item)
        if len(out)>=24:
            break
    return out

def list_devices():
    from NovaApi.ListDevices.nbe_list_devices import request_device_list
    from ProtoDecoders import DeviceUpdate_pb2
    from ProtoDecoders.decoder import parse_device_list_protobuf
    payload=request_device_list()
    if not payload:
        raise RuntimeError("empty_device_response")
    result=[]
    parsed=parse_device_list_protobuf(payload)
    for device in parsed.deviceMetadata:
        identifiers=device.identifierInformation.phoneInformation.canonicIds.canonicId if device.identifierInformation.type==DeviceUpdate_pb2.IDENTIFIER_ANDROID else device.identifierInformation.canonicIds.canonicId
        registration=device.information.deviceRegistration
        try:
            device_type=DeviceUpdate_pb2.SpotDeviceType.Name(registration.deviceTypeInformation.deviceType)
        except Exception:
            device_type=str(registration.deviceTypeInformation.deviceType)
        for identifier in identifiers:
            result.append({
                "id":identifier.id,
                "name":device.userDefinedDeviceName or identifier.id,
                "manufacturer":registration.manufacturer or "",
                "model":registration.model or "",
                "fast_pair_model_id":registration.fastPairModelId or "",
                "device_type":device_type,
                "image_url":device.imageInformation.imageUrl or "",
                "custom_mcu":str(registration.fastPairModelId or "")=="003200",
                "battery_probe":probe_battery_fields(device),
            })
    return result

def start_fcm_listener(receiver, callback, registration_timeout=22, ready_timeout=24):
    """Start upstream FCM without racing the Nova action against MCS login."""
    try:
        receiver.pc.config.connection_retry_count=2
        receiver.pc.config.start_seconds_before_retry_connect=1.25
        receiver.pc.config.abort_on_sequential_error_count=2
    except Exception:
        pass
    holder={}
    registered=threading.Event()
    def register():
        loop=asyncio.new_event_loop()
        receiver._uts_registration_loop=loop
        asyncio.set_event_loop(loop)
        try:
            holder["token"]=receiver.register_for_location_updates(callback)
        except BaseException as exc:
            holder["error"]=exc
        finally:
            registered.set()
        # Older upstream revisions schedule pc.start() and immediately return
        # from run_until_complete. Keep that exact loop alive so the MCS socket
        # can actually reach RUNNING; newer revisions use their own loop and
        # simply leave this compatibility loop idle.
        if holder.get("error") is None:
            try:
                asyncio.set_event_loop(loop)
                loop.run_forever()
            finally:
                try:
                    pending=asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending,return_exceptions=True))
                    loop.close()
                except Exception:
                    pass
    threading.Thread(target=register,daemon=True,name="uts-fcm-register").start()
    if not registered.wait(max(5,float(registration_timeout))):
        raise RuntimeError("fcm_registration_timeout")
    if holder.get("error") is not None:
        raise holder["error"]
    deadline=time.monotonic()+max(5,float(ready_timeout))
    while time.monotonic()<deadline:
        try:
            if receiver.pc.is_started():
                return holder.get("token")
        except Exception:
            pass
        time.sleep(0.1)
    state_name=str(getattr(receiver.pc,"run_state","unknown"))[-80:]
    raise RuntimeError("fcm_listener_not_ready:"+state_name)

def stop_fcm_listener(receiver):
    """Stop on the loop that owns FCM and close compatibility loop resources."""
    own_loop=getattr(receiver,"_loop",None)
    registration_loop=getattr(receiver,"_uts_registration_loop",None)
    target=own_loop if own_loop is not None and own_loop.is_running() else registration_loop
    if target is not None and target.is_running():
        try:
            future=asyncio.run_coroutine_threadsafe(receiver.pc.stop(),target)
            future.result(timeout=5)
        except Exception:
            pass
    else:
        try:
            receiver.stop_listening()
        except Exception:
            pass
    try:
        receiver._listening=False
    except Exception:
        pass
    for loop in (own_loop,registration_loop):
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass

def decrypt_update_reports(update, registration=None):
    """Read protobuf values directly; one corrupt report cannot discard a batch."""
    import hashlib
    from NovaApi.ExecuteAction.LocateTracker import decrypt_locations as decryptor
    from ProtoDecoders import DeviceUpdate_pb2, Common_pb2
    locations = update.deviceMetadata.information.locationInformation.reports.recentLocationAndNetworkLocations
    pairs = list(zip(locations.networkLocations, locations.networkLocationTimestamps))
    if locations.HasField('recentLocation'):
        pairs.append((locations.recentLocation, locations.recentLocationTimestamp))
    pairs = [(loc, stamp) for loc, stamp in pairs if loc.status != Common_pb2.Status.SEMANTIC]
    if not pairs:
        return [], 0
    registration = registration or update.deviceMetadata.information.deviceRegistration
    identity_key = decryptor.retrieve_identity_key(registration)
    is_mcu = decryptor.is_mcu_tracker(registration)
    reports, failed = [], 0
    for location, stamp in pairs:
        try:
            encrypted = location.geoLocation.encryptedReport
            if not encrypted.publicKeyRandom:
                raw = decryptor.decrypt_aes_gcm(hashlib.sha256(identity_key).digest(), encrypted.encryptedLocation)
            else:
                offset = 0 if is_mcu else location.geoLocation.deviceTimeOffset
                raw = decryptor.decrypt(identity_key, encrypted.encryptedLocation, encrypted.publicKeyRandom, offset)
            decoded = DeviceUpdate_pb2.Location()
            decoded.ParseFromString(raw)
            reports.append({'lat': decoded.latitude / 1e7, 'lon': decoded.longitude / 1e7,
                            'alt': decoded.altitude, 'ts': int(stamp.seconds),
                            'acc': float(location.geoLocation.accuracy), 'status': int(location.status),
                            'is_own_report': bool(encrypted.isOwnReport)})
        except Exception:
            failed += 1
    return reports, failed


class GoogleResponseWindow:
    """Thread-safe, bounded collection of all correlated FCM response packets."""
    def __init__(self, request_uuid):
        self.request_uuid = request_uuid
        self.condition = threading.Condition()
        self.packets = []
        self.seen = set()
        self.last_location_packet = None

    def add(self, parsed):
        if parsed.fcmMetadata.requestUuid != self.request_uuid:
            return
        key = parsed.SerializeToString()
        with self.condition:
            if key in self.seen or len(self.packets) >= 256:
                return
            self.seen.add(key)
            self.packets.append(parsed)
            locations = parsed.deviceMetadata.information.locationInformation.reports.recentLocationAndNetworkLocations
            if locations.networkLocations or locations.HasField('recentLocation'):
                self.last_location_packet = time.monotonic()
            self.condition.notify_all()

    def collect(self, timeout, settle=4):
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                now = time.monotonic()
                finish = min(deadline, self.last_location_packet + settle) if self.last_location_packet is not None else deadline
                if now >= finish:
                    return list(self.packets)
                self.condition.wait(finish - now)


def locate(payload):
    from Auth.fcm_receiver import FcmReceiver
    from NovaApi.ExecuteAction.LocateTracker.location_request import create_location_request
    from NovaApi.nova_request import nova_request
    from NovaApi.scopes import NOVA_ACTION_API_SCOPE
    from NovaApi.util import generate_random_uuid
    from ProtoDecoders.decoder import parse_device_update_protobuf
    request_uuid = generate_random_uuid()
    window = GoogleResponseWindow(request_uuid)
    def handle_location_response(response):
        try:
            window.add(parse_device_update_protobuf(response))
        except Exception:
            pass  # A malformed packet must not terminate the stream.
    receiver = FcmReceiver()
    try:
        fcm_token = start_fcm_listener(receiver, handle_location_response,
                                      payload.get('fcm_registration_timeout', 22), payload.get('fcm_ready_timeout', 24))
        hex_payload = create_location_request(payload['device_id'], fcm_token, request_uuid)
        import importlib
        nova_module = importlib.import_module('NovaApi.nova_request')
        original_post = nova_module.requests.post
        def bounded_post(*args, **kwargs):
            kwargs.setdefault('timeout', (10, 20))
            return original_post(*args, **kwargs)
        nova_module.requests.post = bounded_post
        try:
            action_result = nova_request(NOVA_ACTION_API_SCOPE, hex_payload)
        finally:
            nova_module.requests.post = original_post
        if action_result is None:
            raise RuntimeError('nova_action_failed')
        updates = window.collect(max(10, float(payload.get('fcm_response_timeout', 48))))
        if not updates:
            if not receiver.pc.is_started():
                raise RuntimeError('fcm_listener_disconnected')
            raise RuntimeError('fcm_response_timeout')
        # A later packet can omit key metadata supplied by an earlier packet.
        registration = next((item.deviceMetadata.information.deviceRegistration for item in reversed(updates)
                             if item.deviceMetadata.information.deviceRegistration.encryptedUserSecrets.encryptedIdentityKey), None)
        reports, errors, battery = [], 0, []
        for update in updates:
            battery.extend(probe_battery_fields(update))
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    batch, failed = decrypt_update_reports(update, registration)
                reports.extend(batch)
                errors += failed
            except (Exception, SystemExit):
                errors += 1
        if errors and not reports:
            raise RuntimeError('google_decryption_failed:encrypted_reports_received')
        unique = {(r['ts'], r['lat'], r['lon'], r['acc'], r['is_own_report']): r for r in reports}
        return {'reports': sorted(unique.values(), key=lambda r: r['ts']), 'battery_probe': battery[:24],
                'transport': 'fcm_ready', 'response_packets': len(updates), 'decryption_failures': errors}
    finally:
        stop_fcm_listener(receiver)

def refresh_fcm():
    from Auth.fcm_receiver import FcmReceiver
    receiver=FcmReceiver()
    start_fcm_listener(receiver,lambda *_args, **_kwargs: None,22,24)
    android_id=receiver.get_android_id()
    stop_fcm_listener(receiver)
    return str(android_id or "")

def recreate_fcm():
    """Force a new GCM/FCM identity instead of accepting a stale check-in."""
    from Auth.fcm_receiver import FcmReceiver
    from Auth.firebase_messaging.fcmregister import FcmRegister
    try:
        from aiohttp import ClientTimeout
    except Exception:
        ClientTimeout=None
    receiver=FcmReceiver()
    async def force_registration():
        config=getattr(receiver.pc,"fcm_config",None) or getattr(receiver.pc,"config",None)
        if config is None:
            raise RuntimeError("fcm_recreate_missing_config")
        # Harmless on older dataclasses and consumed natively by newer ones.
        config.android_package="com.google.android.apps.adm"
        config.android_cert_sha1="38918a453d07199354f8b19af05ec6562ced5788"
        callback=getattr(receiver,"_on_credentials_updated",None)
        registration=FcmRegister(config,None,callback)
        if ClientTimeout is not None:
            registration.CLIENT_TIMEOUT=ClientTimeout(total=25)
        try:
            credentials=await asyncio.wait_for(registration.register(),timeout=70)
        finally:
            close=getattr(registration,"close",None)
            if close:
                result=close()
                if asyncio.iscoroutine(result):
                    await result
        if not isinstance(credentials,dict) or not credentials.get("fcm") or not credentials.get("gcm"):
            raise RuntimeError("fcm_recreate_invalid_credentials")
        receiver.credentials=credentials
        receiver.pc.credentials=credentials
        receiver._on_credentials_updated(credentials)
        return credentials
    credentials=asyncio.run(force_registration())
    return str(credentials.get("gcm",{}).get("android_id") or "")

try:
    request=json.loads(sys.stdin.read() or "{}")
    operation=request.get("operation")
    if operation=="list":
        quiet=io.StringIO()
        with contextlib.redirect_stdout(quiet),contextlib.redirect_stderr(quiet):
            devices=list_devices()
        emit({"ok":True,"devices":devices})
    elif operation=="locate":
        located=locate(request)
        emit({"ok":True,**located})
    elif operation=="refresh_fcm":
        quiet=io.StringIO()
        with contextlib.redirect_stdout(quiet),contextlib.redirect_stderr(quiet):
            android_id=refresh_fcm()
        emit({"ok":True,"android_id":android_id})
    elif operation=="recreate_fcm":
        quiet=io.StringIO()
        with contextlib.redirect_stdout(quiet),contextlib.redirect_stderr(quiet):
            android_id=recreate_fcm()
        emit({"ok":True,"android_id":android_id,"recreated":True})
    else:
        emit({"ok":False,"error":"unsupported_operation","detail":str(operation or "")})
except BaseException as exc:
    detail=str(exc or "")[:800]
    trace=" | ".join(traceback.format_exc().splitlines()[-5:])[:1200]
    emit({"ok":False,"error":type(exc).__name__,"detail":detail,"trace":trace})
'''


# ════════════════════════════════════════════════════════════════════════════
#  Zustand & Scheduler
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class State:
    store: Store
    hub: Hub
    args: argparse.Namespace
    creds: Credentials
    webauthn: WebAuthn
    apple: Any = None
    registry: Any = None
    notifier: Any = None
    alerts: Any = None
    online: Any = None
    samsung: Any = None
    google: Any = None
    poll_event: asyncio.Event = field(default_factory=asyncio.Event)
    poll_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    waiters: list = field(default_factory=list)
    status: dict = field(default_factory=lambda: {"polling": False, "last_poll": None, "next_poll": None,
                                                  "last_error": None, "last_new": 0, "last_mode": None})
    login_failures: dict = field(default_factory=dict)
    link_codes: dict = field(default_factory=dict)

    def wake(self, device_ids: list[str] | None = None, full: bool = False) -> asyncio.Future:
        if self.registry:
            for t in self.registry.tracked.values():
                if device_ids is None or t.id in device_ids:
                    t.last_quick = 0.0
                    if full:  # gründlich: Schnell + 24 h + 7 Tage in EINER gebündelten Abfrage
                        t.last_full = 0.0
                        t.last_day = 0.0
        fut = asyncio.get_running_loop().create_future()
        self.waiters.append(fut)
        self.poll_event.set()
        return fut

    def set_status(self, **kw: Any) -> None:
        self.status.update(kw)
        self.hub.publish("status", self.public_status())

    def public_status(self) -> dict:
        s = self.store.settings()
        return {**self.status, "stats": self.store.stats(), "version": VERSION, "demo": self.args.demo,
                "server_time": now(), "apple": self.apple.status() if self.apple else {"state": "demo"},
                "networks": networks_summary(self),
                "devices": len(self.registry.tracked) if self.registry else 0,
                "poll_interval": s["poll_interval"], "retention_days": s["retention_days"]}


async def run_poll(st: State, plan: list[tuple[Tracked, str]]) -> int:
    s = st.store.settings()
    started = now()
    total_new = 0
    err = None
    keys = reqs = 0
    st.set_status(polling=True)
    try:
        ranges = [(t, *index_range(t.accessory, mode, float(s["quick_hours"]))) for t, mode in plan]
        async with st.poll_lock:
            results, keys, reqs = await fetch_combined(st.apple.account, ranges)
        for t, mode in plan:
            t.errors = 0
            ts_now = now()
            t.last_quick = ts_now
            if mode in ("day", "full"):
                t.last_day = ts_now
            if mode == "full":
                t.last_full = ts_now
            items = [report_to_dict(r) for r in results.get(t.id, [])]
            prev = st.store.newest_ts(t.id)
            new = st.store.insert_reports(t.id, items)
            if new:
                total_new += len(new)
                log.info("%s: %d neue(r) Bericht(e) [%s]", t.id[:8], len(new), mode)
                st.hub.publish("reports", {"device_id": t.id, "reports": new})
                await st.alerts.on_reports(t.id, new, prev)
        st.registry.save_changed()
        st.apple.save()
        if total_new:
            with contextlib.suppress(Exception):
                await check_case_alerts(st)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        log.warning("Abruf fehlgeschlagen: %s", err)
        for t, _ in plan:
            t.errors += 1
            t.last_quick = now()
        from findmy.errors import UnauthorizedError
        if isinstance(e, UnauthorizedError):
            st.apple.error = "Apple-Sitzung abgelaufen – bitte neu anmelden."
    finally:
        modes = ",".join(sorted({m for _, m in plan}))
        st.store.log_poll(started_at=started, duration=now() - started, mode=modes, devices=len(plan),
                          keys=keys, requests=reqs, new_reports=total_new, error=err)
        st.set_status(polling=False, last_poll=now(), last_error=err, last_new=total_new, last_mode=modes)
        if total_new:
            st.hub.publish("devices", {"devices": st.store.devices()})
    return total_new


async def scheduler(st: State) -> None:
    last_purge = last_offline = 0.0
    while True:
        s = st.store.settings()
        t0 = now()
        plan: list[tuple[Tracked, str]] = []
        result = {"new": 0, "polled": 0, "error": None}
        if st.apple.logged_in and s["networks"]["apple"].get("enabled", True):
            enabled = {d["id"]: d for d in st.store.devices() if d["enabled"]}
            for t in st.registry.tracked.values():
                d = enabled.get(t.id)
                if not d:
                    continue
                fast = d["lost"].get("enabled") or d["alerts"]["guard"].get("enabled")
                backoff = min(2 ** t.errors, 16)
                interval = (s["lost_poll_interval"] if fast else s["poll_interval"]) * backoff
                if t0 - t.last_full >= s["full_sweep_minutes"] * 60:
                    plan.append((t, "full"))
                elif t0 - t.last_day >= s["day_sweep_minutes"] * 60:
                    plan.append((t, "day"))
                elif t0 - t.last_quick >= interval:
                    plan.append((t, "quick"))
            if plan:
                result["new"] = await run_poll(st, plan)
                result["polled"] = len(plan)
                result["error"] = st.status.get("last_error")
        elif st.waiters and not s["networks"]["apple"].get("enabled", True):
            result["error"] = None
        elif st.waiters and st.registry.tracked:
            result["error"] = "Nicht bei Apple angemeldet"
        waiters, st.waiters = st.waiters, []
        for w in waiters:
            if not w.done():
                w.set_result(result)
        if t0 - last_offline > 60:
            last_offline = t0
            with contextlib.suppress(Exception):
                await st.alerts.check_offline()
            with contextlib.suppress(Exception):
                await check_case_alerts(st)
            with contextlib.suppress(Exception):
                for se in st.store.recordings():
                    if se["stopped_ts"] is None and se["end_ts"] and se["end_ts"] <= now():
                        st.store.update_recording(se["id"], stopped_ts=se["end_ts"])
                        st.hub.publish("apple_devices", {"changed": True})
        if t0 - last_purge > 3600:
            last_purge = t0
            n = st.store.purge(s)
            if n:
                log.info("Aufbewahrung: %d alte Berichte gelöscht.", n)
        st.set_status(next_poll=now() + 5)
        st.poll_event.clear()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(st.poll_event.wait(), timeout=5)


# ── Demo-Modus ────────────────────────────────────────────────────────────────

class DemoApple:
    logged_in = True
    account = None
    error = None

    def status(self) -> dict:
        return {"state": "logged_in", "account_name": "demo@example.com", "first_name": "Demo",
                "last_name": "Modus", "error": None}

    def save(self) -> None: ...


async def demo_setup(st: State) -> None:
    st.apple = DemoApple()
    # Demo-Apple-Geräte (online)
    for aid, name, cls, model, pos, bl in [("demo-iphone", "iPhone von Demo", "iPhone", "iPhone16,1", (52.5163, 13.3777), 0.82),
                                          ("demo-mac", "MacBook Pro", "MacBookPro", "Mac15,9", (52.5250, 13.4100), 0.47),
                                          ("demo-airpods", "AirPods Pro", "Accessory", "AirPodsPro", (52.5120, 13.3900), None)]:
        st.store.apple_upsert_fmip({"id": aid, "name": name, "model": model, "display_name": name,
                                    "device_class": cls, "battery_level": bl, "battery_status": "NotCharging",
                                    "device_status": "200",
                                    "online": {"lat": pos[0], "lon": pos[1], "accuracy": 35,
                                               "ts": now() - random.randint(60, 1800),
                                               "position_type": "Wifi", "is_old": False, "inaccurate": False}})
    seeds = [("demo-keys", "Schlüssel", "🔑", (52.5200, 13.4050), "apple", "AirTag"),
             ("demo-bag", "Rucksack", "🎒", (52.5310, 13.3850), "apple", "AirTag"),
             ("demo-bike", "Fahrrad", "🚲", (52.5080, 13.4300), "apple", "AirTag"),
             ("demo-wallet", "Geldbörse", "👛", (52.5000, 13.3600), "google", "Pebblebee Clip"),
             ("demo-suitcase", "Koffer", "🧳", (52.5400, 13.4200), "samsung", "Galaxy SmartTag2")]
    for did, name, emoji, pos, network, model in seeds:
        st.store.upsert_device(did, name, model, emoji, None, "airtag" if network == "apple" else "tracker")
        st.store.update_device(did, network=network, ext_id=None if network == "apple" else did)
        t = Tracked(did, {"pos": list(pos), "hdg": random.random() * 6.28})
        st.registry.tracked[did] = t
        if st.store.newest_ts(did):
            continue
        items, lat, lon = [], *pos
        base = now() - 7 * 86400
        for i in range(400):
            lat += math.cos(i / 9) * 0.0011 + random.uniform(-4e-4, 4e-4)
            lon += math.sin(i / 13) * 0.0015 + random.uniform(-4e-4, 4e-4)
            items.append({"ts": base + i * 1500 + random.randint(0, 600), "lat": lat, "lon": lon,
                          "accuracy": random.randint(5, 60), "confidence": 2, "status": 0x10,
                          "battery": "full"})
        st.store.insert_reports(did, items)
        t.accessory["pos"] = [lat, lon]


async def demo_scheduler(st: State) -> None:
    while True:
        total = 0
        st.set_status(polling=True)
        for t in st.registry.tracked.values():
            if random.random() < 0.35 and not st.waiters:
                continue
            n = random.choice([1, 1, 1, 2, 4])
            p = t.accessory["pos"]
            items = []
            for i in range(n):
                t.accessory["hdg"] += random.uniform(-0.6, 0.6)
                p[0] += math.cos(t.accessory["hdg"]) * 0.0007
                p[1] += math.sin(t.accessory["hdg"]) * 0.001
                items.append({"ts": now() - (n - i) * random.randint(60, 600), "lat": p[0], "lon": p[1],
                              "accuracy": random.randint(4, 80), "confidence": 2, "status": 0x10,
                              "battery": "full"})
            prev = st.store.newest_ts(t.id)
            new = st.store.insert_reports(t.id, items)
            if new:
                total += len(new)
                st.hub.publish("reports", {"device_id": t.id, "reports": new})
                await st.alerts.on_reports(t.id, new, prev)
        st.set_status(polling=False, last_poll=now(), last_new=total, last_mode="demo")
        if total:
            st.hub.publish("devices", {"devices": st.store.devices()})
        waiters, st.waiters = st.waiters, []
        for w in waiters:
            if not w.done():
                w.set_result({"new": total, "polled": len(st.registry.tracked), "error": None})
        st.poll_event.clear()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(st.poll_event.wait(), timeout=st.store.settings()["poll_interval"])


# ════════════════════════════════════════════════════════════════════════════
#  HTTP-API
# ════════════════════════════════════════════════════════════════════════════

PUBLIC = {"/", "/auth/app", "/manifest.webmanifest", "/icon.svg", "/api/health", "/api/auth/login",
          "/api/auth/passkey/login/options", "/api/auth/passkey/login/verify", "/api/auth/link/redeem"}


def client_ip(req: web.Request) -> str:
    fwd = req.headers.get("X-Forwarded-For")
    return (fwd.split(",")[0].strip() if fwd and req.app["trust_proxy"] else req.remote) or "?"


def rp_id_for(req: web.Request) -> str:
    host = req.headers.get("X-Forwarded-Host") if req.app["trust_proxy"] else None
    host = (host or req.host or "localhost").split(",")[0].strip()
    if host.startswith("["):
        return host[1:host.index("]")]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def token_from(req: web.Request) -> str | None:
    h = req.headers.get("Authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return req.cookies.get("fmu_token") or req.query.get("token")


def jerr(status: int, msg: str, **extra: Any) -> web.Response:
    return web.json_response({"ok": False, "error": msg, **extra}, status=status)


def _f(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def build_app(st: State) -> web.Application:
    @web.middleware
    async def auth_mw(req: web.Request, handler: Any) -> web.StreamResponse:
        if req.method == "OPTIONS":
            return web.Response(status=204)
        path = req.path
        if path in PUBLIC or not (path.startswith("/api/") or path.startswith("/export")):
            return await handler(req)
        tok = token_from(req)
        sess = st.store.check_session(tok) if tok else None
        if not sess:
            return jerr(401, "Nicht angemeldet")
        req["session"] = sess
        return await handler(req)

    @web.middleware
    async def error_mw(req: web.Request, handler: Any) -> web.StreamResponse:
        try:
            resp = await handler(req)
        except web.HTTPException:
            raise
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            log.debug("Anfragefehler %s: %s", req.path, e, exc_info=True)
            resp = jerr(400, str(e) or type(e).__name__)
        except Exception as e:  # noqa: BLE001
            log.exception("Fehler bei %s", req.path)
            resp = jerr(500, f"{type(e).__name__}: {e}")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    app = web.Application(middlewares=[error_mw, auth_mw], client_max_size=20 * 1024 ** 2)
    app["trust_proxy"] = st.args.trust_proxy
    r = app.router

    def new_session(req: web.Request, label: str, kind: str) -> str:
        tok = secrets.token_urlsafe(32)
        st.store.add_session(tok, label, client_ip(req), kind)
        return tok

    def session_response(req: web.Request, tok: str) -> web.Response:
        resp = web.json_response({"ok": True, "token": tok, "username": st.creds.username,
                                  "password_is_generated": st.creds.data.get("password_is_generated")})
        resp.set_cookie("fmu_token", tok, httponly=True, samesite="Strict", max_age=90 * 86400,
                        secure=req.secure)
        return resp

    def throttle(req: web.Request) -> None:
        ip = client_ip(req)
        fails = [t for t in st.login_failures.get(ip, []) if now() - t < 600]
        st.login_failures[ip] = fails
        if len(fails) >= 8:
            raise web.HTTPTooManyRequests(text=json.dumps({"ok": False, "error": "Zu viele Versuche – "
                                                           "bitte 10 Minuten warten."}),
                                          content_type="application/json")

    def fail(req: web.Request) -> None:
        st.login_failures.setdefault(client_ip(req), []).append(now())

    # --- Web --------------------------------------------------------------------
    async def index(_: web.Request) -> web.Response:
        return web.Response(text=WEB_HTML, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def manifest(_: web.Request) -> web.Response:
        return web.json_response({"name": APP_NAME, "short_name": "FindMy Ultra", "start_url": "/",
                                  "display": "standalone", "background_color": "#000000",
                                  "theme_color": "#000000",
                                  "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]})

    async def icon(_: web.Request) -> web.Response:
        return web.Response(text=ICON_SVG, content_type="image/svg+xml")

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True, "app": APP_NAME, "version": VERSION, "demo": st.args.demo,
                                  "totp": st.creds.totp_enabled,
                                  "passkeys": len(st.creds.data.get("passkeys", []))})

    # --- Auth ---------------------------------------------------------------------
    async def login(req: web.Request) -> web.Response:
        throttle(req)
        b = await req.json()
        if not st.creds.check(b.get("username", ""), b.get("password", "")):
            fail(req)
            await asyncio.sleep(0.5)
            return jerr(401, "Benutzername oder Passwort falsch")
        if st.creds.totp_enabled:
            code = b.get("totp") or ""
            if not code:
                return web.json_response({"ok": False, "need_totp": True, "error": "2FA-Code erforderlich"},
                                         status=401)
            if not totp_verify(st.creds.data["totp"]["secret"], code):
                fail(req)
                return jerr(401, "2FA-Code falsch", need_totp=True)
        tok = new_session(req, b.get("label") or req.headers.get("User-Agent", "")[:60], "password")
        return session_response(req, tok)

    async def logout(req: web.Request) -> web.Response:
        st.store.delete_session(req["session"]["token_hash"])
        resp = web.json_response({"ok": True})
        resp.del_cookie("fmu_token")
        return resp

    async def me(req: web.Request) -> web.Response:
        c = st.creds.data
        return web.json_response({
            "username": c["username"], "password_is_generated": c.get("password_is_generated", False),
            "totp_enabled": st.creds.totp_enabled,
            "passkeys": [{k: p.get(k) for k in ("id", "name", "created", "last_used", "rp_id")}
                         for p in c.get("passkeys", [])],
            "sessions": [{"id": s["token_hash"][:16], "label": s["label"], "ip": s["ip"],
                          "created": s["created"], "last_used": s["last_used"], "kind": s["kind"],
                          "current": s["token_hash"] == req["session"]["token_hash"]}
                         for s in st.store.sessions()],
        })

    async def change_password(req: web.Request) -> web.Response:
        b = await req.json()
        if not verify_password(b.get("current", ""), st.creds.data["password"]):
            return jerr(403, "Aktuelles Passwort falsch")
        if st.creds.totp_enabled and not totp_verify(st.creds.data["totp"]["secret"], b.get("totp", "")):
            return jerr(403, "2FA-Code falsch", need_totp=True)
        new = b.get("new", "")
        if len(new) < 8:
            return jerr(400, "Neues Passwort: mindestens 8 Zeichen")
        st.creds.set_password(new, b.get("username") or None)
        if b.get("logout_others", True):
            st.store.delete_all_sessions(req["session"]["token_hash"])
        return web.json_response({"ok": True})

    async def totp_setup(req: web.Request) -> web.Response:
        secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        st.creds.data.setdefault("totp", {})["pending"] = secret
        st.creds.save()
        label = quote(f"{APP_NAME}:{st.creds.username}")
        uri = f"otpauth://totp/{label}?secret={secret}&issuer={quote(APP_NAME)}&algorithm=SHA1&digits=6&period=30"
        return web.json_response({"ok": True, "secret": secret, "uri": uri})

    async def totp_enable(req: web.Request) -> web.Response:
        b = await req.json()
        t = st.creds.data.setdefault("totp", {})
        if not t.get("pending") or not totp_verify(t["pending"], b.get("code", "")):
            return jerr(400, "Code ungültig")
        t.update(enabled=True, secret=t.pop("pending"))
        st.creds.save()
        return web.json_response({"ok": True})

    async def totp_disable(req: web.Request) -> web.Response:
        b = await req.json()
        if not verify_password(b.get("password", ""), st.creds.data["password"]):
            return jerr(403, "Passwort falsch")
        st.creds.data["totp"] = {"enabled": False, "secret": None, "pending": None}
        st.creds.save()
        return web.json_response({"ok": True})

    async def pk_reg_options(req: web.Request) -> web.Response:
        return web.json_response(st.webauthn.register_options(rp_id_for(req)))

    async def pk_reg_verify(req: web.Request) -> web.Response:
        pk = st.webauthn.register_verify(await req.json(), rp_id_for(req))
        return web.json_response({"ok": True, "id": pk["id"], "name": pk["name"]})

    async def pk_login_options(req: web.Request) -> web.Response:
        throttle(req)
        if not st.creds.data.get("passkeys"):
            return jerr(404, "Noch kein Passkey eingerichtet")
        return web.json_response(st.webauthn.login_options(rp_id_for(req)))

    async def pk_login_verify(req: web.Request) -> web.Response:
        throttle(req)
        try:
            pk = st.webauthn.login_verify(await req.json(), rp_id_for(req))
        except Exception as e:  # noqa: BLE001
            fail(req)
            return jerr(401, f"Passkey abgelehnt: {e}")
        tok = new_session(req, f"Passkey {pk['name']}", "passkey")
        return session_response(req, tok)

    async def pk_delete(req: web.Request) -> web.Response:
        pid = req.match_info["pid"]
        st.creds.data["passkeys"] = [p for p in st.creds.data.get("passkeys", []) if p["id"] != pid]
        st.creds.save()
        return web.json_response({"ok": True})

    async def link_create(req: web.Request) -> web.Response:
        code = secrets.token_urlsafe(24)
        st.link_codes = {k: v for k, v in st.link_codes.items() if v > now()}
        st.link_codes[code] = now() + 120
        return web.json_response({"ok": True, "code": code, "expires_in": 120})

    async def link_redeem(req: web.Request) -> web.Response:
        b = await req.json()
        exp = st.link_codes.pop(b.get("code", ""), None)
        if not exp or exp < now():
            return jerr(401, "Link abgelaufen")
        return session_response(req, new_session(req, "App-Verknüpfung", "link"))

    async def session_delete(req: web.Request) -> web.Response:
        sid = req.match_info["sid"]
        for s in st.store.sessions():
            if s["token_hash"].startswith(sid):
                st.store.delete_session(s["token_hash"])
        return web.json_response({"ok": True})

    # --- Status / Settings ----------------------------------------------------------
    async def status(_: web.Request) -> web.Response:
        return web.json_response(st.public_status())

    async def get_settings(_: web.Request) -> web.Response:
        return web.json_response(st.store.settings())

    async def put_settings(req: web.Request) -> web.Response:
        b = await req.json()
        s = deep_merge(st.store.settings(), b)
        s["poll_interval"] = max(20, int(s["poll_interval"]))
        s["lost_poll_interval"] = max(10, int(s["lost_poll_interval"]))
        s["quick_hours"] = max(1, min(48, float(s["quick_hours"])))
        s["day_sweep_minutes"] = max(2, int(s["day_sweep_minutes"]))
        s["full_sweep_minutes"] = max(10, int(s["full_sweep_minutes"]))
        s["retention_days"] = max(0, int(s["retention_days"]))
        nets = s["networks"]
        for n in NETWORKS:
            nets[n]["enabled"] = bool(nets[n].get("enabled", True))
        if nets["google"].get("server_mode") not in ("auto", "always", "off"):
            nets["google"]["server_mode"] = "auto"
        nets["google"]["interval"] = max(300, int(nets["google"].get("interval", 900)))
        nets["google"]["app_grace_min"] = max(5, int(nets["google"].get("app_grace_min", 30)))
        nets["samsung"]["interval"] = max(30, int(nets["samsung"].get("interval", 120)))
        nets["samsung"]["history"] = bool(nets["samsung"].get("history"))
        for obj in (st.samsung, st.google):
            if obj:
                obj.event.set()
        od = s["online_devices"]
        od["enabled"] = bool(od.get("enabled"))
        od["interval"] = max(30, int(od.get("interval", 120)))
        if st.online:
            st.online.event.set()
        sc = s["stays"]
        sc["radius_m"] = max(20.0, min(2000.0, float(sc["radius_m"])))
        sc["min_minutes"] = max(1.0, float(sc["min_minutes"]))
        sc["min_points"] = max(1, int(sc["min_points"]))
        sc["max_outliers"] = max(0, int(sc["max_outliers"]))
        sc["outlier_minutes"] = max(1.0, float(sc["outlier_minutes"]))
        sc["max_gap_hours"] = max(0.5, float(sc["max_gap_hours"]))
        sc["max_accuracy_m"] = max(20.0, float(sc["max_accuracy_m"]))
        sc["merge_minutes"] = max(0.0, float(sc["merge_minutes"]))
        bark = s["bark"]
        keys = []
        for k in bark.get("device_keys", []):
            k = str(k).strip()
            m = re.match(r"(https?://[^/]+)/([A-Za-z0-9]+)", k)
            if m:  # komplette Bark-URL eingefügt
                bark["server"], k = m.group(1), m.group(2)
            if k:
                keys.append(k)
        bark["device_keys"] = list(dict.fromkeys(keys))
        for z in s.get("zones", []):
            z.setdefault("id", secrets.token_hex(4))
            z["lat"], z["lon"], z["radius"] = float(z["lat"]), float(z["lon"]), float(z.get("radius", 150))
        st.store.save_settings(s)
        st.hub.publish("settings", s)
        st.poll_event.set()
        return web.json_response(s)

    async def bark_test(req: web.Request) -> web.Response:
        b = await req.json() if req.can_read_body else {}
        level = b.get("level", "active")
        ok, err = await st.notifier.send_bark(
            "FindMy Ultra – Test", f"Stufe: {level}. Wenn du das liest, klappt Bark! ✅", level,
            None, None, None, force=True)
        return web.json_response({"ok": ok, "error": err})

    async def notifications(req: web.Request) -> web.Response:
        return web.json_response({"notifications": st.store.notifications(
            int(req.query.get("limit", 200)), req.query.get("device"))})

    async def notifications_clear(_: web.Request) -> web.Response:
        st.store.db.execute("DELETE FROM notifications")
        st.store.db.commit()
        return web.json_response({"ok": True})

    # --- Apple -------------------------------------------------------------------------
    def need_real() -> None:
        if st.args.demo:
            raise ValueError("Im Demo-Modus nicht verfügbar")

    async def apple_status(_: web.Request) -> web.Response:
        return web.json_response(st.apple.status())

    async def apple_login(req: web.Request) -> web.Response:
        need_real()
        b = await req.json()
        if b.get("anisette_server") is not None:
            s = st.store.settings()
            s["anisette_server"] = b["anisette_server"].strip()
            st.store.save_settings(s)
        try:
            res = await st.apple.login(b["email"], b["password"])
        except ValueError as e:
            st.set_status()
            return jerr(503, str(e))
        except Exception as e:  # noqa: BLE001
            from findmy import InvalidCredentialsError
            text = str(e)
            if isinstance(e, InvalidCredentialsError) and "verification failed" in text.lower():
                msg = ("Apple hat die Anmeldung abgelehnt („Email verification failed“). Bitte prüfen, ob die "
                       "macOS-Komponente bereit ist, und es in ein paar Minuten noch einmal versuchen – nicht "
                       "mehrfach direkt hintereinander, sonst sperrt Apple das Konto vorübergehend.")
                st.apple.error = msg
                return jerr(401, msg)
            if isinstance(e, InvalidCredentialsError):
                return jerr(401, "Apple-ID oder Passwort falsch")
            if "503" in text:
                return jerr(502, "Apple-Anmeldeserver antwortet gerade nicht (503). Bitte später erneut versuchen.")
            return jerr(502, f"Apple-Anmeldung fehlgeschlagen: {type(e).__name__}: {e}")
        if res["state"] == "logged_in":
            st.wake(full=True)
        st.set_status()
        return web.json_response(res)

    async def apple_runtime_install(_: web.Request) -> web.Response:
        need_real()
        if not st.apple.runtime.check():
            st.apple.runtime.start_install()
        return web.json_response(st.apple.status())

    async def apple_2fa_request(req: web.Request) -> web.Response:
        need_real()
        b = await req.json()
        await st.apple.request_code(int(b.get("index", 0)))
        return web.json_response({"ok": True})

    async def apple_2fa_submit(req: web.Request) -> web.Response:
        need_real()
        b = await req.json()
        try:
            res = await st.apple.submit_code(int(b.get("index", 0)), str(b["code"]))
        except Exception as e:  # noqa: BLE001
            return jerr(400, f"Code abgelehnt: {e}")
        st.set_status()
        return web.json_response(res)

    async def apple_logout(_: web.Request) -> web.Response:
        need_real()
        await st.apple.logout()
        st.set_status()
        return web.json_response({"ok": True})

    # --- Geräte --------------------------------------------------------------------------
    async def devices(req: web.Request) -> web.Response:
        return web.json_response({"devices": st.store.devices(req.query.get("category"))})

    async def device_get(req: web.Request) -> web.Response:
        d = st.store.device_public(req.match_info["id"])
        return web.json_response(d) if d else jerr(404, "Unbekanntes Gerät")

    async def device_patch(req: web.Request) -> web.Response:
        did = req.match_info["id"]
        row = st.store.device_row(did)
        if not row:
            return jerr(404, "Unbekanntes Gerät")
        b = await req.json()
        upd: dict = {}
        for k in ("name", "emoji", "color"):
            if k in b and b[k] is not None:
                upd[k] = str(b[k])[:80]
        if "enabled" in b:
            upd["enabled"] = bool(b["enabled"])
        if "sort" in b:
            upd["sort"] = int(b["sort"])
        if "retention_days" in b:
            upd["retention_days"] = None if b["retention_days"] in (None, "", -1) else max(0, int(b["retention_days"]))
        if "alerts" in b:
            alerts = deep_merge(row["alerts"], b["alerts"])
            g = alerts["guard"]
            if b["alerts"].get("guard", {}).get("enabled") and g.get("lat") is None:
                last = st.store.device_public(did).get("last")
                if not last:
                    return jerr(400, "Kein Standort bekannt – Wache kann nicht scharf geschaltet werden")
                g.update(lat=last["lat"], lon=last["lon"])
            if b["alerts"].get("guard", {}).get("enabled"):
                g["armed_at"] = g.get("armed_at") or now()
            elif "guard" in b["alerts"] and not g.get("enabled"):
                g.update(lat=None, lon=None, armed_at=None)
            upd["alerts"] = alerts
        if "lost" in b:
            lost = deep_merge(row["lost"], b["lost"])
            if lost.get("enabled") and not row["lost"].get("enabled"):
                lost["since"] = now()
                state = row["state"]
                state["lost_found"] = False
                upd["state"] = state
            if not lost.get("enabled"):
                lost["since"] = None
            upd["lost"] = lost
        st.store.update_device(did, **upd)
        if "lost" in b and upd["lost"].get("enabled"):
            st.wake([did])
        d = st.store.device_public(did)
        st.hub.publish("device", d)
        return web.json_response(d)

    async def device_delete(req: web.Request) -> web.Response:
        did = req.match_info["id"]
        row = st.store.device_row(did)
        if row and row.get("network") in ("google", "samsung") and row.get("ext_id"):
            # sonst legt die nächste Synchronisierung den Tracker sofort wieder an
            set_network_ignored(st.store, row["network"], row["ext_id"], True)
        st.registry.remove(did)
        st.store.delete_device(did, keep_reports=req.query.get("keep_reports") == "1")
        st.hub.publish("devices", {"devices": st.store.devices()})
        return web.json_response({"ok": True})

    async def device_reports(req: web.Request) -> web.Response:
        q = req.query
        return web.json_response({"reports": st.store.reports(
            _f(q.get("since")), _f(q.get("until")), req.match_info["id"], int(q.get("limit", 50000)))})

    # --- Apple-Geräte -----------------------------------------------------------------
    def apple_list() -> dict:
        devs = [apple_device_public(st, d) for d in st.store.apple_rows()]
        return {"devices": devs, "online": st.online.status() if st.online else {"enabled": False}}

    async def apple_devices(_: web.Request) -> web.Response:
        return web.json_response(apple_list())

    async def apple_create_route(req: web.Request) -> web.Response:
        b = await req.json()
        mode = "airpods" if b.get("mode") == "airpods" else "device"
        aid = st.store.apple_create((b.get("name") or ("AirPods" if mode == "airpods" else "Gerät"))[:80],
                                    mode, b.get("device_class") or ("Accessory" if mode == "airpods" else None))
        st.hub.publish("apple_devices", {"changed": True})
        return web.json_response(apple_device_public(st, st.store.apple_row(aid)))

    async def apple_patch(req: web.Request) -> web.Response:
        aid = req.match_info["id"]
        row = st.store.apple_row(aid)
        if not row:
            return jerr(404, "Unbekanntes Gerät")
        b = await req.json()
        upd: dict = {}
        if "name" in b:
            upd["custom_name"] = (b["name"] or "").strip()[:80] or None
        if "emoji" in b:
            upd["emoji"] = (b["emoji"] or "")[:8] or None
        if "mode" in b and b["mode"] in ("device", "airpods"):
            upd["mode"] = b["mode"]
        if "hidden" in b:
            upd["hidden"] = bool(b["hidden"])
        if "sort" in b:
            upd["sort"] = int(b["sort"])
        if isinstance(b.get("settings"), dict):
            upd["settings"] = json.dumps(deep_merge(row["settings"], b["settings"]))
        if b.get("rearm"):
            upd["state"] = json.dumps({**(row.get("state") or {}), "fired": {}})
        st.store.apple_update(aid, **upd)
        st.hub.publish("apple_devices", {"changed": True})
        return web.json_response(apple_device_public(st, st.store.apple_row(aid)))

    def _unlink(row: dict, role: str) -> None:
        did = (row.get("links") or {}).pop(role, None)
        if did and did not in (row.get("links") or {}).values():
            st.registry.remove(did)
            st.store.delete_device(did)

    async def apple_delete_route(req: web.Request) -> web.Response:
        aid = req.match_info["id"]
        row = st.store.apple_row(aid)
        if not row:
            return jerr(404, "Unbekanntes Gerät")
        for role in list((row.get("links") or {}).keys()):
            _unlink(row, role)
        if row["kind"] == "fmip":
            st.store.apple_update(aid, hidden=True, links={})  # kommt sonst beim nächsten Abruf wieder
        else:
            st.store.apple_delete(aid)
        st.hub.publish("apple_devices", {"changed": True})
        return web.json_response({"ok": True})

    async def apple_offline_import(req: web.Request) -> web.Response:
        need_real()
        aid = req.match_info["id"]
        row = st.store.apple_row(aid)
        if not row:
            return jerr(404, "Unbekanntes Gerät")
        role = req.query.get("role", "main")
        if role not in ("main", *AIRPODS_ROLES):
            return jerr(400, "Rolle muss main, left, right oder case sein")
        raw, name = b"", "upload"
        if req.content_type.startswith("multipart/"):
            reader = await req.multipart()
            async for part in reader:
                if part.filename or part.name in ("file", "files"):
                    raw, name = await part.read(decode=True), part.filename or "upload"
                    break
        else:
            raw = await req.read()
        if not raw:
            return jerr(400, "Keine Datei erhalten")
        try:
            for acc, _meta in parse_key_file(raw, name):
                ex = st.store.device_row(accessory_id(acc))
                if ex and ex.get("category", "item") == "item":
                    return jerr(409, f"Diese Schlüsseldatei ist bereits als Objekt „{ex['name']}“ importiert. "
                                     "Entferne das Objekt zuerst, wenn sie zu diesem Gerät gehören soll.")
            added = st.registry.import_bytes(raw, name, category="apple_device")
        except Exception as e:  # noqa: BLE001
            return jerr(400, f"{type(e).__name__}: {e}")
        if not added:
            return jerr(400, "Keine Schlüssel in der Datei")
        new_id = added[0]["id"]
        links = row.get("links") or {}
        old = links.get(role)
        if old and old != new_id:
            _unlink(row, role)
            links = row.get("links") or {}
        links[role] = new_id
        st.store.apple_update(aid, links=links)
        label = {"main": "", "left": " (links)", "right": " (rechts)", "case": " (Case)"}[role]
        st.store.update_device(new_id, name=f"{row.get('custom_name') or row['name']}{label}")
        st.wake([new_id], full=True)
        st.hub.publish("apple_devices", {"changed": True})
        return web.json_response(apple_device_public(st, st.store.apple_row(aid)))

    async def apple_offline_remove(req: web.Request) -> web.Response:
        aid = req.match_info["id"]
        row = st.store.apple_row(aid)
        if not row:
            return jerr(404, "Unbekanntes Gerät")
        _unlink(row, req.match_info["role"])
        st.store.apple_update(aid, links=row.get("links") or {})
        st.hub.publish("apple_devices", {"changed": True})
        return web.json_response(apple_device_public(st, st.store.apple_row(aid)))

    async def apple_refresh(req: web.Request) -> web.Response:
        b = await req.json() if req.can_read_body else {}
        n = await st.online.refresh(force=True) if st.online and not st.args.demo else 0
        linked = [did for d in st.store.apple_rows() for did in (d.get("links") or {}).values()]
        aid = b.get("id")
        if aid:
            row = st.store.apple_row(aid)
            linked = list((row or {}).get("links", {}).values())
        res = {"new": 0}
        if linked:
            fut = st.wake(linked, full=bool(b.get("full", True)))
            with contextlib.suppress(asyncio.TimeoutError):
                res = await asyncio.wait_for(asyncio.shield(fut), timeout=float(b.get("timeout", 90)))
        return web.json_response({"ok": True, "online_devices": n, "new_offline": res.get("new", 0),
                                  "online_error": st.online.error if st.online else None, **apple_list()})

    async def apple_raw(req: web.Request) -> web.Response:
        r = st.store.db.execute("SELECT raw FROM apple_devices WHERE id=?", (req.match_info["id"],)).fetchone()
        if not r:
            return jerr(404, "Unbekanntes Gerät")
        return web.json_response({"raw": json.loads(r[0] or "{}")})

    async def apple_message(req: web.Request) -> web.Response:
        need_real()
        row = st.store.apple_row(req.match_info["id"])
        if not row or row["kind"] != "fmip":
            return jerr(400, "Nur bei online verbundenen Apple-Geräten möglich")
        b = await req.json()
        try:
            await st.online.send_message(row["id"], b.get("subject", ""), b.get("text", ""), bool(b.get("sound")))
        except Exception as e:  # noqa: BLE001
            return jerr(502, f"Nachricht fehlgeschlagen: {e}")
        return web.json_response({"ok": True})

    async def apple_lost(req: web.Request) -> web.Response:
        need_real()
        row = st.store.apple_row(req.match_info["id"])
        if not row or row["kind"] != "fmip":
            return jerr(400, "Nur bei online verbundenen Apple-Geräten möglich")
        b = await req.json()
        try:
            await st.online.lost_mode(row["id"], str(b.get("number", "")), b.get("text") or
                                      "Dieses Gerät wurde verloren. Bitte ruf mich an.")
        except Exception as e:  # noqa: BLE001
            return jerr(502, f"Verloren-Modus fehlgeschlagen: {e}")
        await st.online.refresh(force=True)
        return web.json_response({"ok": True})

    async def apple_sound(req: web.Request) -> web.Response:
        need_real()
        row = st.store.apple_row(req.match_info["id"])
        if not row or row["kind"] != "fmip":
            return jerr(400, "Ton nur bei online verbundenen Apple-Geräten möglich")
        try:
            await st.online.play_sound(row["id"])
        except Exception as e:  # noqa: BLE001
            return jerr(502, f"Ton fehlgeschlagen: {e}")
        return web.json_response({"ok": True})

    # --- Aufzeichnungen (Sessions) ------------------------------------------------------
    def _session_public(se: dict) -> dict:
        pts = session_points(st, se)
        on = sum(1 for p in pts if p["source"] == "online")
        return {**se, "points": len(pts), "online_points": on, "offline_points": len(pts) - on,
                "last_ts": pts[-1]["ts"] if pts else None}

    async def sessions_list(req: web.Request) -> web.Response:
        aid = req.match_info["id"]
        return web.json_response({"sessions": [_session_public(x) for x in st.store.recordings(aid)]})

    async def session_start(req: web.Request) -> web.Response:
        aid = req.match_info["id"]
        row = st.store.apple_row(aid)
        if not row:
            return jerr(404, "Unbekanntes Gerät")
        b = await req.json() if req.can_read_body else {}
        source = b.get("source") if b.get("source") in ("both", "offline", "online") else "both"
        if any(x["active"] for x in st.store.recordings(aid)):
            return jerr(409, "Für dieses Gerät läuft bereits eine Aufzeichnung.")
        end_ts = None
        if b.get("end_ts"):
            end_ts = float(b["end_ts"])
        elif b.get("duration_hours"):
            end_ts = now() + float(b["duration_hours"]) * 3600
        name = (b.get("name") or "").strip()[:80] or \
            f"Aufzeichnung {dt.datetime.now().strftime('%d.%m. %H:%M')}"
        sid = st.store.add_recording(aid, name, source, end_ts)
        linked = list((row.get("links") or {}).values())
        if linked and source != "online":
            st.wake(linked, full=True)
        if st.online:
            st.online.event.set()
        st.hub.publish("apple_devices", {"changed": True})
        return web.json_response(_session_public(st.store.recording(sid)))

    async def session_patch(req: web.Request) -> web.Response:
        sid = int(req.match_info["sid"])
        se = st.store.recording(sid)
        if not se:
            return jerr(404, "Unbekannte Aufzeichnung")
        b = await req.json()
        f: dict = {}
        if "name" in b:
            f["name"] = (b["name"] or se["name"])[:80]
        if b.get("source") in ("both", "offline", "online"):
            f["source"] = b["source"]
        if "end_ts" in b:
            f["end_ts"] = float(b["end_ts"]) if b["end_ts"] else None
        if b.get("extend_hours"):
            base = max(se["end_ts"] or now(), now())
            f["end_ts"] = base + float(b["extend_hours"]) * 3600
        if b.get("resume"):
            f["stopped_ts"] = None
        st.store.update_recording(sid, **f)
        st.hub.publish("apple_devices", {"changed": True})
        return web.json_response(_session_public(st.store.recording(sid)))

    async def session_stop(req: web.Request) -> web.Response:
        sid = int(req.match_info["sid"])
        se = st.store.recording(sid)
        if not se:
            return jerr(404, "Unbekannte Aufzeichnung")
        if se["stopped_ts"] is None:
            st.store.update_recording(sid, stopped_ts=now())
        st.hub.publish("apple_devices", {"changed": True})
        return web.json_response(_session_public(st.store.recording(sid)))

    async def recording_delete(req: web.Request) -> web.Response:
        st.store.delete_recording(int(req.match_info["sid"]))
        st.hub.publish("apple_devices", {"changed": True})
        return web.json_response({"ok": True})

    async def session_points_route(req: web.Request) -> web.Response:
        se = st.store.recording(int(req.match_info["sid"]))
        if not se:
            return jerr(404, "Unbekannte Aufzeichnung")
        pts = session_points(st, se)
        stays = compute_stays(pts, dict(st.store.settings().get("stays", {})))
        return web.json_response({"session": _session_public(se), "points": pts, **stays})

    async def icloud_connect(req: web.Request) -> web.Response:
        b = await req.json() if req.can_read_body else {}
        return web.json_response(await st.online.connect(b.get("apple_id"), b.get("password")))

    async def icloud_sms(_: web.Request) -> web.Response:
        return web.json_response(await st.online.request_sms())

    async def icloud_code(req: web.Request) -> web.Response:
        b = await req.json()
        res = await st.online.submit_code(str(b.get("code", "")))
        if res["state"] == "connected":
            await st.online.refresh(force=True)
            res = st.online.status()
        return web.json_response(res)

    async def icloud_disconnect(_: web.Request) -> web.Response:
        await st.online.disconnect()
        return web.json_response(st.online.status())

    async def new_since(req: web.Request) -> web.Response:
        """Neue Berichte je Objekt seit Zeitpunkt X (nach Eingang beim Server)."""
        since = _f(req.query.get("since")) or (now() - 86400)
        rows = st.store.db.execute(
            "SELECT device_id, COUNT(*) AS n, MAX(ts) AS newest, SUM(late) AS late, "
            "COUNT(DISTINCT CASE WHEN batch_size>1 AND batch_id NOT LIKE 'init-%' THEN batch_id END) AS batches "
            "FROM reports WHERE received_at>? GROUP BY device_id", (since,)).fetchall()
        items = [dict(r) for r in rows]
        return web.json_response({"since": since, "total": sum(x["n"] for x in items), "devices": items})

    async def device_stays(req: web.Request) -> web.Response:
        q = req.query
        cfg = dict(st.store.settings().get("stays", {}))
        for k in DEFAULT_SETTINGS["stays"]:
            if q.get(k) not in (None, ""):
                cfg[k] = float(q[k])
        rows = st.store.reports(_f(q.get("since")), _f(q.get("until")), req.match_info["id"], 100000)
        return web.json_response(compute_stays(rows, cfg))

    async def device_export_keys(req: web.Request) -> web.Response:
        t = st.registry.tracked.get(req.match_info["id"])
        if not t or st.args.demo:
            return jerr(404, "Keine Schlüssel")
        return web.json_response(t.accessory.to_json(), headers={
            "Content-Disposition": f'attachment; filename="{safe_name(t.id)}.json"'})

    async def all_reports(req: web.Request) -> web.Response:
        q = req.query
        return web.json_response({"reports": st.store.reports(
            _f(q.get("since")), _f(q.get("until")), q.get("device"), int(q.get("limit", 200000)))})

    async def import_keys(req: web.Request) -> web.Response:
        need_real()
        files: list[tuple[str, bytes]] = []
        if req.content_type.startswith("multipart/"):
            reader = await req.multipart()
            async for part in reader:
                if part.filename or part.name in ("file", "files"):
                    files.append((part.filename or "upload", await part.read(decode=True)))
        else:
            files.append((req.query.get("filename", "upload"), await req.read()))
        added, errors = [], []
        for name, raw in files:
            try:
                added += st.registry.import_bytes(raw, name)
            except Exception as e:  # noqa: BLE001
                errors.append({"file": name, "error": f"{type(e).__name__}: {e}"})
        if added:
            st.wake([a["id"] for a in added], full=True)
            st.hub.publish("devices", {"devices": st.store.devices()})
        return web.json_response({"ok": bool(added), "added": added, "errors": errors},
                                 status=200 if added or not errors else 400)

    async def refresh(req: web.Request) -> web.Response:
        b = await req.json() if req.can_read_body else {}
        ids = b.get("device_ids") or ([b["device_id"]] if b.get("device_id") else None)
        nets = st.store.settings()["networks"]
        by_net: dict[str, list[str]] = {}
        for d in st.store.devices():
            if ids is None or d["id"] in ids:
                by_net.setdefault(d.get("network") or "apple", []).append(d["id"])
        extra_new, errors = 0, []
        # Samsung: schnell, direkt mit abrufen
        if (st.samsung and st.samsung.connected and nets["samsung"].get("enabled")
                and by_net.get("samsung") and not st.args.demo):
            try:
                extra_new += await asyncio.wait_for(st.samsung.refresh(ids and by_net["samsung"]), timeout=60)
            except Exception as e:  # noqa: BLE001
                errors.append(f"Samsung: {e}")
        # Google: Server-Ortung nur auf ausdrücklichen Wunsch für einzelne Tracker (dauert bis ~2 min)
        if (ids and by_net.get("google") and st.google and st.google.has_access and st.google.tools_ready
                and nets["google"].get("server_mode") != "off" and not st.args.demo):
            try:
                extra_new += await asyncio.wait_for(st.google.refresh(by_net["google"]), timeout=180)
            except Exception as e:  # noqa: BLE001
                errors.append(f"Google: {e}")
        if ids is not None and not by_net.get("apple") and not st.args.demo:
            return web.json_response({"ok": not errors, "new": extra_new, "polled": len(ids),
                                      "error": "; ".join(errors) or None})
        fut = st.wake(ids, full=bool(b.get("full", True)))
        if not b.get("wait", True):
            return web.json_response({"ok": True, "queued": True})
        try:
            res = await asyncio.wait_for(asyncio.shield(fut), timeout=float(b.get("timeout", 90)))
        except asyncio.TimeoutError:
            return web.json_response({"ok": True, "queued": True, "timeout": True, "new": extra_new})
        res = dict(res)
        res["new"] = (res.get("new") or 0) + extra_new
        if errors:
            res["error"] = "; ".join(filter(None, [res.get("error"), *errors]))
        return web.json_response({"ok": res.get("error") is None, **res})

    # --- Netzwerke: Google & Samsung --------------------------------------------------
    def need_net(obj: Any, name: str) -> Any:
        if st.args.demo or obj is None:
            raise ValueError(f"{name} ist im Demo-Modus nicht verfügbar")
        return obj

    async def networks(_: web.Request) -> web.Response:
        return web.json_response(networks_summary(st))

    async def samsung_login(_: web.Request) -> web.Response:
        sm = need_net(st.samsung, "Samsung")
        try:
            url = await asyncio.to_thread(sm.login_url)
        except Exception as e:  # noqa: BLE001
            return jerr(502, f"Samsung-Login konnte nicht vorbereitet werden: {e}")
        return web.json_response({"ok": True, "login_url": url, "redirect_scheme": "ms-app", "expires_in": 1800})

    async def samsung_complete(req: web.Request) -> web.Response:
        sm = need_net(st.samsung, "Samsung")
        b = await req.json()
        try:
            await asyncio.to_thread(sm.complete_login, str(b.get("redirect_url") or ""))
        except Exception as e:  # noqa: BLE001
            return jerr(400, f"Samsung-Anmeldung fehlgeschlagen: {e}")
        info: dict = {}
        try:
            info = await sm.sync()
        except Exception as e:  # noqa: BLE001
            sm.error = f"Konto verbunden, Geräteliste noch nicht geladen: {e}"
        if b.get("pin"):
            sm.set_pin(b["pin"])
        sm.event.set()
        st.hub.publish("networks", {"samsung": sm.status()})
        return web.json_response({"ok": True, **info, "status": sm.status()})

    async def samsung_logout(_: web.Request) -> web.Response:
        sm = need_net(st.samsung, "Samsung")
        sm.logout()
        st.hub.publish("networks", {"samsung": sm.status()})
        return web.json_response({"ok": True, "status": sm.status()})

    async def samsung_pin(req: web.Request) -> web.Response:
        sm = need_net(st.samsung, "Samsung")
        if req.method == "DELETE":
            sm.set_pin(None)
        else:
            pin = str((await req.json()).get("pin") or "").strip()
            if not pin or len(pin) > 128:
                return jerr(400, "Bitte eine gültige Samsung-Find-PIN eingeben.")
            sm.set_pin(pin)
            sm.event.set()
        return web.json_response({"ok": True, "status": sm.status()})

    async def samsung_sync(req: web.Request) -> web.Response:
        sm = need_net(st.samsung, "Samsung")
        if not sm.connected:
            return jerr(400, "Bitte zuerst das Samsung-Konto verbinden.")
        b = await req.json() if req.can_read_body else {}
        try:
            info = await sm.sync(restore=bool(b.get("restore")))
        except Exception as e:  # noqa: BLE001
            return jerr(502, f"Samsung-Geräteliste: {e}")
        return web.json_response({"ok": True, **info, "status": sm.status()})

    async def samsung_refresh(_: web.Request) -> web.Response:
        sm = need_net(st.samsung, "Samsung")
        try:
            n = await sm.refresh()
        except Exception as e:  # noqa: BLE001
            return jerr(502, f"Samsung-Abruf fehlgeschlagen: {e}")
        return web.json_response({"ok": True, "new": n, "status": sm.status()})

    async def google_secrets(req: web.Request) -> web.Response:
        g = need_net(st.google, "Google")
        if req.method == "DELETE":
            g.delete_secrets()
            return web.json_response({"ok": True, "status": g.status()})
        if req.content_type.startswith("multipart/"):
            data = {}
            async for part in await req.multipart():
                raw = await part.read(decode=True)
                data = json.loads(raw.decode("utf-8-sig"))
                break
        else:
            data = await req.json()
        try:
            g.store_secrets(data)
        except Exception as e:  # noqa: BLE001
            return jerr(400, f"{e}")
        if not g.tools_ready:
            g.start_setup()
        else:
            asyncio.create_task(g.sync())
        st.hub.publish("networks", {"google": g.status()})
        return web.json_response({"ok": True, "status": g.status()})

    async def google_setup(_: web.Request) -> web.Response:
        g = need_net(st.google, "Google")
        g.start_setup()
        return web.json_response({"ok": True, "status": g.status()})

    async def google_sync(req: web.Request) -> web.Response:
        g = need_net(st.google, "Google")
        b = await req.json() if req.can_read_body else {}
        try:
            info = await g.sync(restore=bool(b.get("restore")))
        except Exception as e:  # noqa: BLE001
            return jerr(502, f"Google-Geräteliste: {e}")
        return web.json_response({"ok": True, **info, "status": g.status()})

    async def google_refresh(req: web.Request) -> web.Response:
        g = need_net(st.google, "Google")
        b = await req.json() if req.can_read_body else {}
        ids = b.get("device_ids") or ([b["device_id"]] if b.get("device_id") else None)
        try:
            n = await g.refresh(ids)
        except Exception as e:  # noqa: BLE001
            return jerr(502, f"Google-Abruf fehlgeschlagen: {e}")
        return web.json_response({"ok": True, "new": n, "status": g.status()})

    async def google_app_reports(req: web.Request) -> web.Response:
        if st.google is None:
            return jerr(400, "Google ist nicht verfügbar")
        if not st.store.settings()["networks"]["google"].get("enabled", True):
            return web.json_response({"ok": True, "new": 0, "devices": [], "disabled": True})
        return web.json_response(await st.google.app_reports(await req.json()))

    async def events(req: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                                           "Connection": "keep-alive", "X-Accel-Buffering": "no"})
        await resp.prepare(req)
        q: asyncio.Queue = asyncio.Queue()
        st.hub.clients.add(q)
        try:
            await resp.write(f"event: status\ndata: {json.dumps(st.public_status())}\n\n".encode())
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    await resp.write(msg.encode())
                except asyncio.TimeoutError:
                    await resp.write(b"event: ping\ndata: {}\n\n")
        except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
            pass
        finally:
            st.hub.clients.discard(q)
        return resp

    # --- Export ----------------------------------------------------------------------------
    def export_rows(req: web.Request) -> tuple[list[dict], dict]:
        q = req.query
        rows = st.store.reports(_f(q.get("since")), _f(q.get("until")), q.get("device"))
        return rows, {d["id"]: d["name"] for d in st.store.devices()}

    async def export_csv(req: web.Request) -> web.Response:
        rows, names = export_rows(req)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["geraet", "zeit_utc", "lat", "lon", "genauigkeit_m", "batterie", "empfangen_utc",
                    "batch_groesse", "nachgereicht", "netz"])
        nets = {d["id"]: d.get("network") or "apple" for d in st.store.devices()}
        for x in rows:
            w.writerow([names.get(x["device_id"], x["device_id"]), iso(x["ts"]), x["lat"], x["lon"],
                        x["accuracy"], x["battery"], iso(x["received_at"]), x["batch_size"], x["late"],
                        nets.get(x["device_id"], "apple")])
        return web.Response(text=buf.getvalue(), content_type="text/csv", charset="utf-8",
                            headers={"Content-Disposition": 'attachment; filename="findmy-ultra.csv"'})

    async def export_json(req: web.Request) -> web.Response:
        rows, names = export_rows(req)
        for x in rows:
            x["device_name"] = names.get(x["device_id"])
        return web.json_response(rows, headers={"Content-Disposition": 'attachment; filename="findmy-ultra.json"'})

    async def export_gpx(req: web.Request) -> web.Response:
        from xml.sax.saxutils import escape
        rows, names = export_rows(req)
        by: dict[str, list] = {}
        for x in rows:
            by.setdefault(x["device_id"], []).append(x)
        parts = ['<?xml version="1.0" encoding="UTF-8"?>',
                 f'<gpx version="1.1" creator="{APP_NAME}" xmlns="http://www.topografix.com/GPX/1/1">']
        for did, pts in by.items():
            parts.append(f"<trk><name>{escape(names.get(did, did))}</name><trkseg>")
            parts += [f'<trkpt lat="{p["lat"]}" lon="{p["lon"]}"><time>{iso(p["ts"])}</time>'
                      f'<hdop>{p["accuracy"] or 0}</hdop></trkpt>' for p in pts]
            parts.append("</trkseg></trk>")
        parts.append("</gpx>")
        return web.Response(text="\n".join(parts), content_type="application/gpx+xml",
                            headers={"Content-Disposition": 'attachment; filename="findmy-ultra.gpx"'})

    r.add_get("/", index)
    r.add_get("/auth/app", index)
    r.add_get("/manifest.webmanifest", manifest)
    r.add_get("/icon.svg", icon)
    r.add_get("/api/health", health)
    r.add_post("/api/auth/login", login)
    r.add_post("/api/auth/logout", logout)
    r.add_get("/api/auth/me", me)
    r.add_post("/api/auth/password", change_password)
    r.add_post("/api/auth/totp/setup", totp_setup)
    r.add_post("/api/auth/totp/enable", totp_enable)
    r.add_post("/api/auth/totp/disable", totp_disable)
    r.add_post("/api/auth/passkey/register/options", pk_reg_options)
    r.add_post("/api/auth/passkey/register/verify", pk_reg_verify)
    r.add_post("/api/auth/passkey/login/options", pk_login_options)
    r.add_post("/api/auth/passkey/login/verify", pk_login_verify)
    r.add_delete("/api/auth/passkeys/{pid}", pk_delete)
    r.add_post("/api/auth/link", link_create)
    r.add_post("/api/auth/link/redeem", link_redeem)
    r.add_delete("/api/auth/sessions/{sid}", session_delete)
    r.add_get("/api/status", status)
    r.add_get("/api/settings", get_settings)
    r.add_put("/api/settings", put_settings)
    r.add_post("/api/bark/test", bark_test)
    r.add_get("/api/notifications", notifications)
    r.add_delete("/api/notifications", notifications_clear)
    r.add_get("/api/apple/status", apple_status)
    r.add_post("/api/apple/login", apple_login)
    r.add_post("/api/apple/runtime/install", apple_runtime_install)
    r.add_post("/api/apple/2fa/request", apple_2fa_request)
    r.add_post("/api/apple/2fa/submit", apple_2fa_submit)
    r.add_post("/api/apple/logout", apple_logout)
    r.add_get("/api/devices", devices)
    r.add_get("/api/devices/{id}", device_get)
    r.add_patch("/api/devices/{id}", device_patch)
    r.add_delete("/api/devices/{id}", device_delete)
    r.add_get("/api/devices/{id}/reports", device_reports)
    r.add_get("/api/devices/{id}/stays", device_stays)
    r.add_get("/api/new", new_since)
    r.add_get("/api/apple-devices", apple_devices)
    r.add_post("/api/apple-devices", apple_create_route)
    r.add_post("/api/apple-devices/refresh", apple_refresh)
    # Apple-IDs enthalten „/“, „+“, „=“ → {id:.+}; spezifische Routen zuerst registrieren
    r.add_post("/api/apple-devices/{id:.+}/offline", apple_offline_import)
    r.add_delete("/api/apple-devices/{id:.+}/offline/{role:main|left|right|case}", apple_offline_remove)
    r.add_post("/api/apple-devices/{id:.+}/sound", apple_sound)
    r.add_get("/api/apple-devices/{id:.+}/raw", apple_raw)
    r.add_post("/api/apple-devices/{id:.+}/message", apple_message)
    r.add_post("/api/apple-devices/{id:.+}/lost", apple_lost)
    r.add_get("/api/apple-devices/{id:.+}/sessions", sessions_list)
    r.add_post("/api/apple-devices/{id:.+}/sessions", session_start)
    r.add_get("/api/sessions/{sid:\\d+}/points", session_points_route)
    r.add_post("/api/sessions/{sid:\\d+}/stop", session_stop)
    r.add_patch("/api/sessions/{sid:\\d+}", session_patch)
    r.add_delete("/api/sessions/{sid:\\d+}", recording_delete)
    r.add_patch("/api/apple-devices/{id:.+}", apple_patch)
    r.add_delete("/api/apple-devices/{id:.+}", apple_delete_route)
    r.add_post("/api/icloud/connect", icloud_connect)
    r.add_post("/api/icloud/2fa/sms", icloud_sms)
    r.add_post("/api/icloud/2fa/submit", icloud_code)
    r.add_post("/api/icloud/disconnect", icloud_disconnect)
    r.add_get("/api/devices/{id}/keys", device_export_keys)
    r.add_get("/api/reports", all_reports)
    r.add_post("/api/import", import_keys)
    r.add_post("/api/refresh", refresh)
    r.add_get("/api/events", events)
    r.add_get("/api/networks", networks)
    r.add_post("/api/samsung/login", samsung_login)
    r.add_post("/api/samsung/complete", samsung_complete)
    r.add_post("/api/samsung/logout", samsung_logout)
    r.add_post("/api/samsung/pin", samsung_pin)
    r.add_delete("/api/samsung/pin", samsung_pin)
    r.add_post("/api/samsung/sync", samsung_sync)
    r.add_post("/api/samsung/refresh", samsung_refresh)
    r.add_post("/api/google/secrets", google_secrets)
    r.add_delete("/api/google/secrets", google_secrets)
    r.add_post("/api/google/setup", google_setup)
    r.add_post("/api/google/sync", google_sync)
    r.add_post("/api/google/refresh", google_refresh)
    r.add_post("/api/google/app-reports", google_app_reports)
    r.add_get("/export.csv", export_csv)
    r.add_get("/export.json", export_json)
    r.add_get("/export.gpx", export_gpx)
    return app


# ════════════════════════════════════════════════════════════════════════════
#  Web-Oberfläche (eingebettet)
# ════════════════════════════════════════════════════════════════════════════

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0A84FF"/><stop offset="1" stop-color="#5E5CE6"/></linearGradient></defs><rect width="512" height="512" rx="112" fill="url(#g)"/><circle cx="256" cy="256" r="150" fill="none" stroke="#fff" stroke-opacity=".35" stroke-width="18"/><circle cx="256" cy="256" r="88" fill="none" stroke="#fff" stroke-opacity=".6" stroke-width="18"/><circle cx="256" cy="256" r="36" fill="#fff"/></svg>"""

WEB_HTML = r"""<!doctype html>
<html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>FindMy Ultra</title>
<link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/icon.svg">
<meta name="theme-color" content="#000000"><meta name="apple-mobile-web-app-capable" content="yes">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
:root{--bg:#0b0b0f;--glass:rgba(28,28,34,.62);--stroke:rgba(255,255,255,.12);--fg:#f5f5f7;--mute:#9a9aa3;--acc:#0A84FF;--red:#FF453A;--green:#30D158;--orange:#FF9F0A}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font:15px/1.4 -apple-system,BlinkMacSystemFont,"SF Pro Text",Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
#map{position:fixed;inset:0;z-index:0}
.glass{background:var(--glass);backdrop-filter:blur(28px) saturate(180%);-webkit-backdrop-filter:blur(28px) saturate(180%);border:1px solid var(--stroke);box-shadow:0 10px 40px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.08)}
button,.btn{font:inherit;color:var(--fg);background:rgba(255,255,255,.08);border:1px solid var(--stroke);border-radius:999px;padding:8px 14px;cursor:pointer;transition:.15s}
button:hover{background:rgba(255,255,255,.16)}button.pri{background:var(--acc);border-color:transparent;font-weight:600}button.danger{background:rgba(255,69,58,.2);color:#ff6961}
input,select{font:inherit;color:var(--fg);background:rgba(255,255,255,.07);border:1px solid var(--stroke);border-radius:12px;padding:10px 12px;width:100%}
#side{position:fixed;top:12px;left:12px;bottom:12px;width:360px;border-radius:26px;z-index:500;display:flex;flex-direction:column;overflow:hidden}
#side header{padding:16px 18px 8px;display:flex;align-items:center;gap:10px}#side header h1{font-size:20px;margin:0;flex:1;letter-spacing:-.3px}
.pill{font-size:12px;color:var(--mute);padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.07)}
.live{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--green);margin-right:6px;box-shadow:0 0 0 0 rgba(48,209,88,.7);animation:pulse 2s infinite}
@keyframes pulse{70%{box-shadow:0 0 0 10px rgba(48,209,88,0)}100%{box-shadow:0 0 0 0 rgba(48,209,88,0)}}
#list{overflow:auto;padding:4px 10px 10px;flex:1}
.dev{display:flex;gap:12px;align-items:center;padding:10px;border-radius:18px;cursor:pointer;transition:.15s}
.dev:hover,.dev.sel{background:rgba(255,255,255,.08)}
.emo{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;font-size:22px;flex:none}
.dev .t{flex:1;min-width:0}.dev .n{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.dev .s{color:var(--mute);font-size:13px}
.tag{font-size:11px;padding:2px 7px;border-radius:999px;margin-left:6px;font-weight:600}.tag.lost{background:var(--red)}.tag.guard{background:var(--orange)}
#tools{position:fixed;top:12px;right:12px;z-index:500;display:flex;gap:8px;padding:6px;border-radius:999px}
#timeline{position:fixed;left:384px;right:12px;bottom:12px;z-index:500;border-radius:24px;padding:12px 18px;display:none}
#timeline input[type=range]{padding:0;height:28px;background:none;border:none}
#timeline .row{display:flex;gap:10px;align-items:center}
#tlinfo{font-variant-numeric:tabular-nums;color:var(--mute);font-size:13px;min-width:230px}
.modal{position:fixed;inset:0;z-index:1000;display:none;place-items:center;background:rgba(0,0,0,.4)}
.modal .card{width:min(440px,92vw);max-height:88vh;overflow:auto;border-radius:28px;padding:22px}
.card h2{margin:0 0 12px;font-size:22px}.card label{display:block;font-size:13px;color:var(--mute);margin:12px 0 6px}
.row2{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}.err{color:#ff6961;font-size:13px;min-height:18px;margin-top:8px}
.marker{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;font-size:19px;border:3px solid #fff;box-shadow:0 4px 14px rgba(0,0,0,.45)}
.leaflet-popup-content-wrapper{background:rgba(28,28,34,.85);color:var(--fg);backdrop-filter:blur(20px);border-radius:16px}.leaflet-popup-tip{background:rgba(28,28,34,.85)}
.leaflet-popup-content a{color:var(--acc)}
#login{position:fixed;inset:0;z-index:2000;display:none;place-items:center;background:radial-gradient(circle at 30% 20%,#1c2a4a,#000 60%)}
#login .card{width:min(380px,92vw);border-radius:30px;padding:28px}
.logo{width:64px;height:64px;border-radius:18px;margin-bottom:12px}
.sec{border-top:1px solid var(--stroke);margin-top:16px;padding-top:6px}
.small{font-size:12px;color:var(--mute)}
@media(max-width:760px){#side{top:auto;left:8px;right:8px;bottom:8px;width:auto;height:44vh}#timeline{left:8px;right:8px;bottom:calc(44vh + 16px)}#tools{top:8px;right:8px}}
</style></head><body>
<div id="map"></div>
<aside id="side" class="glass">
  <header><img src="/icon.svg" style="width:30px;height:30px;border-radius:8px"><h1>FindMy Ultra</h1><span class="pill" id="st"><span class="live"></span>live</span></header>
  <div style="padding:0 18px 8px" class="small" id="stats"></div>
  <div id="list"></div>
</aside>
<div id="tools" class="glass">
  <button onclick="refresh()" title="Standorte aktualisieren (r)">⟳ Aktualisieren</button>
  <select id="range" style="width:auto;border-radius:999px" onchange="loadHistory()">
    <option value="3600">1 h</option><option value="21600">6 h</option><option value="86400" selected>24 h</option>
    <option value="259200">3 T</option><option value="604800">7 T</option><option value="2592000">30 T</option><option value="0">Alles</option></select>
  <button onclick="fitAll()" title="Alle zeigen (f)">◎</button>
  <button onclick="openSetup()">⚙︎</button>
</div>
<div id="timeline" class="glass"><div class="row">
  <button id="play" onclick="togglePlay()">▶︎</button>
  <input type="range" id="slider" min="0" max="0" value="0" oninput="scrub(+this.value)">
  <div id="tlinfo"></div><button onclick="closeTimeline()">✕</button></div></div>

<div id="login"><div class="card glass">
  <img class="logo" src="/icon.svg"><h2 style="margin:0 0 4px">FindMy Ultra</h2><div class="small" id="loginhint">Melde dich an.</div>
  <label>Benutzer</label><input id="lu" value="admin" autocomplete="username">
  <label>Passwort</label><input id="lp" type="password" autocomplete="current-password" onkeydown="if(event.key==='Enter')doLogin()">
  <div id="totpbox" style="display:none"><label>2FA-Code</label><input id="lt" inputmode="numeric" autocomplete="one-time-code" onkeydown="if(event.key==='Enter')doLogin()"></div>
  <div class="row2"><button class="pri" onclick="doLogin()" style="flex:1">Anmelden</button><button onclick="passkeyLogin()" id="pkbtn">🔑 Passkey</button></div>
  <div class="err" id="lerr"></div>
</div></div>

<div class="modal" id="setup"><div class="card glass">
  <h2>Einrichtung</h2>
  <div id="applebox"></div>
  <div class="sec"><label>Schlüssel importieren (.json / .plist)</label><input type="file" id="keyfiles" multiple>
  <div class="row2"><button onclick="importKeys()">Importieren</button></div><div class="err" id="ierr"></div></div>
  <div class="sec"><label>Sicherheit</label><div class="row2"><button onclick="registerPasskey()">🔑 Passkey hinzufügen</button><button onclick="changePw()">Passwort ändern</button><button onclick="logoutWeb()">Abmelden</button></div><div class="err" id="serr"></div></div>
  <div class="sec small">Export: <a href="#" onclick="exp('gpx')">GPX</a> · <a href="#" onclick="exp('csv')">CSV</a> · <a href="#" onclick="exp('json')">JSON</a>. Weitere Einstellungen (Alarme, Bark, Zonen, 2FA) in der iOS-App.</div>
  <div class="row2"><button onclick="closeSetup()" style="margin-left:auto">Fertig</button></div>
</div></div>

<script>
const $=s=>document.querySelector(s);let devices=[],sel=null,map,layers={},hist=[],histLayer=null,playT=null,es=null;
const params=new URLSearchParams(location.search);const appMode=location.pathname==='/auth/app';
const b64u=b=>btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
const ub64=s=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')+'==='.slice((s.length+3)%4)),c=>c.charCodeAt(0));
async function api(p,o={}){const r=await fetch(p,{credentials:'same-origin',...o,headers:{'Content-Type':'application/json',...(o.headers||{})}});
  let j={};try{j=await r.json()}catch(e){} if(r.status===401&&!p.includes('/auth/')){showLogin();throw new Error('auth')} if(!r.ok&&j.ok!==false)j.error=j.error||r.statusText; if(!r.ok)throw Object.assign(new Error(j.error||r.statusText),{j});return j}
const ago=ts=>{const s=Date.now()/1000-ts;if(s<60)return'gerade eben';if(s<3600)return`vor ${Math.round(s/60)} min`;if(s<86400)return`vor ${(s/3600).toFixed(1)} h`;return`vor ${(s/86400).toFixed(1)} T`};
const fmt=ts=>new Date(ts*1000).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
const bat={full:'🔋',medium:'🔋',low:'🪫',critical:'🪫'};

function showLogin(msg){$('#login').style.display='grid';if(msg)$('#loginhint').textContent=msg}
async function doLogin(){$('#lerr').textContent='';try{const j=await api('/api/auth/login',{method:'POST',body:JSON.stringify({username:$('#lu').value,password:$('#lp').value,totp:$('#lt').value,label:'Web '+navigator.platform})});afterLogin(j)}
  catch(e){if(e.j&&e.j.need_totp){$('#totpbox').style.display='block';$('#lt').focus()}$('#lerr').textContent=e.message}}
async function passkeyLogin(){$('#lerr').textContent='';try{const o=await api('/api/auth/passkey/login/options',{method:'POST'});
  const c=await navigator.credentials.get({publicKey:{challenge:ub64(o.challenge),rpId:o.rpId,timeout:o.timeout,userVerification:o.userVerification,allowCredentials:[]}});
  const j=await api('/api/auth/passkey/login/verify',{method:'POST',body:JSON.stringify({id:c.id,clientDataJSON:b64u(c.response.clientDataJSON),authenticatorData:b64u(c.response.authenticatorData),signature:b64u(c.response.signature),userHandle:c.response.userHandle?b64u(c.response.userHandle):null})});afterLogin(j)}
  catch(e){$('#lerr').textContent=e.message}}
function afterLogin(j){if(appMode&&params.get('action')==='login'){location.href=(params.get('callback')||'findmyultra')+'://auth?token='+encodeURIComponent(j.token);$('#loginhint').textContent='Zurück zur App …';return}
  $('#login').style.display='none';start()}
async function registerPasskey(){$('#serr').textContent='';try{const o=await api('/api/auth/passkey/register/options',{method:'POST'});
  const c=await navigator.credentials.create({publicKey:{...o,challenge:ub64(o.challenge),user:{...o.user,id:ub64(o.user.id)},excludeCredentials:o.excludeCredentials.map(x=>({...x,id:ub64(x.id)}))}});
  const name=(navigator.userAgent.match(/iPhone|iPad|Mac|Android|Windows/)||['Passkey'])[0];
  await api('/api/auth/passkey/register/verify',{method:'POST',body:JSON.stringify({clientDataJSON:b64u(c.response.clientDataJSON),attestationObject:b64u(c.response.attestationObject),name})});
  $('#serr').textContent='✅ Passkey gespeichert';return true}catch(e){$('#serr').textContent=e.message;return false}}
async function changePw(){const cur=prompt('Aktuelles Passwort');if(cur===null)return;const nw=prompt('Neues Passwort (min. 8 Zeichen)');if(!nw)return;let totp='';
  try{await api('/api/auth/password',{method:'POST',body:JSON.stringify({current:cur,new:nw})})}catch(e){if(e.j&&e.j.need_totp){totp=prompt('2FA-Code');try{await api('/api/auth/password',{method:'POST',body:JSON.stringify({current:cur,new:nw,totp})})}catch(e2){return alert(e2.message)}}else return alert(e.message)}alert('Passwort geändert ✅')}
async function logoutWeb(){await api('/api/auth/logout',{method:'POST'}).catch(()=>{});location.reload()}

async function appFlow(){ // ASWebAuthenticationSession der iOS-App
  const action=params.get('action');const cb=params.get('callback')||'findmyultra';
  if(action==='register'){document.body.innerHTML='<div style="display:grid;place-items:center;height:100%;padding:24px;text-align:center"><div class="glass" style="padding:28px;border-radius:28px;max-width:380px"><img class="logo" src="/icon.svg"><h2>Passkey hinzufügen</h2><p class="small">Tippe auf den Button, um einen Passkey für FindMy Ultra zu erstellen.</p><button class="pri" id="go">🔑 Passkey erstellen</button><div class="err" id="serr"></div></div></div>';
    try{await api('/api/auth/link/redeem',{method:'POST',body:JSON.stringify({code:params.get('code')})})}catch(e){$('#serr').textContent=e.message;return}
    $('#go').onclick=async()=>{const ok=await registerPasskey();await api('/api/auth/logout',{method:'POST'}).catch(()=>{});location.href=cb+'://passkey?ok='+(ok?1:0)};return}
  showLogin('Mit Passkey oder Passwort bei FindMy Ultra anmelden.');}

function initMap(){if(map)return;map=L.map('map',{zoomControl:false,attributionControl:true}).setView([51.16,10.45],6);
  const dark=matchMedia('(prefers-color-scheme: dark)').matches;
  L.tileLayer(`https://{s}.basemaps.cartocdn.com/${dark?'dark_all':'rastertiles/voyager'}/{z}/{x}/{y}{r}.png`,{maxZoom:20,attribution:'© OpenStreetMap © CARTO'}).addTo(map)}
function icon(d){return L.divIcon({className:'',html:`<div class="marker" style="background:${d.color}">${d.emoji||'📍'}</div>`,iconSize:[38,38],iconAnchor:[19,19]})}
function render(){const l=$('#list');l.innerHTML='';
  for(const d of devices){const e=document.createElement('div');e.className='dev'+(sel===d.id?' sel':'');const last=d.last;
    e.innerHTML=`<div class="emo" style="background:${d.color}33">${d.emoji||'📍'}</div><div class="t"><div class="n">${esc(d.name)}${d.network&&d.network!=='apple'?`<span class="tag" style="background:${d.network==='google'?'#34a853':'#1428a0'}">${d.network==='google'?'GOOGLE':'SAMSUNG'}</span>`:''}${d.lost.enabled?'<span class="tag lost">VERLOREN</span>':''}${d.alerts.guard.enabled?'<span class="tag guard">WACHE</span>':''}</div>
    <div class="s">${last?ago(last.ts)+' · ±'+(last.accuracy??'?')+' m':'noch kein Standort'} ${d.battery?bat[d.battery]:''} · ${d.total} Pkt.</div></div>`;
    e.onclick=()=>select(d.id);l.appendChild(e);
    if(last){const ll=[last.lat,last.lon];if(!layers[d.id]){layers[d.id]={m:L.marker(ll,{icon:icon(d)}).addTo(map).on('click',()=>select(d.id)),c:L.circle(ll,{radius:last.accuracy||10,color:d.color,weight:1,fillOpacity:.12}).addTo(map)}}
      else{layers[d.id].m.setLatLng(ll).setIcon(icon(d));layers[d.id].c.setLatLng(ll).setRadius(last.accuracy||10)}
      layers[d.id].m.bindPopup(popup(d,last))}}}
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function popup(d,r){return `<b>${d.emoji||''} ${esc(d.name)}</b><br>${fmt(r.ts)} (${ago(r.ts)})<br>±${r.accuracy??'?'} m · empfangen +${Math.round((r.received_at-r.ts)/60)} min${r.batch_size>1?' · Batch ×'+r.batch_size:''}<br><a target="_blank" href="https://maps.apple.com/?ll=${r.lat},${r.lon}&q=${encodeURIComponent(d.name)}">In Apple Karten öffnen</a>`}
function fitAll(){const pts=devices.filter(d=>d.last).map(d=>[d.last.lat,d.last.lon]);if(pts.length)map.fitBounds(pts,{padding:[80,80],maxZoom:16})}
async function select(id){sel=id;render();await loadHistory()}
async function loadHistory(){if(!sel)return;const r=+$('#range').value;const since=r?Date.now()/1000-r:'';
  const j=await api(`/api/devices/${encodeURIComponent(sel)}/reports?since=${since}`);hist=j.reports;const d=devices.find(x=>x.id===sel);
  if(histLayer)histLayer.remove();histLayer=L.layerGroup().addTo(map);if(!hist.length){$('#timeline').style.display='none';return}
  const ll=hist.map(p=>[p.lat,p.lon]);L.polyline(ll,{color:d.color,weight:4,opacity:.85}).addTo(histLayer);
  hist.forEach((p,i)=>L.circleMarker([p.lat,p.lon],{radius:4,color:'#fff',weight:1,fillColor:d.color,fillOpacity:.25+.75*i/hist.length}).bindPopup(popup(d,p)).addTo(histLayer));
  map.fitBounds(ll,{padding:[80,80],maxZoom:17});$('#timeline').style.display='block';const s=$('#slider');s.max=hist.length-1;s.value=hist.length-1;scrub(hist.length-1,true)}
let cursor=null;function scrub(i,nofly){const p=hist[i];if(!p)return;const d=devices.find(x=>x.id===sel);
  $('#tlinfo').textContent=`${i+1}/${hist.length} · ${fmt(p.ts)} · ±${p.accuracy??'?'} m${p.late?' · nachgereicht':''}`;
  if(!cursor)cursor=L.circleMarker([p.lat,p.lon],{radius:9,color:'#fff',weight:3,fillColor:d.color,fillOpacity:1}).addTo(map);else cursor.setLatLng([p.lat,p.lon]).setStyle({fillColor:d.color});if(!nofly)map.panTo([p.lat,p.lon],{animate:true})}
function togglePlay(){if(playT){clearInterval(playT);playT=null;$('#play').textContent='▶︎';return}const s=$('#slider');if(+s.value>=hist.length-1)s.value=0;$('#play').textContent='❚❚';
  playT=setInterval(()=>{if(+s.value>=hist.length-1)return togglePlay();s.value=+s.value+1;scrub(+s.value)},350)}
function closeTimeline(){$('#timeline').style.display='none';if(histLayer)histLayer.remove();if(cursor){cursor.remove();cursor=null}sel=null;render()}
async function refresh(){$('#st').innerHTML='⟳ lädt …';try{const j=await api('/api/refresh',{method:'POST',body:JSON.stringify({wait:true})});$('#st').innerHTML=`<span class="live"></span>${j.new||0} neu`}catch(e){$('#st').textContent='Fehler'}}
async function loadDevices(){const j=await api('/api/devices');devices=j.devices;render()}
function stats(s){const a=s.apple||{};$('#stats').textContent=`${s.stats.total} Standorte · heute ${s.stats.today} · Batches ${s.stats.batches} · ${a.state==='logged_in'?'Apple ✓':'Apple ✗ – ⚙︎ öffnen'}${s.polling?' · ruft ab …':''}`}
function live(){if(es)es.close();es=new EventSource('/api/events');
  es.addEventListener('status',e=>stats(JSON.parse(e.data)));es.addEventListener('devices',e=>{devices=JSON.parse(e.data).devices;render()});
  es.addEventListener('device',()=>loadDevices());
  es.addEventListener('reports',e=>{const j=JSON.parse(e.data);if(j.device_id===sel)loadHistory();loadDevices()});
  es.addEventListener('notification',e=>{const n=JSON.parse(e.data);toast(n.title+' – '+n.body)});es.onerror=()=>setTimeout(live,4000)}
function toast(t){const d=document.createElement('div');d.className='glass';d.style.cssText='position:fixed;top:70px;right:12px;z-index:3000;padding:12px 16px;border-radius:18px;max-width:340px';d.textContent=t;document.body.appendChild(d);setTimeout(()=>d.remove(),7000)}

async function openSetup(){$('#setup').style.display='grid';renderApple(await api('/api/apple/status'))}
function closeSetup(){$('#setup').style.display='none'}
function renderApple(s){const b=$('#applebox');
  if(s.state==='logged_in'){b.innerHTML=`<label>Apple-Konto</label><div>✅ ${esc(s.account_name||'')} </div><div class="row2"><button class="danger" onclick="appleLogout()">Abmelden</button></div>`;return}
  if(s.state==='require_2fa'){b.innerHTML=`<label>Zwei-Faktor-Code</label><select id="m2">${(s.methods||[]).map(m=>`<option value="${m.index}">${esc(m.label)}</option>`).join('')}</select>
    <div class="row2"><button onclick="req2fa()">Code senden</button></div><label>Code</label><input id="c2" inputmode="numeric" autocomplete="one-time-code"><div class="row2"><button class="pri" onclick="sub2fa()">Bestätigen</button></div><div class="err" id="aerr"></div>`;return}
  b.innerHTML=`<label>Apple-ID</label><input id="ae" autocomplete="username"><label>Passwort</label><input id="ap" type="password"><label>Anisette-Server (optional, leer = lokal)</label><input id="aa" placeholder="http://…:6969"><div class="row2"><button class="pri" onclick="appleLogin()">Bei Apple anmelden</button></div><div class="err" id="aerr">${esc(s.error||'')}</div>`}
async function appleLogin(){$('#aerr').textContent='Anmeldung läuft …';try{renderApple(await api('/api/apple/login',{method:'POST',body:JSON.stringify({email:$('#ae').value,password:$('#ap').value,anisette_server:$('#aa').value})}))}catch(e){$('#aerr').textContent=e.message}}
async function req2fa(){try{await api('/api/apple/2fa/request',{method:'POST',body:JSON.stringify({index:+$('#m2').value})});$('#aerr').textContent='Code angefordert ✅'}catch(e){$('#aerr').textContent=e.message}}
async function sub2fa(){try{renderApple(await api('/api/apple/2fa/submit',{method:'POST',body:JSON.stringify({index:+$('#m2').value,code:$('#c2').value})}))}catch(e){$('#aerr').textContent=e.message}}
async function appleLogout(){if(confirm('Apple-Konto abmelden?')){await api('/api/apple/logout',{method:'POST'});openSetup()}}
async function importKeys(){const f=$('#keyfiles').files;if(!f.length)return;const fd=new FormData();for(const x of f)fd.append('files',x,x.name);
  const r=await fetch('/api/import',{method:'POST',body:fd,credentials:'same-origin'});const j=await r.json();$('#ierr').textContent=(j.added||[]).map(a=>'✅ '+a.name).join(', ')+' '+(j.errors||[]).map(e=>'❌ '+e.file+': '+e.error).join(' ');loadDevices()}
function exp(t){const r=+$('#range').value;location.href=`/export.${t}?since=${r?Date.now()/1000-r:''}${sel?'&device='+encodeURIComponent(sel):''}`}
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT')return;if(e.key==='r')refresh();if(e.key==='f')fitAll();if(e.key==='Escape')closeTimeline()});
async function start(){initMap();await loadDevices();fitAll();live();api('/api/status').then(stats)}
(async()=>{const h=await fetch('/api/health').then(r=>r.json()).catch(()=>({}));if(!h.passkeys)$('#pkbtn').style.display='none';
  if(appMode)return appFlow();try{await api('/api/auth/me');start()}catch(e){showLogin()}})();
</script></body></html>"""


# ════════════════════════════════════════════════════════════════════════════
#  TLS (optional selbstsigniert)
# ════════════════════════════════════════════════════════════════════════════

def local_ips() -> list[str]:
    ips = set()
    with contextlib.suppress(Exception):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    with contextlib.suppress(Exception):
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    return sorted(i for i in ips if not i.startswith("127."))


def make_self_signed(dirp: Path) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    cert_p, key_p = dirp / "cert.pem", dirp / "key.pem"
    if cert_p.exists() and key_p.exists():
        return cert_p, key_p
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FindMy Ultra")])
    alt = [x509.DNSName("localhost"), x509.DNSName(socket.gethostname())]
    for ip in ["127.0.0.1", *local_ips()]:
        alt.append(x509.IPAddress(ipaddress.ip_address(ip)))
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1))
            .not_valid_after(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .sign(key, hashes.SHA256()))
    secure_write(key_p, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    secure_write(cert_p, cert.public_bytes(serialization.Encoding.PEM))
    return cert_p, key_p


def cert_fingerprint(cert_p: Path) -> str:
    der = ssl.PEM_cert_to_DER_cert(cert_p.read_text())
    return hashlib.sha256(der).hexdigest().upper()


# ════════════════════════════════════════════════════════════════════════════
#  main
# ════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="findmy_ultra.py", description=f"{APP_NAME} – Server für deine AirTags.")
    p.add_argument("--host", default=os.environ.get("FMU_HOST", HOST))
    p.add_argument("--port", type=int, default=int(os.environ.get("FMU_PORT", PORT)))
    p.add_argument("--data", help="Datenordner (Standard: ./data neben dem Skript, oder $FMU_HOME)")
    p.add_argument("--import", dest="import_path", metavar="PFAD",
                   help="Schlüssel-Datei(en) (.json/.plist) oder Ordner beim Start importieren")
    p.add_argument("--tls-cert", help="TLS-Zertifikat (PEM)")
    p.add_argument("--tls-key", help="TLS-Schlüssel (PEM)")
    p.add_argument("--self-signed", action="store_true", help="HTTPS mit selbstsigniertem Zertifikat")
    p.add_argument("--trust-proxy", action="store_true",
                   help="X-Forwarded-* Header vertrauen (hinter Caddy/nginx/Cloudflare)")
    p.add_argument("--demo", action="store_true", help="Demo-Daten ohne Apple-Konto")
    p.add_argument("--reset-password", action="store_true", help="Neues Admin-Passwort generieren")
    p.add_argument("--no-bootstrap", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


async def amain(args: argparse.Namespace) -> None:
    global DATA_DIR
    if args.data:
        DATA_DIR = Path(args.data).expanduser().resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(DATA_DIR, 0o700)

    store = Store(DATA_DIR / ("demo.sqlite3" if args.demo else "findmy_ultra.sqlite3"))
    creds = Credentials(DATA_DIR / "credentials.json")
    if args.reset_password and creds.path.exists():
        creds.path.rename(creds.path.with_suffix(".json.bak"))
    created = creds.load_or_create()
    if created:
        store.delete_all_sessions()
    st = State(store=store, hub=Hub(), args=args, creds=creds, webauthn=WebAuthn(creds))
    st.registry = Registry(st)
    st.notifier = Notifier(st)
    st.online = OnlineDevices(st)
    st.alerts = Alerts(st)
    st.samsung = Samsung(st)
    st.google = GoogleServer(st)

    tasks: list[asyncio.Task] = []
    if args.demo:
        await demo_setup(st)
        tasks.append(asyncio.create_task(demo_scheduler(st)))
    else:
        st.apple = Apple(st)
        st.registry.load()
        if args.import_path:
            p = Path(args.import_path).expanduser()
            for f in ([p] if p.is_file() else sorted(p.glob("*"))):
                if f.suffix.lower() in (".json", ".plist"):
                    try:
                        for a in st.registry.import_bytes(f.read_bytes(), f.name):
                            log.info("Importiert: %s (%s)", a["name"], a["id"])
                    except Exception as e:  # noqa: BLE001
                        log.warning("%s: %s", f.name, e)
        await st.apple.restore()
        tasks.append(asyncio.create_task(scheduler(st)))
        tasks.append(asyncio.create_task(st.online.loop()))
        tasks.append(asyncio.create_task(st.samsung.loop()))
        tasks.append(asyncio.create_task(st.google.loop()))

    app = build_app(st)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    ssl_ctx = None
    fp = None
    if args.self_signed or args.tls_cert:
        cert, key = (Path(args.tls_cert), Path(args.tls_key)) if args.tls_cert else make_self_signed(DATA_DIR / "tls")
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(cert, key)
        fp = cert_fingerprint(cert)
    await web.TCPSite(runner, args.host, args.port, ssl_context=ssl_ctx).start()

    scheme = "https" if ssl_ctx else "http"
    print("\n" + "═" * 64)
    print(f"  {APP_NAME} {VERSION}{'  (DEMO)' if args.demo else ''}")
    print("═" * 64)
    hosts = ["127.0.0.1", *local_ips()] if args.host in ("0.0.0.0", "::", "") else [args.host]
    for h in hosts:
        print(f"  ➜  {scheme}://{h}:{args.port}")
    if fp:
        print(f"  🔒 Zertifikat SHA-256: {fp[:32]}…")
    if created:
        print("\n  Neue Anmeldedaten erzeugt (data/credentials.json):")
        print("     Benutzer: admin")
        print(f"     Passwort: {creds.generated_password}")
        print("     (steht auch in data/ERSTES-PASSWORT.txt – bitte in der App ändern)")
    elif creds.data.get("password_is_generated") and (DATA_DIR / "ERSTES-PASSWORT.txt").exists():
        print("\n  Erstes Passwort: siehe data/ERSTES-PASSWORT.txt")
    if not args.demo:
        a = st.apple.status()
        print(f"\n  Apple: {'✅ ' + str(a.get('account_name') or 'angemeldet') if a['state'] == 'logged_in' else '❌ nicht angemeldet – in der App einrichten'}")
        print(f"  Geräte mit Schlüsseln: {len(st.registry.tracked)}")
        print(f"  Samsung: {'✅ ' + (st.samsung.status()['account'] or 'verbunden') if st.samsung.connected else '–'}"
              f"   ·   Google (Server): {'✅ ' + st.google.status()['account'] if st.google.has_access else '–'}")
    print("═" * 64 + "\n")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    log.info("Beende …")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if not args.demo:
        st.registry.save_changed()
        st.apple.save()
        if st.apple.account is not None:
            with contextlib.suppress(Exception):
                await st.apple.account.close()
    if st.notifier.http:
        await st.notifier.http.close()
    await runner.cleanup()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    if not args.debug:
        logging.getLogger("findmy").setLevel(logging.WARNING)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(amain(args))


if __name__ == "__main__":
    main()
