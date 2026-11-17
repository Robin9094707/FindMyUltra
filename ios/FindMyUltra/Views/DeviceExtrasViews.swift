import SwiftUI

// MARK: - Gerätestatus aus iCloud (Zusatzinfos + Aktionen)

struct DeviceStatusCard: View {
    @Environment(AppModel.self) private var model
    let device: AppleDevice
    @State private var sheet: Kind?

    enum Kind: String, Identifiable { case message, lost, raw; var id: String { rawValue } }

    private var x: DeviceExtra? { device.extra }

    var body: some View {
        GlassSection(title: "Gerätestatus (iCloud)", systemImage: "iphone.gen3.radiowaves.left.and.right") {
            if !device.isCloud {
                Text("Nur für Geräte aus deinem Apple-Account (Online-Ortung verbinden).")
                    .font(.subheadline).foregroundStyle(.secondary)
            } else {
                Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                    if let b = device.batteryText {
                        row("Akku", "\(b) · \(chargeLabel(x?.batteryStatus?.text ?? device.batteryStatus))")
                    }
                    if let lp = x?.lowPowerMode { row("Stromsparmodus", lp.isTrue ? "An" : "Aus") }
                    if let p = x?.positionType?.text { row("Ortungsart", positionLabel(p)) }
                    if let a = x?.altitude?.number, a != 0 {
                        row("Höhe", String(format: "%.0f m%@", a, x?.verticalAccuracy?.number.map { String(format: " (±%.0f m)", $0) } ?? ""))
                    }
                    if let f = x?.floorLevel?.number { row("Stockwerk", String(Int(f))) }
                    if let le = x?.locationEnabled { row("Ortungsdienste", le.isTrue ? "An" : "Aus") }
                    if let lm = x?.lostModeEnabled {
                        row("Verloren-Modus", lm.isTrue ? "Aktiv" + (x?.lostNumber?.text.map { " · \($0)" } ?? "") : "Aus")
                    }
                    if let al = x?.activationLocked { row("Aktivierungssperre", al.isTrue ? "An" : "Aus") }
                    if let o = x?.owner?.text, !o.isEmpty { row("Gehört", o + (x?.family?.isTrue == true ? " (Familie)" : "")) }
                    if let c = x?.deviceColor?.text { row("Farbe", c) }
                    if let ch = x?.audioChannels, !ch.isEmpty {
                        row("Audiokanäle", ch.map { "\($0.name?.display ?? "?"): \($0.available?.isTrue == true ? "aktiv" : "–")" }.joined(separator: " · "))
                    }
                }
                .font(.subheadline)
                HStack(spacing: 8) {
                    Button { sheet = .message } label: { Label("Nachricht", systemImage: "text.bubble") }
                        .buttonStyle(.glass)
                        .disabled(x?.canMessage?.isTrue == false)
                    Button { sheet = .lost } label: { Label("Verloren", systemImage: "lock.fill") }
                        .buttonStyle(.glass).tint(.red)
                        .disabled(x?.canLost?.isTrue == false)
                    Button { sheet = .raw } label: { Label("Rohdaten", systemImage: "curlybraces") }
                        .buttonStyle(.glass)
                }
                .font(.subheadline)
            }
        }
        .sheet(item: $sheet) { k in
            NavigationStack {
                switch k {
                case .message: SendMessageView(device: device)
                case .lost: LostModeAppleView(device: device)
                case .raw: RawDataView(device: device)
                }
            }
            .presentationDetents([.medium, .large])
        }
    }

    private func chargeLabel(_ s: String?) -> String {
        switch s {
        case "Charging": "lädt"
        case "Charged": "voll geladen"
        case "NotCharging": "lädt nicht"
        default: s ?? "unbekannt"
        }
    }

    private func positionLabel(_ p: String) -> String {
        switch p.lowercased() {
        case "gps": "GPS"
        case "wifi": "WLAN"
        case "cell": "Mobilfunk"
        default: p
        }
    }

    private func row(_ k: String, _ v: String) -> some View {
        GridRow { Text(k).foregroundStyle(.secondary); Text(v) }
    }
}

struct SendMessageView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let device: AppleDevice
    @State private var subject = "FindMy Ultra"
    @State private var text = ""
    @State private var sound = true
    @State private var busy = false

    var body: some View {
        Form {
            Section {
                TextField("Titel", text: $subject)
                TextField("Nachricht", text: $text, axis: .vertical).lineLimit(3...6)
                Toggle("Mit Ton", isOn: $sound)
            } footer: {
                Text("Die Nachricht erscheint auf dem Display von „\(device.name)“, sobald es online ist.")
            }
        }
        .navigationTitle("Nachricht senden")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Senden") { Task { await send() } }.disabled(text.isEmpty || busy)
            }
        }
    }

    private func send() async {
        busy = true; defer { busy = false }
        do {
            let _: OKResult = try await model.api!.send("POST", "/api/apple-devices/\(APIClient.seg(device.id))/message",
                                                       json: ["subject": subject, "text": text, "sound": sound])
            Haptics.success(); model.showToast("Nachricht gesendet"); dismiss()
        } catch { Haptics.warning(); model.showToast("⚠️ \(error.localizedDescription)") }
    }
}

