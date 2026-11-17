#!/usr/bin/env python3
"""
FindMy Ultra – Server
=====================

Eine einzige Python-Datei, die die Standortberichte deiner **eigenen** AirTags
und Wo-ist-Zubehörteile direkt bei Apple abholt (über FindMy.py), lückenlos in
SQLite speichert und per HTTP-API + Web-App bereitstellt. Die iOS-App
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

REQUIREMENTS = ["findmy>=0.10.2", "aiohttp>=3.9.5,<4"]
_HERE = Path(__file__).resolve().parent


def _bootstrap() -> None:
    try:
        import aiohttp  # noqa: F401
        import findmy  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("FMU_BOOTSTRAPPED") or "--no-bootstrap" in sys.argv:
        print("❌ Abhängigkeiten fehlen: pip install " + " ".join(REQUIREMENTS))
        sys.exit(1)
    if sys.version_info < (3, 10):
        print("❌ Python 3.10 oder neuer nötig.")
        sys.exit(1)
    venv = _HERE / ".venv"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        print(f"→ Erstelle virtuelle Umgebung in {venv} …")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
    print("→ Installiere Abhängigkeiten (einmalig) …")
    subprocess.check_call([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([str(py), "-m", "pip", "install", "-q", "--prefer-binary", *REQUIREMENTS])
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
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlparse

from aiohttp import ClientSession, ClientTimeout, web

APP_NAME = "FindMy Ultra"
VERSION = "1.1.0"
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

    def devices(self) -> list[dict]:
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

    def device_public(self, dev_id: str) -> dict | None:
        return next((d for d in self.devices() if d["id"] == dev_id), None)

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
        for d in self.db.execute("SELECT id, retention_days FROM devices").fetchall():
            days = d["retention_days"] if d["retention_days"] is not None else default
            if days and days > 0:
                cur = self.db.execute("DELETE FROM reports WHERE device_id=? AND ts<?",
                                      (d["id"], now() - days * 86400))
                removed += cur.rowcount
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
#  Apple-Konto
# ════════════════════════════════════════════════════════════════════════════

class Apple:
    def __init__(self, st: "State") -> None:
        self.st = st
        self.account: Any = None
        self.methods: list[Any] = []
        self.path = DATA_DIR / "apple_account.json"
        self.libs = DATA_DIR / "anisette_libs.bin"
        self.error: str | None = None
        self.lock = asyncio.Lock()

    def _provider(self) -> Any:
        from findmy import LocalAnisetteProvider, RemoteAnisetteProvider
        url = (self.st.store.settings().get("anisette_server") or "").strip()
        if url:
            return RemoteAnisetteProvider(url)
        return LocalAnisetteProvider(libs_path=self.libs)

    async def restore(self) -> None:
        from findmy import AsyncAppleAccount, LoginState
        if not self.path.exists():
            return
        try:
            acc = AsyncAppleAccount.from_json(self.path, anisette_libs_path=self.libs)
            if acc.login_state == LoginState.LOGGED_IN:
                self.account = acc
                log.info("Apple-Konto wiederhergestellt: %s", acc.account_name)
            else:
                await acc.close()
        except Exception as e:  # noqa: BLE001
            log.warning("Gespeicherte Apple-Sitzung unbrauchbar: %s", e)

    @property
    def logged_in(self) -> bool:
        from findmy import LoginState
        return self.account is not None and self.account.login_state == LoginState.LOGGED_IN

    def status(self) -> dict:
        if self.account is None:
            return {"state": "logged_out", "error": self.error}
        from findmy import LoginState
        s = self.account.login_state
        out: dict = {"state": {LoginState.LOGGED_OUT: "logged_out", LoginState.REQUIRE_2FA: "require_2fa",
                               LoginState.AUTHENTICATED: "authenticated",
                               LoginState.LOGGED_IN: "logged_in"}[s], "error": self.error}
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
            acc = AsyncAppleAccount(anisette=self._provider())
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
                self.save()
            return self.status()

    async def request_code(self, index: int) -> None:
        await self.methods[index].request()

    async def submit_code(self, index: int, code: str) -> dict:
        from findmy import LoginState
        async with self.lock:
            state = await self.methods[index].submit(code.strip())
            if state == LoginState.LOGGED_IN:
                self.methods = []
                self.save()
                self.st.wake(full=True)
            return self.status()

    async def logout(self) -> None:
        async with self.lock:
            if self.account is not None:
                with contextlib.suppress(Exception):
                    await self.account.close()
            self.account, self.methods = None, []
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

    def import_bytes(self, raw: bytes, filename: str = "") -> list[dict]:
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
                     lat: float | None = None, lon: float | None = None) -> None:
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
                data["url"] = f"findmyultra://device/{quote(device['id'])}"
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
                        body="Bitte bald die Knopfzelle (CR2032) tauschen.")
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
        if st.apple.logged_in:
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
        elif st.waiters:
            result["error"] = "Nicht bei Apple angemeldet"
        waiters, st.waiters = st.waiters, []
        for w in waiters:
            if not w.done():
                w.set_result(result)
        if t0 - last_offline > 60:
            last_offline = t0
            with contextlib.suppress(Exception):
                await st.alerts.check_offline()
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
    seeds = [("demo-keys", "Schlüssel", "🔑", (52.5200, 13.4050)),
             ("demo-bag", "Rucksack", "🎒", (52.5310, 13.3850)),
             ("demo-bike", "Fahrrad", "🚲", (52.5080, 13.4300))]
    for did, name, emoji, pos in seeds:
        st.store.upsert_device(did, name, "AirTag", emoji, None, "airtag")
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
        except Exception as e:  # noqa: BLE001
            from findmy import InvalidCredentialsError
            if isinstance(e, InvalidCredentialsError):
                return jerr(401, "Apple-ID oder Passwort falsch")
            return jerr(502, f"Apple-Anmeldung fehlgeschlagen: {type(e).__name__}: {e}")
        if res["state"] == "logged_in":
            st.wake(full=True)
        st.set_status()
        return web.json_response(res)

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
    async def devices(_: web.Request) -> web.Response:
        return web.json_response({"devices": st.store.devices()})

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
        st.registry.remove(did)
        st.store.delete_device(did, keep_reports=req.query.get("keep_reports") == "1")
        st.hub.publish("devices", {"devices": st.store.devices()})
        return web.json_response({"ok": True})

    async def device_reports(req: web.Request) -> web.Response:
        q = req.query
        return web.json_response({"reports": st.store.reports(
            _f(q.get("since")), _f(q.get("until")), req.match_info["id"], int(q.get("limit", 50000)))})

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
        fut = st.wake(ids, full=bool(b.get("full", True)))
        if not b.get("wait", True):
            return web.json_response({"ok": True, "queued": True})
        try:
            res = await asyncio.wait_for(asyncio.shield(fut), timeout=float(b.get("timeout", 90)))
        except asyncio.TimeoutError:
            return web.json_response({"ok": True, "queued": True, "timeout": True})
        return web.json_response({"ok": res.get("error") is None, **res})

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
                    "batch_groesse", "nachgereicht"])
        for x in rows:
            w.writerow([names.get(x["device_id"], x["device_id"]), iso(x["ts"]), x["lat"], x["lon"],
                        x["accuracy"], x["battery"], iso(x["received_at"]), x["batch_size"], x["late"]])
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
    r.add_post("/api/apple/2fa/request", apple_2fa_request)
    r.add_post("/api/apple/2fa/submit", apple_2fa_submit)
    r.add_post("/api/apple/logout", apple_logout)
    r.add_get("/api/devices", devices)
    r.add_get("/api/devices/{id}", device_get)
    r.add_patch("/api/devices/{id}", device_patch)
    r.add_delete("/api/devices/{id}", device_delete)
    r.add_get("/api/devices/{id}/reports", device_reports)
    r.add_get("/api/devices/{id}/keys", device_export_keys)
    r.add_get("/api/reports", all_reports)
    r.add_post("/api/import", import_keys)
    r.add_post("/api/refresh", refresh)
    r.add_get("/api/events", events)
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
    e.innerHTML=`<div class="emo" style="background:${d.color}33">${d.emoji||'📍'}</div><div class="t"><div class="n">${esc(d.name)}${d.lost.enabled?'<span class="tag lost">VERLOREN</span>':''}${d.alerts.guard.enabled?'<span class="tag guard">WACHE</span>':''}</div>
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
    st.alerts = Alerts(st)

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
        print(f"\n  Apple: {'✅ ' + str(a.get('account_name')) if a['state'] == 'logged_in' else '❌ nicht angemeldet – in der App einrichten'}")
        print(f"  Geräte mit Schlüsseln: {len(st.registry.tracked)}")
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
