import SwiftUI
import MapKit
import UniformTypeIdentifiers

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var draft: ServerSettings?
    @State private var importing = false
    @State private var importResult: String?
    @State private var saving = false
    @State private var confirmDisconnect = false

    private var dirty: Bool { draft != nil && draft != model.settings }

    var body: some View {
        @Bindable var model = model
        Form {
            serverSection
            Section {
                NavigationLink {
                    AppleAccountView()
                } label: {
                    HStack {
                        Label("Apple-Account", systemImage: "apple.logo")
                        Spacer()
                        Text(model.status?.apple.isLoggedIn == true ? (model.status?.apple.accountName ?? "verbunden") : "nicht angemeldet")
                            .foregroundStyle(model.status?.apple.isLoggedIn == true ? Color.secondary : Color.orange)
                            .lineLimit(1)
                    }
                }
                Button {
                    importing = true
                } label: {
                    Label("Schlüssel importieren (.json / .plist)", systemImage: "square.and.arrow.down.on.square")
                }
                Button {
                    Task { await importFromClipboard() }
                } label: {
                    Label("JSON aus Zwischenablage einfügen", systemImage: "doc.on.clipboard")
                }
                if let importResult { Text(importResult).font(.footnote) }
            } header: {
                Text("Apple & Objekte")
            } footer: {
                Text("Importiere die exportierten AirTag-Schlüssel (FindMy.py-/export-findmy-JSON oder entschlüsselte .plist). Mehrere Dateien gleichzeitig möglich.")
            }

            if draft != nil {
                pollingSection
                historySection
                appleSection
                staysSection
                barkSection
                zonesSection
            }

            Section {
                Toggle("Gründlich aktualisieren", isOn: $model.thoroughRefresh)
                    .onChange(of: model.thoroughRefresh) { _, _ in Haptics.light() }
                Toggle("Mitteilungen in der App", isOn: $model.inAppNotifications)
                    .onChange(of: model.inAppNotifications) { _, _ in Haptics.light() }
                NavigationLink { SecurityView() } label: {
                    Label("Sicherheit (Passwort, 2FA, Passkeys)", systemImage: "lock.shield")
                }
            } header: {
                Text("App")
            } footer: {
                Text("„Gründlich“: Jedes Aktualisieren startet Schnell-Abruf, 24-h- und 7-Tage-Scan gleichzeitig (gebündelt in einer Abfrage) – so landen auch nachgelieferte Standorte sofort im Verlauf.")
            }

            Section {
                Button("Abmelden", role: .destructive) { confirmDisconnect = true }
            } footer: {
                Text("FindMy Ultra \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "") · Server \(model.status?.version ?? "–")")
            }
        }
        .scrollContentBackground(.hidden)
        .safeAreaInset(edge: .top, spacing: 0) {
            HStack {
                Text("Ich").font(.largeTitle.bold())
                Spacer()
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
        }
        .safeAreaInset(edge: .bottom) {
            if dirty {
                GlassEffectContainer(spacing: 10) {
                    HStack(spacing: 10) {
                        Button("Verwerfen") { Haptics.light(); draft = model.settings }
                            .buttonStyle(.glass)
                        Button {
                            Task { await save() }
                        } label: {
                            Text(saving ? "Sichere …" : "Änderungen sichern").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.glassProminent)
                        .disabled(saving)
                    }
                    .controlSize(.large)
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 8)
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.spring(duration: 0.3), value: dirty)
        .onAppear { if draft == nil { draft = model.settings } }
        .onChange(of: model.settings) { old, new in if draft == nil || draft == old { draft = new } }
        .sheet(isPresented: $importing) {
            DocumentPicker { urls in
                importing = false
                Task { await handleImport(.success(urls)) }
            } onCancel: {
                importing = false
            }
            .ignoresSafeArea()
        }
        .confirmationDialog("Vom Server abmelden?", isPresented: $confirmDisconnect, titleVisibility: .visible) {
            Button("Abmelden", role: .destructive) { Task { await model.logout() } }
        }
    }

    // MARK: Abschnitte

    private var serverSection: some View {
        Section("Server") {
            LabeledContent("Adresse", value: model.serverURLString)
            HStack {
                Text("Verbindung")
                Spacer()
                LiveDot(on: model.liveConnected)
                Text(model.liveConnected ? "Live" : "getrennt").foregroundStyle(.secondary)
            }
            if let s = model.status {
                LabeledContent("Standorte gespeichert", value: "\(s.stats.total)")
                LabeledContent("Anfragen heute", value: "\(s.stats.requestsToday ?? 0)")
                if let e = s.lastError { Text(e).font(.footnote).foregroundStyle(.orange) }
                if s.demo { Label("Demo-Modus", systemImage: "theatermasks") }
            }
            if model.me?.passwordIsGenerated == true {
                NavigationLink { SecurityView() } label: {
                    Label("Bitte das generierte Passwort ändern", systemImage: "exclamationmark.shield.fill")
                        .foregroundStyle(.orange)
                }
            }
        }
    }

    private var draftBinding: Binding<ServerSettings> {
        Binding(get: { draft ?? model.settings! }, set: { draft = $0 })
    }

    private var pollingSection: some View {
        let d = draftBinding
        return Section {
            Picker("Abruf-Intervall", selection: d.pollInterval) {
                ForEach([20, 30, 45, 60, 90, 120, 300, 600], id: \.self) { Text(secs($0)).tag($0) }
            }
            Picker("Verloren/Wache", selection: d.lostPollInterval) {
                ForEach([10, 15, 20, 30, 45, 60], id: \.self) { Text(secs($0)).tag($0) }
            }
            Stepper("Schnell-Fenster: \(Int(d.wrappedValue.quickHours)) h", value: d.quickHours, in: 1...48)
            Stepper("24-h-Scan alle \(d.wrappedValue.daySweepMinutes) min", value: d.daySweepMinutes, in: 2...120)
            Stepper("7-Tage-Scan alle \(d.wrappedValue.fullSweepMinutes) min", value: d.fullSweepMinutes, in: 10...720, step: 10)
            TextField("Anisette-Server (leer = lokal)", text: d.anisetteServer)
                .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
        } header: {
            Text("Abruf")
        } footer: {
            Text("Der Server bündelt die Schlüssel aller Objekte in wenigen Anfragen. Regelmäßige 24-h- und 7-Tage-Scans holen nachgereichte Batch-Berichte, damit dein Verlauf lückenlos wird.")
        }
    }

    private var historySection: some View {
        let d = draftBinding
        return Section {
            Picker("Standortverlauf", selection: d.retentionDays) {
                ForEach([1, 3, 7, 14, 30, 60, 90, 180, 365], id: \.self) { Text("\($0) Tage").tag($0) }
                Text("Unbegrenzt").tag(0)
            }
            Toggle("Adressen in Mitteilungen (OpenStreetMap)", isOn: d.geocode)
        } header: {
            Text("Verlauf")
        } footer: {
            Text("Standard: 7 Tage für alle Objekte. Pro Objekt unter „Bearbeiten“ änderbar.")
        }
    }

    private var barkSection: some View {
        let d = draftBinding
        let keys = Binding<String>(
            get: { d.wrappedValue.bark.deviceKeys.joined(separator: ", ") },
            set: { d.wrappedValue.bark.deviceKeys = $0.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty } }
        )
        return Section {
            Toggle("Bark-Push aktivieren", isOn: d.bark.enabled)
            TextField("Bark-Server", text: d.bark.server)
                .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
            TextField("Geräte-Key(s) oder Bark-URL", text: keys)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            LevelPicker(title: "Mindest-Stufe", level: d.bark.minLevel)
            VStack(alignment: .leading) {
                Text("Lautstärke kritischer Hinweise: \(d.wrappedValue.bark.criticalVolume)")
                Slider(value: Binding(get: { Double(d.wrappedValue.bark.criticalVolume) },
                                      set: { d.wrappedValue.bark.criticalVolume = Int($0) }), in: 0...10, step: 1)
            }
            TextField("Ton kritisch (z. B. alarm)", text: d.bark.criticalSound)
                .textInputAutocapitalization(.never)
            TextField("Ton normal (leer = Standard)", text: d.bark.sound)
                .textInputAutocapitalization(.never)
            TextField("Gruppe", text: d.bark.group)
            Toggle("Ruhezeit (nicht-kritisch leise)", isOn: d.quietHours.enabled)
            if d.wrappedValue.quietHours.enabled {
                HStack {
                    TextField("Start", text: d.quietHours.start).keyboardType(.numbersAndPunctuation)
                    Text("bis")
                    TextField("Ende", text: d.quietHours.end).keyboardType(.numbersAndPunctuation)
                }
            }
            HStack {
                Button("Test") { Task { await testBark("active") } }.buttonStyle(.glass)
                Button("Test kritisch") { Task { await testBark("critical") } }.buttonStyle(.glass).tint(.red)
                Spacer()
                Link("Bark laden", destination: URL(string: "https://apps.apple.com/app/id1403753865")!)
                    .font(.footnote)
            }
        } header: {
            Text("Benachrichtigungen (Bark)")
        } footer: {
            Text("Installiere die App „Bark“, kopiere deine Push-URL (https://api.day.app/DEINKEY) und füge sie hier ein. Kritische Hinweise durchbrechen Stumm- und Fokus-Modus. Erst „Sichern“, dann testen.")
        }
    }

    @ViewBuilder
    private var appleSection: some View {
        let d = draftBinding
        if d.wrappedValue.onlineDevices != nil {
            let od = Binding<OnlineDevicesConfig>(get: { d.wrappedValue.onlineDevices! }, set: { d.wrappedValue.onlineDevices = $0 })
            Section {
                Toggle("Online-Ortung (iCloud)", isOn: od.enabled)
                Picker("Abfrage alle", selection: od.interval) {
                    ForEach([60, 120, 300, 600, 1800], id: \.self) { Text(secs($0)).tag($0) }
                }
                if let e = model.onlineStatus?.error { Text(e).font(.footnote).foregroundStyle(.orange) }
            } header: {
                Text("Apple-Geräte")
            } footer: {
                Text("Optional: Fragt die Online-Standorte deiner iPhones, iPads, Macs, Watches und AirPods mit derselben Apple-Anmeldung ab. Offline-Standorte kommen zusätzlich über importierte Schlüsseldateien im Geräte-Tab. Kein Standortverlauf.")
            }
        }
    }

    @ViewBuilder
    private var staysSection: some View {
        let d = draftBinding
        if d.wrappedValue.stays != nil {
            let st = Binding<StaysConfig>(get: { d.wrappedValue.stays! }, set: { d.wrappedValue.stays = $0 })
            Section {
                Stepper("Umkreis: \(Int(st.wrappedValue.radiusM)) m", value: st.radiusM, in: 30...1000, step: 10)
                Stepper("Mindestdauer: \(Int(st.wrappedValue.minMinutes)) min", value: st.minMinutes, in: 1...240)
                Stepper("Mind. Berichte: \(st.wrappedValue.minPoints)", value: st.minPoints, in: 1...20)
                Stepper("Ausreißer tolerieren: \(st.wrappedValue.maxOutliers)", value: st.maxOutliers, in: 0...20)
                Stepper("… innerhalb von \(Int(st.wrappedValue.outlierMinutes)) min", value: st.outlierMinutes, in: 5...240, step: 5)
                Stepper("Zusammenfassen bis \(Int(st.wrappedValue.mergeMinutes)) min Lücke", value: st.mergeMinutes, in: 0...240, step: 5)
                Stepper("Max. Funkstille: \(Int(st.wrappedValue.maxGapHours)) h", value: st.maxGapHours, in: 1...48)
                Stepper("Ungenau ab: \(Int(st.wrappedValue.maxAccuracyM)) m", value: st.maxAccuracyM, in: 50...5000, step: 50)
            } header: {
                Text("Aufenthalte")
            } footer: {
                Text("Ein Aufenthalt ist ein Ort, an dem das Objekt mindestens die Mindestdauer im Umkreis war. Einzelne Ausreißer (falsche Ortungen) brechen ihn nicht ab, solange das Objekt danach wieder dort geortet wird. Ungenauere Berichte zählen nur, wenn sie in den Umkreis passen. Wird live aus allen Berichten berechnet.")
            }
        }
    }

    private var zonesSection: some View {
        Section {
            ForEach(draftBinding.zones) { $z in
                NavigationLink {
                    ZoneEditor(zone: $z)
                } label: {
                    VStack(alignment: .leading) {
                        Text(z.name)
                        Text("Radius \(formatDistance(z.radius))").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .onDelete { draft?.zones.remove(atOffsets: $0) }
            Button {
                let c = model.devices.compactMap(\.last).first?.coordinate
                    ?? LocationPermission.manager.location?.coordinate
                    ?? CLLocationCoordinate2D(latitude: 52.52, longitude: 13.405)
                draft?.zones.append(Zone(id: String(UUID().uuidString.prefix(8)).lowercased(), name: "Neue Zone",
                                         lat: c.latitude, lon: c.longitude, radius: 150))
            } label: {
                Label("Zone hinzufügen", systemImage: "plus.circle")
            }
        } header: {
            Text("Zonen")
        } footer: {
            Text("Für Alarme beim Betreten/Verlassen (pro Objekt unter „Alarme“ aktivieren).")
        }
    }

    // MARK: Logik

    private func secs(_ s: Int) -> String { s >= 60 ? "\(s / 60) min\(s % 60 > 0 ? " \(s % 60) s" : "")" : "\(s) s" }

    private func save() async {
        guard let d = draft else { return }
        saving = true
        defer { saving = false }
        do {
            try await model.saveSettings(d)
            draft = model.settings
            Haptics.success()
            model.showToast("Gesichert")
        } catch {
            Haptics.warning()
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }

    private func testBark(_ level: String) async {
        if dirty { await save() }
        do {
            let r: OKResult = try await model.api!.send("POST", "/api/bark/test", json: ["level": level])
            model.showToast(r.ok == true ? "✅ Test gesendet" : "⚠️ \(r.error ?? "Fehler")")
        } catch {
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }

    private func importFromClipboard() async {
        guard let text = UIPasteboard.general.string, !text.isEmpty else {
            importResult = "❌ Zwischenablage ist leer – öffne die JSON-Datei, „Alles auswählen“ → „Kopieren“."
            return
        }
        await upload([("zwischenablage.json", Data(text.utf8))])
    }

    private func upload(_ files: [(name: String, data: Data)]) async {
        importResult = "Importiere \(files.count) Datei(en) …"
        importResult = await KeyImporter.upload(files, model: model)
    }

    private func handleImport(_ result: Result<[URL], Error>) async {
        guard case .success(let urls) = result else { return }
        var files: [(name: String, data: Data)] = []
        for u in urls {
            let ok = u.startAccessingSecurityScopedResource()
            defer { if ok { u.stopAccessingSecurityScopedResource() } }
            if let d = try? Data(contentsOf: u) { files.append((u.lastPathComponent, d)) }
        }
        guard !files.isEmpty else {
            importResult = "❌ Datei konnte nicht gelesen werden"
            return
        }
        await upload(files)
    }
}

// MARK: - Zone bearbeiten

struct ZoneEditor: View {
    @Binding var zone: Zone
    @State private var position: MapCameraPosition = .automatic
    @State private var center: CLLocationCoordinate2D?

    var body: some View {
        Form {
            Section {
                TextField("Name", text: $zone.name)
                Stepper("Radius \(formatDistance(zone.radius))", value: $zone.radius, in: 25...10000, step: 25)
            }
            Section {
                Map(position: $position) {
                    MapCircle(center: center ?? zone.coordinate, radius: zone.radius)
                        .foregroundStyle(.blue.opacity(0.15))
                        .stroke(.blue, lineWidth: 2)
                    UserAnnotation()
                }
                .overlay { Image(systemName: "plus").font(.title2.bold()).foregroundStyle(.blue) }
                .onMapCameraChange(frequency: .onEnd) { ctx in
                    center = ctx.region.center
                    zone.lat = ctx.region.center.latitude
                    zone.lon = ctx.region.center.longitude
                }
                .frame(height: 320)
                .listRowInsets(EdgeInsets())
            } footer: {
                Text("Karte verschieben, um den Mittelpunkt festzulegen. Danach in den Einstellungen „Sichern“.")
            }
        }
        .navigationTitle(zone.name)
        .onAppear {
            position = .region(MKCoordinateRegion(center: zone.coordinate, latitudinalMeters: zone.radius * 5,
                                                  longitudinalMeters: zone.radius * 5))
        }
    }
}
