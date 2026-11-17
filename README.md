# FindMy Ultra

Live-Ortung und lückenloser Standortverlauf für deine **eigenen** AirTags und Wo-ist-Zubehörteile.
Das Projekt hat zwei Teile:

* **`server/findmy_ultra.py`**: eine einzige Python-Datei. Sie meldet sich (über [FindMy.py](https://github.com/malmeloo/FindMy.py)) bei Apple an, holt laufend alle Standortberichte und speichert sie in SQLite. Sie stellt eine HTTP-API und eine kleine Web-App bereit und verschickt Alarme über **Bark**.
* **`ios/`**: eine iOS-App in SwiftUI mit Liquid Glass (iOS 26) und Apple Karten. Eine GitHub-Action baut sie als **unsignierte IPA**, die du sideloadest.

Die Schlüssel extrahiert das Projekt nicht. Du importierst deine vorhandenen JSON- oder plist-Schlüsseldateien.

---

## 1. Server starten

```bash
cd server
python3 findmy_ultra.py                # legt beim ersten Start .venv an und installiert alles
python3 findmy_ultra.py --self-signed  # HTTPS mit selbstsigniertem Zertifikat (App pinnt den Fingerabdruck)
python3 findmy_ultra.py --demo         # Demo-Daten zum Ausprobieren, ohne Apple
```

Du brauchst Python 3.10 oder neuer. Die Konsole zeigt die Adressen (z. B. `http://192.168.1.20:8787`) und **beim ersten Start Benutzer und Passwort**. Beides steht auch in `server/data/ERSTES-PASSWORT.txt`.

| Datei in `server/data/` | Inhalt |
|---|---|
| `credentials.json` | Server-Login (Passwort-Hash, TOTP, Passkeys). **Löschen ⇒ beim nächsten Start neue Zugangsdaten**, alle Sitzungen werden abgemeldet. |
| `apple_account.json` | Gespeicherte Apple-Sitzung |
| `accessories/*.json` | Importierte AirTag-Schlüssel (inkl. aktueller Schlüssel-Ausrichtung) |
| `findmy_ultra.sqlite3` | Standortverlauf, Geräte, Alarme, Einstellungen |

Optionen: `--port 8787`, `--host`, `--data DIR`, `--import DATEI|ORDNER`, `--tls-cert/--tls-key`, `--trust-proxy` (hinter Caddy, nginx oder Cloudflare), `--reset-password`.

**HTTP über IP:Port funktioniert** (die App erlaubt lokale und unverschlüsselte Verbindungen). Für **Passkeys** brauchst du eine HTTPS-Domain mit gültigem Zertifikat, z. B. über `caddy reverse-proxy --from findmy.example.com --to :8787`, Tailscale Serve oder einen Cloudflare Tunnel. Starte den Server dann mit `--trust-proxy`.

## 2. App installieren

1. Unter **Actions → „iOS IPA“** findest du `FindMyUltra-ipa` als Artefakt. Bei einem Tag `v*` landet die IPA zusätzlich im Release.
2. Sideloade sie mit AltStore, SideStore, Sideloadly oder TrollStore.
3. Gib in der App die Server-Adresse ein (`https://…` oder `192.168.1.20:8787`) und melde dich mit dem Server-Login an.
4. **Einstellungen → Apple-Account**: Apple-ID und Passwort eingeben, dann den 2FA-Code bestätigen (vertrauenswürdiges Gerät oder SMS).
5. **Einstellungen → Schlüssel importieren**: deine `.json`- oder `.plist`-Dateien auswählen (mehrere gleichzeitig möglich).

## Funktionen

* **Karte** (Apple Karten): alle Objekte mit Genauigkeitskreis, die Spur der letzten 24 h, Zonen und Kartenstile (Standard, Hybrid, Satellit).
* **Standortverlauf**: Jeder einzelne Bericht wird gespeichert. Die Verlaufsleiste hat einen Schieberegler, eine Dichte-Leiste und eine Wiedergabe-Funktion. Batch-Berichte und nachgereichte Berichte sind markiert. Export als GPX.
* **Aufbewahrung**: Standard sind 7 Tage, global oder pro Objekt einstellbar (bis unbegrenzt). Apple selbst liefert Berichte nur 7 Tage lang, deshalb sammelt der Server sie dauerhaft.
* **Möglichst viele Standorte**: Der Server bündelt die Schlüssel *aller* Objekte in wenigen Apple-Anfragen. Er ruft laufend die letzten Stunden ab, macht alle 10 min einen 24-h-Scan und stündlich einen 7-Tage-Scan. So landen auch Berichte im Verlauf, die iPhones gesammelt nachliefern. „Aktualisieren“ wartet, bis der Abruf fertig ist.
* **Alarme** (pro Objekt):
  * Plötzliche Entfernung (X m in Y min)
  * Wache bzw. Diebstahlschutz (Radius um den aktuellen Ort)
  * Zone betreten oder verlassen
  * Offline seit N Stunden
  * Batterie schwach
  * Jeder neue Standort
* **Verloren-Modus**: schnellerer Abruf (Standard alle 20 s) und bei jeder Sichtung sofort ein Hinweis, standardmäßig **kritisch**.
* **Bark**: Installiere die App [Bark](https://apps.apple.com/app/id1403753865) und füge deine Push-URL in den Einstellungen ein. Es gibt vier Stufen: Leise, Normal, Dringend und Kritisch. Kritische Hinweise durchbrechen den Stumm-Modus, die Lautstärke ist einstellbar. Ruhezeiten sind möglich. Tippst du auf einen Hinweis, öffnet sich das Objekt in FindMy Ultra.
* **Sicherheit**: Passwort ändern, optional TOTP-2FA (QR-Code für die Passwörter-App), Passkeys (WebAuthn über eine sichere Safari-Ansicht), angemeldete Geräte verwalten.
* **Web-App** unter der Server-Adresse: Karte, Verlauf mit Zeitleiste, Apple-Login, Import, Passkeys und Export (GPX, CSV, JSON).

## API (Auszug)

Alle Aufrufe brauchen `Authorization: Bearer <token>`.

| Methode | Pfad | |
|---|---|---|
| POST | `/api/auth/login` | `{username,password,totp?}` → `{token}` |
| GET | `/api/devices` | Objekte inkl. letztem Standort |
| GET | `/api/devices/{id}/reports?since=` | Verlauf |
| PATCH | `/api/devices/{id}` | Name, Emoji, Alarme, Verloren-Modus, Aufbewahrung |
| POST | `/api/refresh` | `{device_id?, full?, wait?}` |
| POST | `/api/import` | multipart mit `.json` und `.plist` |
| POST | `/api/apple/login`, `/api/apple/2fa/request`, `/api/apple/2fa/submit` | Apple-Anmeldung |
| GET/PUT | `/api/settings` | Abruf, Aufbewahrung, Bark, Zonen |
| GET | `/api/events` | Server-Sent Events (Live) |

---

FindMy Ultra nutzt inoffizielle Apple-Schnittstellen. Verwende es nur für deine eigenen Geräte.
