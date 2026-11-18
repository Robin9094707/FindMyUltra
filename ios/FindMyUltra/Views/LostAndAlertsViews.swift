import SwiftUI

// MARK: - Verloren-Modus

struct LostModeView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let device: Device
    @State private var lost: LostConfig
    @State private var saving = false

    init(device: Device) {
        self.device = device
        _lost = State(initialValue: device.lost)
    }

    var body: some View {
        Form {
            Section {
                VStack(spacing: 12) {
                    Image(systemName: lost.enabled ? "exclamationmark.triangle.fill" : "exclamationmark.triangle")
                        .font(.system(size: 48))
                        .foregroundStyle(.red)
                        .symbolEffect(.pulse, isActive: lost.enabled)
                    Text(lost.enabled ? "\(device.name) wird gesucht" : "Verloren-Modus")
                        .font(.title2.bold())
                    Text("Der Server ruft das Objekt alle \(model.settings?.lostPollInterval ?? 20) s ab und schickt bei jeder Sichtung sofort eine Benachrichtigung – auf Wunsch als kritischen Hinweis über Bark, der auch den Stumm-Modus durchbricht.")
                        .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    if let since = lost.since, lost.enabled {
                        Text("Aktiv seit \(Date(timeIntervalSince1970: since).shortDE)").font(.caption.bold())
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
                Toggle("Als verloren markieren", isOn: $lost.enabled.animation())
                    .tint(.red)
            }
            Section("Benachrichtigung bei Fund") {
                LevelPicker(title: "Stufe", level: $lost.level)
                Toggle("Bei jeder neuen Sichtung", isOn: $lost.notifyEveryReport)
            }
            Section {
                TextField("Notiz (z. B. wo zuletzt gesehen)", text: $lost.message, axis: .vertical)
                TextField("Kontakt-Telefon", text: $lost.phone).keyboardType(.phonePad)
            } header: {
                Text("Notizen")
            } footer: {
                Text("Hinweis: Der Verloren-Modus von Apple (Nachricht beim Antippen per NFC) kann nur über die Wo-ist-App gesetzt werden. Diese Angaben dienen deiner Dokumentation.")
            }
            if let r = device.last {
                Section("Letzte Sichtung") {
                    LabeledContent("Zeit", value: r.date.shortDE)
                    LabeledContent("Genauigkeit", value: "±\(r.accuracy ?? 0) m")
                    Button("Jetzt orten") { Task { await model.refresh(deviceID: device.id) } }
                }
            }
        }
        .navigationTitle("Verloren-Modus")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Sichern") { Task { await save() } }.disabled(saving)
            }
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            try await model.patchDevice(device.id, encodable: ["lost": lost])
            model.showToast(lost.enabled ? "🚨 Verloren-Modus aktiv" : "Verloren-Modus beendet")
            dismiss()
        } catch {
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }
}

// MARK: - Alarme