struct LostModeAppleView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let device: AppleDevice
    @State private var number = ""
    @State private var text = "Dieses Gerät wurde verloren. Bitte ruf mich an."
    @State private var confirm = false
    @State private var busy = false

    var body: some View {
        Form {
            Section {
                TextField("Telefonnummer", text: $number).keyboardType(.phonePad)
                TextField("Nachricht", text: $text, axis: .vertical).lineLimit(2...5)
            } footer: {
                Text("Aktiviert Apples Verloren-Modus auf „\(device.name)“: Das Gerät wird gesperrt, zeigt die Nachricht an und ein Finder kann dich direkt anrufen. Beenden kannst du ihn am Gerät (Code eingeben) oder auf iCloud.com.")
            }
            if device.extra?.lostModeEnabled?.isTrue == true {
                Section { Label("Verloren-Modus ist bereits aktiv", systemImage: "checkmark.seal.fill").foregroundStyle(.red) }
            }
        }
        .navigationTitle("Verloren-Modus")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Aktivieren") { confirm = true }.disabled(busy).tint(.red)
            }
        }
        .confirmationDialog("Verloren-Modus wirklich aktivieren?", isPresented: $confirm, titleVisibility: .visible) {
            Button("Aktivieren", role: .destructive) { Task { await activate() } }
        } message: { Text("Das Gerät wird sofort gesperrt.") }
    }

    private func activate() async {
        busy = true; defer { busy = false }
        do {
            let _: OKResult = try await model.api!.send("POST", "/api/apple-devices/\(APIClient.seg(device.id))/lost",
                                                       json: ["number": number, "text": text])
            Haptics.success(); model.showToast("Verloren-Modus aktiviert")
            await model.reloadAppleDevices(); dismiss()
        } catch { Haptics.warning(); model.showToast("⚠️ \(error.localizedDescription)") }
    }
}

struct RawDataView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let device: AppleDevice
    @State private var text = "Lädt …"

    var body: some View {
        ScrollView {
            Text(text)
                .font(.system(.caption, design: .monospaced))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
        }
        .navigationTitle("Rohdaten")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Schließen") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button { UIPasteboard.general.string = text; Haptics.success(); model.showToast("Kopiert") } label: {
                    Image(systemName: "doc.on.doc")
                }
            }
        }
        .task {
            guard let api = model.api else { return }
            do {
                let data = try await api.raw("GET", "/api/apple-devices/\(APIClient.seg(device.id))/raw")
                let obj = try JSONSerialization.jsonObject(with: data)
                let raw = (obj as? [String: Any])?["raw"] ?? obj
                let pretty = try JSONSerialization.data(withJSONObject: raw, options: [.prettyPrinted, .sortedKeys])
                let s = String(data: pretty, encoding: .utf8) ?? ""
                text = s == "{\n\n}" || s == "{}" ? "Noch keine Rohdaten – einmal „Orten“ ausführen (Online-Ortung muss verbunden sein)." :
                    "Von iCloud „Geräte suchen“ (IDs/Tokens ausgeblendet):\n\n" + s
            } catch { text = "Fehler: \(error.localizedDescription)" }
        }
    }
}

// MARK: - AirPods: Getrennt-Erkennung

struct SeparationView: View {
    let pairs: [SeparationPair]
    private let names = ["left": "Links", "right": "Rechts", "case": "Case"]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Zusammen oder getrennt?").font(.subheadline.bold()).padding(.top, 4)
            ForEach(pairs) { p in
                let (label, color): (String, Color) = switch p.state {
                case "separated": ("Getrennt", .red)
                case "maybe": ("Evtl. getrennt", .orange)
                case "together": ("Zusammen", .green)
                default: ("Unbekannt", .secondary)
                }
                HStack(spacing: 8) {
                    Text("\(names[p.a] ?? p.a) ↔ \(names[p.b] ?? p.b)").font(.subheadline)
                    Spacer()
                    if let d = p.distance, p.state != "unknown" {
                        Text(formatDistance(d)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                    }
                    Text(label).font(.caption.bold()).padding(.horizontal, 8).padding(.vertical, 3)
                        .background(color.opacity(0.18), in: .capsule).foregroundStyle(color)
                }
                if p.state == "separated", let since = p.since {
                    Text("Bestätigt durch \(p.streak) getrennte Ortungen seit \(Date(timeIntervalSince1970: since).shortDE)")
                        .font(.caption2).foregroundStyle(.secondary)
                } else if p.state == "maybe" {
                    Text("Eine getrennte Ortung – wird erst nach Bestätigung als getrennt gewertet.")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
    }
}
