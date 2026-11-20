# CLAUDE.md – Leitfaden für die Weiterarbeit an FindMy Ultra

Diese Datei liest Claude Code in jeder neuen Sitzung automatisch. Sie fasst Aufbau, Regeln und bereits gelöste Stolperfallen zusammen. Bitte aktuell halten.

## Projekt in einem Satz

`server/findmy_ultra.py` ist eine einzige Python-Datei. Sie ortet die **eigenen** AirTags, Apple-Geräte, AirPods sowie (seit 1.7) Google-Find-Hub- und Samsung-SmartThings-Tracker des Nutzers (Wo-ist-Netzwerk über FindMy.py, online über iCloud mit pyicloud), speichert alles in SQLite und stellt API, Web-App und Bark-Alarme bereit. `ios/` ist die passende SwiftUI-App mit Liquid Glass für iOS 26, gebaut per GitHub Action als unsignierte IPA zum Sideloaden.

Der Nutzer spricht **Deutsch**. UI-Texte, Fehlermeldungen, Commits und Antworten bitte auf Deutsch.

## Goldene Regeln

1. **Vorhandene Daten müssen nach jedem Update weiter funktionieren.**
   - Schema-Änderungen nur über `CREATE TABLE IF NOT EXISTS` oder `ALTER TABLE … ADD COLUMN` in `Store.__init__`. Spalten nie löschen oder umbenennen.
   - Neue JSON-Felder mit Defaults über `deep_merge(DEFAULT_…, gespeichert)` einlesen.
   - In der App neue Felder **optional** und tolerant dekodieren (siehe `Flex` und `DeviceExtra` in `Models.swift`). Ein unerwarteter Typ darf nie die ganze Geräteliste kaputtmachen.
2. **Server bleibt eine einzige Datei.** Abhängigkeiten installiert `_bootstrap()` selbst. Optionale Pakete werden bei Bedarf nachinstalliert (Beispiel `OnlineDevices._ensure_lib` für pyicloud).
3. **Ein Release erhöht beide Versionen gemeinsam:**
   - `VERSION` in `server/findmy_ultra.py`
   - `MARKETING_VERSION` und `CURRENT_PROJECT_VERSION` in `ios/project.yml`
   - danach die README aktualisieren
4. **Konfiguration für den Nutzer** steht ganz oben in der Server-Datei (`PORT = 5070`, `HOST`). Der Port des Nutzers ist **5070**.
5. **Nie Geheimnisse committen.** Schlüsseldateien, `server/data/` und IPAs sind per `.gitignore` ausgeschlossen. Beispiel-Schlüsseldateien des Nutzers gehören nicht ins Repo.
6. **Apple-Account schützen.** Das Passwort nie automatisch wiederholt senden. Nach Fehlern drosseln (siehe `OnlineDevices.MIN_INTERVAL` und Backoff). Mehrere fehlgeschlagene Logins können den Account sperren.
7. **Keine destruktiven Fernaktionen.** „Gerät löschen“ (Remote Wipe) wird bewusst nicht angeboten.

## Aufbau

### Server (`server/findmy_ultra.py`, ca. 5.400 Zeilen, Abschnitte mit `═══`-Bannern)

| Bereich | Wichtige Namen |
|---|---|
| Einstellungen | `DEFAULT_SETTINGS`, `DEFAULT_ALERTS`, `DEFAULT_LOST`, `DEFAULT_APPLE_SETTINGS` |
| Datenbank | `Store`, Tabellen `devices` (`category`: `item` oder `apple_device`), `reports`, `online_reports`, `apple_devices`, `recordings`, `notifications`, `polls`, `sessions` (**Login-Sitzungen!**), `kv` |
| Auth | `Credentials` (`credentials.json`, löschen ⇒ neu erzeugt), TOTP, `WebAuthn` (Passkeys, eigener CBOR-Parser) |
| Wo-ist-Abruf | `Apple` (Login + 2FA), `Registry` (Schlüssel), `fetch_combined` (bündelt Schlüssel aller Geräte), `index_range`, `run_poll`, `scheduler` (Schnell-Abruf, 24 h, 7 Tage) |
| Online-Ortung | `OnlineDevices` (pyicloud: connect → 2FA → vertrauenswürdige Sitzung in `data/icloud/`; `_parse` liefert `extra` und bereinigte `raw`-Daten) |
| Apple-Geräte | `apple_device_public` (führt online und offline zusammen, `best`), `airpods_case_status`, `airpods_separation`, `check_case_alerts`, `session_points` |
| Auswertung | `compute_stays` (Aufenthalte mit Ausreißer-Toleranz) |
| Benachrichtigung | `Notifier` (Bark, Stufen, Ruhezeit), `Alerts` |
| Weitere Netze (1.7) | `Samsung` (Login über `ms-app://`-Rückleitung, SmartThings `execute`, ECIES mit Find-PIN), `GoogleServer` (GoogleFindMyTools in `data/google/venv`, `GOOGLE_BRIDGE_SOURCE`, `app_reports`), `networks_summary`, `ingest_network_reports`; Tracker liegen in `devices` mit `network`/`ext_id`, IDs über `network_device_id` |
| HTTP | `build_app` (aiohttp, Middleware für Auth, alle Routen am Ende), `WEB_HTML` (eingebettete Web-App) |