struct AlertSettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let device: Device
    @State private var a: AlertConfig
    @State private var saving = false

    init(device: Device) {
        self.device = device
        _a = State(initialValue: device.alerts)
    }

    var body: some View {
        Form {
            Section {
                Toggle("Plötzliche Entfernung", isOn: $a.movement.enabled)
                if a.movement.enabled {
                    Stepper("Ab \(formatDistance(a.movement.distanceM))", value: $a.movement.distanceM, in: 50...20000, step: 50)
                    Stepper("Innerhalb von \(Int(a.movement.windowMin)) min", value: $a.movement.windowMin, in: 5...720, step: 5)
                    LevelPicker(title: "Stufe", level: $a.movement.level)
                }
            } header: {
                Label("Bewegung", systemImage: "figure.run")
            } footer: {
                Text("Alarm, wenn sich das Objekt in kurzer Zeit weiter als die Distanz entfernt (Ungenauigkeit wird herausgerechnet).")
            }

            Section {
                Toggle("Wache (Diebstahlschutz)", isOn: $a.guardMode.enabled)
                Stepper("Radius \(formatDistance(a.guardMode.radiusM))", value: $a.guardMode.radiusM, in: 30...5000, step: 10)
                LevelPicker(title: "Stufe", level: $a.guardMode.level)
                if let t = a.guardMode.armedAt, a.guardMode.enabled {
                    LabeledContent("Scharf seit", value: Date(timeIntervalSince1970: t).shortDE)
                }
            } header: {
                Label("Wache", systemImage: "shield.lefthalf.filled")
            } footer: {
                Text("Merkt sich den aktuellen Standort. Sobald das Objekt außerhalb des Radius gesichtet wird, kommt (alle 2 min) ein Alarm. Ideal fürs Fahrrad oder Auto.")
            }

            Section {
                Toggle("Zonen betreten/verlassen", isOn: $a.zones.enabled)
                LevelPicker(title: "Stufe", level: $a.zones.level)
            } header: {
                Label("Zonen", systemImage: "circle.dashed")
            } footer: {
                Text("Zonen legst du unter Einstellungen → Zonen an (z. B. Zuhause, Arbeit).")
            }

            Section {
                Toggle("Bei neuem Standort", isOn: $a.newReport.enabled)
                if a.newReport.enabled {
                    Stepper("Höchstens alle \(Int(a.newReport.minIntervalMin)) min", value: $a.newReport.minIntervalMin, in: 0...1440, step: 5)
                    LevelPicker(title: "Stufe", level: $a.newReport.level)
                }
            } header: {
                Label("Neue Standorte", systemImage: "mappin.and.ellipse")
            }

            Section {
                Toggle("Meldet sich nicht", isOn: $a.offline.enabled)
                if a.offline.enabled {
                    Stepper("Nach \(Int(a.offline.hours)) h ohne Standort", value: $a.offline.hours, in: 1...168)
                    LevelPicker(title: "Stufe", level: $a.offline.level)
                }
            } header: {
                Label("Offline", systemImage: "antenna.radiowaves.left.and.right.slash")
            }

            Section {
                Toggle("Batterie schwach", isOn: $a.battery.enabled)
                LevelPicker(title: "Stufe", level: $a.battery.level)
            } header: {
                Label("Batterie", systemImage: "battery.25percent")
            }
        }
        .navigationTitle("Alarme · \(device.name)")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Sichern") { Task { await save() } }.disabled(saving)
            }
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        var cfg = a
        if cfg.guardMode.enabled && !device.alerts.guardMode.enabled {
            cfg.guardMode.lat = nil
            cfg.guardMode.lon = nil
            cfg.guardMode.armedAt = nil
        }
        do {
            try await model.patchDevice(device.id, encodable: ["alerts": cfg])
            if model.settings?.bark.enabled != true {
                model.showToast("Gesichert – richte Bark ein, um Push-Hinweise zu bekommen")
            }
            dismiss()
        } catch {
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }
}

// MARK: - Mitteilungen

struct NotificationsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        List {
            if model.notifications.isEmpty {
                ContentUnavailableView("Keine Mitteilungen", systemImage: "bell.slash",
                                       description: Text("Alarme (Bewegung, Wache, Zonen, Verloren-Modus …) erscheinen hier und – mit Bark – als Push."))
                    .listRowBackground(Color.clear)
            }
            ForEach(model.notifications) { n in
                Button {
                    if let id = n.deviceId, model.device(id) != nil { model.openDevice(id) }
                } label: {
                    HStack(alignment: .top, spacing: 12) {
                        let lvl = AlertLevel.of(n.level)
                        Image(systemName: lvl.icon)
                            .font(.title3)
                            .foregroundStyle(lvl.color)
                            .frame(width: 36, height: 36)
                            .glassEffect(.regular.tint(lvl.color.opacity(0.25)), in: .circle)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(n.title).font(.subheadline.bold())
                            Text(n.body).font(.footnote).foregroundStyle(.secondary)
                            HStack(spacing: 6) {
                                Text(n.date.relativeDE)
                                if n.delivered == true { Label("Bark", systemImage: "checkmark") }
                                else if let e = n.error, e != "Bark nicht eingerichtet" { Label(e, systemImage: "xmark").lineLimit(1) }
                            }
                            .font(.caption2).foregroundStyle(.tertiary)
                        }
                    }
                }
                .buttonStyle(.plain)
                .listRowBackground(Color(.secondarySystemGroupedBackground).opacity(0.6))
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .refreshable { await model.reloadNotifications() }
        .safeAreaInset(edge: .top, spacing: 0) {
            HStack {
                Text("Mitteilungen").font(.largeTitle.bold())
                Spacer()
                if !model.notifications.isEmpty {
                    Button("Leeren", role: .destructive) {
                        Haptics.light()
                        Task {
                            _ = try? await model.api?.send("DELETE", "/api/notifications", as: OKResult.self)
                            model.notifications = []
                        }
                    }
                    .buttonStyle(.glass)
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
        }
        .task { await model.reloadNotifications() }
    }
}
