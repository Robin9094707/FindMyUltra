# FindMy Ultra

Lückenlose Ortung und Standortverlauf für deine **eigenen** AirTags, Apple-Geräte und AirPods. Das Projekt besteht aus zwei Teilen:

| Teil | Was | Version |
|---|---|---|
| `server/findmy_ultra.py` | **Eine einzige Python-Datei.** Holt Standortberichte über das Wo-ist-Netzwerk ([FindMy.py](https://github.com/malmeloo/FindMy.py)) und optional die Online-Standorte deiner Apple-Geräte über iCloud ([pyicloud](https://github.com/timlaing/pyicloud)). Speichert alles in SQLite, stellt eine API und eine Web-App bereit und schickt Alarme über **Bark**. | 1.6.0 |
| `ios/` | **iOS-App** in SwiftUI mit Liquid Glass (iOS 26) und Apple Karten, aufgebaut wie Apples „Wo ist?“. Wird per GitHub-Action als **unsignierte IPA** gebaut und per Sideloading installiert. | 1.6.0 |

> Das Projekt extrahiert keine Schlüssel. Du importierst deine vorhandenen JSON- oder plist-Schlüsseldateien.
> Es nutzt inoffizielle Apple-Schnittstellen, die sich jederzeit ändern können. Verwende es nur für deine eigenen Geräte.

---

## Inhalt

- [Schnellstart](#schnellstart)
- [Server](#server)
- [iOS-App installieren](#ios-app-installieren)
- [Funktionen](#funktionen)
- [Firewall / Netzwerk](#firewall--netzwerk)
- [API](#api)
- [Aufbau des Repos](#aufbau-des-repos)
- [Fehlerbehebung](#fehlerbehebung)

---

## Schnellstart

```bash
cd server
python3 findmy_ultra.py          # installiert beim ersten Start alles selbst in .venv
```

1. In der Konsole stehen die Adressen (z. B. `http://192.168.1.20:5070`) und **beim ersten Start Benutzer und Passwort**. Beides steht auch in `server/data/ERSTES-PASSWORT.txt`.
2. Die App installierst du über **Actions → „iOS IPA“ → Artefakt** und sideloadest sie.
3. In der App gibst du die Server-Adresse ein und meldest dich an.
4. Unter **Ich → Apple-Account** meldest du dich mit deiner Apple-ID an, inklusive 2FA.
5. Unter **Objekte → +** importierst du die AirTag-Schlüssel (`.json` / `.plist`).
6. Optional: Unter **Geräte → „Online-Ortung verbinden“** verbindest du iCloud einmalig mit 2FA.

---

## Server

Du brauchst Python 3.10 oder neuer. Fehlende Pakete (`findmy`, `aiohttp`, bei Bedarf `pyicloud`) installiert die Datei selbst.

**Port & Host** stehen ganz oben in der Datei:

```python
PORT = 5070          # Port, auf dem der Server läuft
HOST = "0.0.0.0"     # "0.0.0.0" = ganzes Netzwerk, "127.0.0.1" = nur lokal
```

**Optionen** (überschreiben die Werte in der Datei):

| Option | Bedeutung |
|---|---|
| `--port`, `--host` | Port und Adresse (auch per `FMU_PORT` / `FMU_HOST`) |
| `--data DIR` | Datenordner (Standard: `server/data`, auch `FMU_HOME`) |
| `--import PFAD` | Schlüsseldatei(en) beim Start importieren |
| `--self-signed` | HTTPS mit selbstsigniertem Zertifikat (die App pinnt den Fingerabdruck) |
| `--tls-cert/--tls-key` | eigenes Zertifikat |
| `--trust-proxy` | hinter Caddy, nginx oder Cloudflare (`X-Forwarded-*`) |
| `--demo` | Demo-Daten ohne Apple (Objekte und Apple-Geräte) |
| `--reset-password` | neues Admin-Passwort erzeugen |

**Daten in `server/data/`** (nicht im Repo):

| Datei | Inhalt |
|---|---|
| `credentials.json` | Server-Login (Passwort-Hash, TOTP, Passkeys). **Löschen ⇒ beim nächsten Start neue Zugangsdaten**, alle Sitzungen werden abgemeldet. |
| `apple_account.json` | Apple-Sitzung für das Wo-ist-Netzwerk |
| `icloud/` | vertrauenswürdige iCloud-Sitzung für die Online-Ortung |
| `accessories/*.json` | importierte Schlüssel inklusive aktueller Schlüssel-Ausrichtung |
| `findmy_ultra.sqlite3` | Standorte, Geräte, Aufzeichnungen, Alarme, Einstellungen |

Updates sind abwärtskompatibel. Die Datenbank wird beim Start nur ergänzt, vorhandene Daten bleiben erhalten.

**HTTPS / Passkeys:** HTTP über IP:Port funktioniert, die App erlaubt das. Für **Passkeys** brauchst du eine HTTPS-Domain mit gültigem Zertifikat, z. B. `caddy reverse-proxy --from findmy.example.com --to :5070`, Tailscale Serve oder einen Cloudflare Tunnel. Starte den Server dann mit `--trust-proxy`.

---

## iOS-App installieren

1. Öffne auf GitHub **Actions → „iOS IPA“ → letzter erfolgreicher Lauf → Artefakt `FindMyUltra-ipa-…`**. Bei einem Tag `v*` landet die IPA zusätzlich im Release.
2. Sideloade die IPA mit AltStore, SideStore, Sideloadly, Feather oder TrollStore. Du brauchst **iOS 26**.
3. Einen neuen Build startest du über *Actions → iOS IPA → Run workflow*. Ein Push auf `ios/**` startet ihn automatisch. Gebaut wird parallel auf `macos-26` und `macos-15`, der Schnellere gewinnt.

---

## Funktionen

### Objekte (AirTags & Zubehör)

- **Karte wie in „Wo ist?“** mit Vollbild-Apple-Karten und einem Sheet für Objekte, Geräte, Alarme und Ich.
  - AirTag-Pins mit Emoji
  - Genauigkeitskreise in Blau: aus, nur der gewählte Punkt oder alle
  - Kartenstile Standard, Hybrid und Satellit
- **Möglichst viele Standorte:**
  - Die Schlüssel aller Objekte gehen gebündelt in wenigen Apple-Anfragen raus.
  - Abgefragt werden laufend die letzten Stunden, alle 10 Minuten 24 Stunden und stündlich 7 Tage. So landen auch nachgereichte Batch-Berichte im Verlauf.
  - „Aktualisieren“ ist standardmäßig gründlich (Schnell-Abruf, 24 h und 7 Tage in einem Rutsch).
- **Standortverlauf:**
  - Wird erst per Knopf eingeblendet, Standard sind 24 Stunden.
  - Große Punkte zum Antippen, Zeitleiste mit Abspielen, Batch- und „nachgereicht“-Markierung, GPX-Export.
  - Aufbewahrung global oder pro Objekt (Standard 7 Tage, bis unbegrenzt).
- **Aufenthalte** (gelbe Kreise):
  - Zeigt, wo das Objekt wie lange war, mit Adresse und häufigen Orten.
  - Robust gegen Ausreißer und ungenaue Berichte, alles einstellbar.
- **Farbige Zeitangaben:** lila unter 1 Minute, grün bis 15 Minuten, gelb bis 1 Stunde, rot darüber.
- **Akkustand** in Grün, Gelb oder Rot.
- **„Neu seit dem letzten Öffnen“:** eine aufklappbare Info mit „+N NEU“ pro Objekt.
- **Alarme:**
  - Bewegung, Wache (Diebstahlschutz), Zonen betreten oder verlassen, Offline, Batterie, neuer Standort.
  - Verloren-Modus mit schnellem Abruf.

### Geräte (iPhone, iPad, Mac, Watch, AirPods)

- **Online-Ortung über iCloud „Geräte suchen“:**
  - Einmal mit 2FA verbinden, danach läuft eine vertrauenswürdige Sitzung ohne erneuten Code.
  - Dein Passwort wird nie automatisch wiederholt gesendet. Das schützt vor einer Kontosperre.
- **Offline-Ortung:** Pro Gerät eine AirTag-JSON- oder plist-Schlüsseldatei. Bei AirPods je eine Datei für **links, rechts und das Case**.
- **Bester Standort:** Online und offline werden verglichen, der neuere gewinnt. Ein Etikett zeigt die Quelle.
- **Gerätestatus aus iCloud:**
  - Akku in % mit Ladezustand und Stromsparmodus
  - Ortungsart (GPS/WLAN/Mobilfunk), Höhe und Stockwerk
  - Verloren-Modus, Aktivierungssperre, Besitzer in der Familienfreigabe, Audiokanäle
- **Aktionen:** Ton abspielen, Nachricht anzeigen, Verloren-Modus aktivieren und Rohdaten anzeigen. Bei den Rohdaten sind IDs und Tokens ausgeblendet.
- **Aufzeichnungen (Sessions):**
  - Starten, stoppen, verlängern, fortsetzen, umbenennen und löschen.
  - Quelle wählbar: beides, nur online oder nur offline. Dauer unbegrenzt, 1 Stunde bis 7 Tage oder bis zu einem Datum.
  - Die Timeline auf der Karte zeigt Online-Punkte grün und Offline-Punkte blau, dazu Aufenthalte und GPX-Export.
  - Nachgelieferte Offline-Berichte werden automatisch an der richtigen Stelle einsortiert. Punkte in Aufzeichnungen bleiben von der Aufbewahrung unberührt.
- **AirPods** (geschätzt):
  - **Case-Status:** „Im Case“, „Draußen“ oder „Teilweise draußen“. Grundlage sind Offline-Ortungen der Ohrhörer, aktive iCloud-Audiokanäle und das Statusbyte.
  - **Getrennt-Erkennung:** links ↔ rechts ↔ Case. Erst nach mehreren getrennten Ortungen zur gleichen Zeit gilt ein Teil als getrennt.
  - **Benachrichtigungen:** „aus dem Case genommen“, „wieder im Case“ und „getrennt“. Wahlweise immer oder einmalig, mit Stufe bis kritisch.
- **Datenquellen-Übersicht:** zeigt pro Gerät, woher welche Daten kommen.

### Benachrichtigungen (Bark)

- Installiere die App [Bark](https://apps.apple.com/app/id1403753865) und füge in **Ich** deine Push-URL ein.
- Es gibt die Stufen **Leise, Normal, Dringend und Kritisch**. Kritische Hinweise durchbrechen Stumm- und Fokus-Modus, die Lautstärke ist einstellbar.
- Ruhezeiten sind möglich.
- Ein Antippen öffnet das Objekt oder Gerät direkt in der App.

### Sicherheit

- Server-Login mit Passwort, optional **TOTP-2FA** (QR-Code für die Passwörter-App) und **Passkeys** (WebAuthn).
- Angemeldete Geräte siehst du und kannst sie abmelden. Die Anmeldung wird gedrosselt, Passwörter sind mit scrypt gehasht.
- Die App speichert ihr Token im Schlüsselbund und pinnt selbstsignierte Zertifikate.

### Web-App

Unter der Server-Adresse findest du Karte, Verlauf mit Zeitleiste, Apple-Login, Import, Passkeys und Export (GPX, CSV, JSON).

---

## Firewall / Netzwerk

Der Server braucht fast nur **ausgehendes HTTPS (TCP 443)**.

| Richtung | Ziel | Port | Wofür |
|---|---|---|---|
| eingehend | Server | **5070** TCP | App und Web-App |
| ausgehend | `gsa.apple.com`, `setup.icloud.com`, `gateway.icloud.com` | 443 | Apple-Login und Offline-Standorte |
| ausgehend | `idmsa.apple.com`, `*.icloud.com` | 443 | Online-Ortung (iCloud „Geräte suchen“) |
| ausgehend | `anisette.dl.mikealmel.ooo` | 443 | einmalig beim ersten Login |
| ausgehend | `api.day.app` oder eigener Bark-Server | 443 | Push-Benachrichtigungen |
| ausgehend | `nominatim.openstreetmap.org` | 443 | Adressen in Mitteilungen (optional) |
| ausgehend | `pypi.org`, `files.pythonhosted.org` | 443 | Installation und Updates der Pakete |
| ausgehend | DNS 53, NTP 123 | UDP | Namensauflösung, genaue Uhrzeit für 2FA |

Am einfachsten erlaubst du **17.0.0.0/8 ausgehend auf 443**, das ist der IP-Bereich von Apple. Nimm `*.icloud.com` außerdem von einer **TLS-Inspektion** aus, sonst schlägt die Zertifikatsprüfung fehl. Fehlt IPv6, fällt der Server automatisch auf IPv4 zurück.

---

## API

Alle Aufrufe brauchen `Authorization: Bearer <token>` (aus `POST /api/auth/login`). Live-Ereignisse kommen per Server-Sent Events über `GET /api/events`.

| Bereich | Endpunkte |
|---|---|
| Auth | `POST /api/auth/login` · `/logout` · `/password` · `/totp/*` · `/passkey/*` · `GET /api/auth/me` |
| Status & Einstellungen | `GET /api/status` · `GET/PUT /api/settings` · `POST /api/bark/test` · `GET/DELETE /api/notifications` · `GET /api/new?since=` |
| Apple-Login | `GET /api/apple/status` · `POST /api/apple/login` · `/2fa/request` · `/2fa/submit` · `/logout` |
| Objekte | `GET /api/devices` · `GET/PATCH/DELETE /api/devices/{id}` · `GET /api/devices/{id}/reports` · `/stays` · `/keys` · `POST /api/import` · `POST /api/refresh` |
| Apple-Geräte | `GET/POST /api/apple-devices` · `POST /api/apple-devices/refresh` · `PATCH/DELETE /api/apple-devices/{id}` · `POST …/{id}/offline?role=main\|left\|right\|case` · `DELETE …/{id}/offline/{role}` · `POST …/{id}/sound` · `…/message` · `…/lost` · `GET …/{id}/raw` |
| Aufzeichnungen | `GET/POST /api/apple-devices/{id}/sessions` · `GET /api/sessions/{sid}/points` · `POST /api/sessions/{sid}/stop` · `PATCH/DELETE /api/sessions/{sid}` |
| iCloud | `POST /api/icloud/connect` · `/2fa/sms` · `/2fa/submit` · `/disconnect` |
| Export | `GET /export.gpx` · `/export.csv` · `/export.json` (`?since=&until=&device=`) |

Geräte-IDs von Apple enthalten `/`, `+` und `=`. Kodiere sie im Pfad (z. B. `%2F`).

---

## Aufbau des Repos

```
server/
  findmy_ultra.py        # kompletter Server inkl. Web-App (eine Datei)
  requirements.txt
ios/
  project.yml            # XcodeGen-Projekt
  FindMyUltra/           # SwiftUI-App (Liquid Glass, iOS 26)
    AppModel.swift, APIClient.swift, Models.swift
    Views/               # Karte, Objekte, Geräte, Aufzeichnungen, Einstellungen …
.github/workflows/ios.yml  # baut die unsignierte IPA (macos-26 + macos-15)
```

---

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| Build hängt in der Warteschlange | GitHub hat keinen freien Mac. Abwarten oder neu starten. Nach 15 Minuten in der Warteschlange bricht GitHub den Job ab. Bei privaten Repos zählen Mac-Minuten zehnfach (Settings → Billing → Usage). |
| Online-Ortung: „Network is unreachable“ | IPv6 fehlt. Der Server nutzt automatisch IPv4. |
| Online-Ortung: Zertifikatsfehler | TLS-Inspektion der Firewall für `*.icloud.com` abschalten. |
| Online-Ortung: Sitzung abgelaufen | Geräte → „Online-Ortung verbinden“ und den Code erneut bestätigen. |
| Import zeigt „bereits als Objekt importiert“ | Dieselbe Schlüsseldatei kann nicht gleichzeitig Objekt und Gerät sein. Entferne zuerst das Objekt. |
| Zugangsdaten vergessen | `server/data/credentials.json` löschen und den Server neu starten. |