### App (`ios/FindMyUltra/`)

| Datei | Inhalt |
|---|---|
| `AppModel.swift` | zentraler `@Observable`-Zustand: Laden, Live-SSE, Fokus/Kamera, Verlauf, Aufzeichnungen, Apple-Geräte; merkt sich `section`, `sheetPath`, `detent` |
| `AppCache.swift` | letzter Stand (Objekte, Geräte, Status, Einstellungen) im Caches-Ordner → sofortiger Start ohne Splash |
| `APIClient.swift` | HTTP, Upload, SSE, TLS-Pinning; `APIClient.seg()` kodiert Pfadsegmente |
| `Models.swift` | alle Codable-Modelle (snake_case → camelCase automatisch) |
| `Views/MapScreen.swift` | Vollbild-Karte + dauerhaftes Sheet (`FindSheet` in `RootView.swift`) |
| `Views/DeviceDetailView.swift` | Objekt-Detail mit Verlauf |
| `Views/AppleDevicesViews.swift` | Geräte-Tab, Gerätedetail, iCloud verbinden |
| `Views/RecordingViews.swift` | Aufzeichnungen, Timeline, Case-Status-Karte, Datenquellen |
| `Views/DeviceExtrasViews.swift` | Gerätestatus aus iCloud, Nachricht, Verloren-Modus, Rohdaten, Trennungsanzeige |
| `Networks.swift` | `GoogleLink` (Spot → Server-Sync, Zugang übergeben, `inUse`), Netz-Filter-Logik, `mapItems`/`mapAppleDevices`/`isolating` (was die Karte zeigt), `locate(_:)` |
| `Views/NetworkViews.swift` | Netz-Filter-Leiste, Google- und Samsung-Seiten, Login-WebViews |
| `../Vendor/Spot/` | Google-Engine als Framework `SpotIntegration` (aus RJ TrackerApp, GPL-3.0); öffentliche API: `GoogleTrackerStore` |
| `Views/Components.swift` | Pins, Haptik, Zeitformat (`findMyTime`, `ageColor`), Glas-Bausteine |

Navigation im Sheet: `model.sheetPath: [DeviceRoute]` mit den Flags `apple` und `recording`.

## Build & Test

- **Server lokal testen:** `python3 server/findmy_ultra.py --demo --port 5071 --data /tmp/x`. Der Demo-Modus liefert Objekte und Apple-Geräte ohne Apple-Account. Danach mit `curl` gegen die API testen (Login-Passwort steht in `<data>/ERSTES-PASSWORT.txt`).
- **Syntax prüfen:** `python3 -c "import ast;ast.parse(open('server/findmy_ultra.py').read())"`
- **iOS:** Bauen lässt sich nur über GitHub Actions (`.github/workflows/ios.yml`, XcodeGen, `macos-26` und `macos-15` parallel), lokal gibt es kein Xcode. Mit `workflow_dispatch` starten und Fehler im Job-Log suchen (`error:`). Artefakt: `FindMyUltra-ipa-<runner>`.
  - GitHub-Macs stehen oft 5–15 Minuten in der Warteschlange. Nach 15 Minuten in der Warteschlange bricht GitHub den Job ab. Der Code ist dann nicht schuld.
  - Swift-Sprachmodus 5, Deployment-Target iOS 26.0.

## Gelöste Stolperfallen (nicht erneut einbauen!)

- **Apple-Geräte-IDs enthalten `/`, `+` und `=`.** Server-Routen nutzen `{id:.+}`, spezifische Routen werden zuerst registriert. Die App kodiert mit `APIClient.seg()` und setzt `percentEncodedPath`.
- **Online-Ortung über `fmipmobile.icloud.com` mit mme-Tokens** („Forever“, „UserIdGuest“) wird von Apple mit 401 `ResponseContentFilter` abgelehnt. Deshalb wird pyicloud genutzt (Web-API von iCloud.com „Geräte suchen“).
- **Zertifikate:** Viele Linux-Systeme kennen Apples Root-CA nicht. Für Apple-Verbindungen `findmy.util.tls.apple_trust_context()` nutzen. Bei TLS-Inspektion der Firewall des Nutzers `*.icloud.com` ausnehmen.
- **IPv6:** Fehlt eine IPv6-Route, gibt es „Network is unreachable“. Dann fällt der Server auf eine IPv4-Session zurück.
- **Namenskollision:** Tabelle und Methoden `sessions` gehören zu den **Login-Sitzungen**. Aufzeichnungen heißen `recordings` / `recording()` / `add_recording()` usw.
- **Mehrfach gleiche Funktionsnamen in `build_app`:** Lokale Handler-Namen müssen eindeutig sein, sonst überschreibt der spätere den früheren (Beispiel: `recording_delete` vs. `session_delete`).
- **FindMy.py `_login_mobileme()`** darf nur im Status AUTHENTICATED aufgerufen werden. Zum Auffrischen erst `_gsa_authenticate()`.
- **iOS-Dateiauswahl:** Statt SwiftUI-`fileImporter` den eigenen `DocumentPicker` nutzen (`asCopy: true`, alle Dateitypen). Sonst blieb „Öffnen“ ausgegraut. Zusätzlich gibt es das Einfügen aus der Zwischenablage.
- **Dieselbe Schlüsseldatei** darf nicht gleichzeitig Objekt (`item`) und Gerät (`apple_device`) sein. Der Server lehnt das mit 409 ab, damit beim Entfernen nichts verloren geht.
- **Apple-Anmeldung (seit Okt. 2026):** Apple akzeptiert nur noch eine macOS-Identität. Der Server nutzt FindMy.py/Anisette.py aus den Forks von sacca97 (PR #279 / #6, feste Commits in `REQUIREMENTS_PINNED`, Installation ohne git aus GitHub-Archiven, Schritt 2 mit `--no-deps`) und Apples echte `CoreADI` aus dem iTunes-12.8.3-Installer im Unicorn-Emulator (`AppleRuntime`, eingebettete Quellen `APPLE_COREADI_SOURCES`/`APPLE_ADI_BRIDGE`, Auspacken in reinem Python: UDIF → xar → Payload per SHA-1 suchen, da das .pkg im HFS+-Abbild fragmentiert ist). Alte Android-Sitzungen erkennt `apple_session_is_mac` und verlangt eine neue Anmeldung. Kein `libs_path` mehr an `LocalAnisetteProvider`/`from_json` übergeben (Fork wirft sonst). Sobald FindMy.py offiziell eine Lösung veröffentlicht, auf die PyPI-Version zurückwechseln.
- **Fremde Netze:** Gelöschte Google-/Samsung-Tracker stehen in `kv.network_ignored`, sonst legt die Synchronisierung sie wieder an. Alle Tracker-Code-Pfade (Apple-Polling, Registry) müssen `network != 'apple'` ignorieren.
- **Spot-Engine und Hintergrundmodi:** `allowsBackgroundLocationUpdates = true` und `CBCentralManagerOptionRestoreIdentifierKey` ohne angemeldeten Hintergrundmodus (`location` bzw. `bluetooth-central`) beenden die App sofort. Die Engine prüft das über `SpotBackgroundModes` (`EngineSupport.swift`). Die App meldet bewusst keine Hintergrundmodi an. Die Engine startet erst, wenn Google eingerichtet ist (`GoogleLink.inUse`). `inUse` erkennt eine bestehende Anmeldung am Schlüssel `username` in der Suite `de.findmyultra.spot` – sonst funktioniert Google nach einem Update nicht mehr (Fehler aus 1.7.1).
- **Karte:** Was angezeigt wird, entscheiden nur `mapItems` und `mapAppleDevices`. Im Geräte-Tab sind Apple-Geräte immer sichtbar, ist ein Verlauf oder eine Aufzeichnung offen (`isolating`), nur diese Spur.
- **Verlauf-Cursor:** `track`/`cursor` klemmen sich per `didSet` in den gültigen Bereich. Nicht entfernen, ungültige Indizes ließen die Karte abstürzen.
- **Workflows:** Pushes aus der Claude-Sitzung lösen keine `push`-Workflows aus. Über `pull_request` (offener PR) oder `workflow_dispatch` bauen.
- **Spot-Pakete:** Versionen in `ios/project.yml` exakt lassen (Digest 1.12.0 passt nur zu SwiftECC 5.4.0).
- **Aufbewahrung:** `Store.purge` schützt Zeiträume von Aufzeichnungen, damit Punkte darin nicht gelöscht werden.

## Fachliche Hinweise

- AirTags haben kein GPS. Standorte entstehen erst, wenn fremde Apple-Geräte vorbeikommen, mit Verzögerung und teils gebündelt (Batch) oder nachgereicht. Einsortiert wird immer nach Ortungszeit (`ts`), nicht nach Eingang.
- Statusbyte der Offline-Berichte: Bits 6–7 sind der Akku (voll/mittel/schwach/kritisch), Bits 4–5 der Gerätetyp (Apple/AirTag/Fremdhersteller/AirPods).
- Den AirPods-Case-Status liefert Apple nicht direkt. Er wird **geschätzt** (Ohrhörer senden eigenständig ⇒ draußen; aktive iCloud-Audiokanäle; Trennung erst nach mehreren Ortungen) und in der UI auch so gekennzeichnet.
- Die Firewall des Nutzers ist restriktiv. Benötigte Ziele stehen in der README unter „Firewall / Netzwerk“.

## Git

- `main` ist der Hauptbranch. Änderungen über einen Feature-Branch und Pull Request, Commit-Nachrichten auf Deutsch.
- Die Sitzungsumgebung kann keine Tags pushen (403). Releases mit Tag `v*` legt der Nutzer in der GitHub-Oberfläche an. Die Action hängt die IPA dann automatisch an.
