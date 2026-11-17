import SwiftUI
import MapKit

// MARK: - Aufzeichnungen im Gerätedetail

struct RecordingsCard: View {
    @Environment(AppModel.self) private var model
    let device: AppleDevice
    @State private var showStart = false
    @State private var showAll = false

    private var list: [Recording] { model.recordings[device.id] ?? [] }

    var body: some View {
        GlassSection(title: "Standortverlauf", systemImage: "record.circle") {
            if let a = device.activeSession ?? list.first(where: \.active) {
                activeBanner(a)
            } else {
                Button {
                    Haptics.light()
                    showStart = true
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: "record.circle.fill").font(.title2).foregroundStyle(.red)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Aufzeichnung starten").font(.headline).foregroundStyle(.primary)
                            Text("Online, offline oder beides – auch über mehrere Tage")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.right").foregroundStyle(.tertiary)
                    }
                    .padding(12)
                    .background(Color.red.opacity(0.1), in: .rect(cornerRadius: 16))
                }
                .buttonStyle(PressableStyle())
            }
            let past = list.filter { !$0.active }
            if !past.isEmpty {
                Text("Frühere Aufzeichnungen").font(.footnote.bold()).foregroundStyle(.secondary).padding(.top, 4)
                ForEach(showAll ? past : Array(past.prefix(5))) { r in
                    Button { model.openRecording(r.id) } label: { RecordingRow(rec: r) }
                        .buttonStyle(.plain)
                }
                if past.count > 5 && !showAll {
                    Button("Alle \(past.count) anzeigen") { showAll = true }.buttonStyle(.glass)
                }
            }
            Text("Ohne laufende Aufzeichnung wird für Geräte kein Verlauf angezeigt. Offline-Berichte, die später gebündelt eintreffen (Batch/nachgereicht), werden automatisch in die passende Aufzeichnung einsortiert.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .task(id: device.id) { await model.loadRecordings(device.id) }
        .onChange(of: device.activeSession?.id) { _, _ in Task { await model.loadRecordings(device.id) } }
        .sheet(isPresented: $showStart) {
            NavigationStack { StartRecordingView(device: device) }
                .presentationDetents([.medium, .large])
        }
    }

    private func activeBanner(_ a: Recording) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Circle().fill(.red).frame(width: 10, height: 10)
                    .overlay(Circle().stroke(.red.opacity(0.4), lineWidth: 6))
                VStack(alignment: .leading, spacing: 1) {
                    Text(a.name).font(.headline)
                    TimelineView(.periodic(from: .now, by: 1)) { _ in
                        Text("läuft seit \(formatDuration(Date().timeIntervalSince1970 - a.startTs)) · \(a.sourceLabel)")
                            .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                Text("\(a.points ?? 0)").font(.title3.bold().monospacedDigit())
                Text("Punkte").font(.caption).foregroundStyle(.secondary)
            }
            if let e = a.endTs {
                Text("Endet automatisch \(Date(timeIntervalSince1970: e).shortDE)").font(.caption).foregroundStyle(.secondary)
            }
            HStack(spacing: 8) {
                Button { model.openRecording(a.id) } label: {
                    Label("Anzeigen", systemImage: "map").frame(maxWidth: .infinity)
                }
                .buttonStyle(.glassProminent)
                Button { Task { await stop(a) } } label: {
                    Label("Stoppen", systemImage: "stop.fill").frame(maxWidth: .infinity)
                }
                .buttonStyle(.glass).tint(.red)
                Menu {
                    ForEach([1, 6, 24, 72], id: \.self) { h in
                        Button("+\(h < 24 ? "\(h) h" : "\(h / 24) T")") { Task { await extend(a, h) } }
                    }
                } label: {
                    Image(systemName: "clock.badge.plus").frame(width: 36, height: 30)
                }
                .buttonStyle(.glass)
            }
        }
        .padding(12)
        .background(Color.red.opacity(0.08), in: .rect(cornerRadius: 16))
    }

    private func stop(_ a: Recording) async {
        let _: Recording? = try? await model.api?.send("POST", "/api/sessions/\(a.id)/stop")
        Haptics.success()
        model.showToast("Aufzeichnung beendet")
        await model.loadRecordings(device.id)
        await model.reloadAppleDevices()
    }

    private func extend(_ a: Recording, _ h: Int) async {
        let _: Recording? = try? await model.api?.send("PATCH", "/api/sessions/\(a.id)", json: ["extend_hours": h])
        Haptics.success()
        await model.loadRecordings(device.id)
        await model.reloadAppleDevices()
    }
}

struct RecordingRow: View {
    let rec: Recording
    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: rec.active ? "record.circle.fill" : "point.topleft.down.to.point.bottomright.curvepath")
                .foregroundStyle(rec.active ? .red : .blue)
                .frame(width: 32, height: 32)
                .background(Color(.tertiarySystemFill), in: .circle)
            VStack(alignment: .leading, spacing: 2) {
                Text(rec.name).font(.subheadline.weight(.semibold)).lineLimit(1)
                Text("\(rec.start.shortDE) · \(formatDuration((rec.effectiveEnd ?? Date().timeIntervalSince1970) - rec.startTs)) · \(rec.sourceLabel)")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            Text("\(rec.points ?? 0)").font(.subheadline.monospacedDigit()).foregroundStyle(.secondary)
            Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
    }
}

// MARK: - Aufzeichnung starten

struct StartRecordingView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let device: AppleDevice
    @State private var name = ""
    @State private var source = "both"
    @State private var duration: Double = 0   // Stunden, 0 = unbegrenzt, -1 = bis Datum
    @State private var until = Date().addingTimeInterval(86400)
    @State private var busy = false

    private var hasOffline: Bool { !device.parts.isEmpty }
    private var hasOnline: Bool { device.isCloud }

    var body: some View {
        Form {
            Section {
                TextField("Name (optional, z. B. Stadtrundgang)", text: $name)
            }
            Section {
                Picker("Quelle", selection: $source) {
                    Text("Beides").tag("both")
                    Text("Nur offline").tag("offline")
                    Text("Nur online").tag("online")
                }
                .pickerStyle(.segmented)
                if source != "online" && !hasOffline {
                    Label("Keine Offline-Schlüsseldatei hinterlegt – es kommen nur Online-Punkte.", systemImage: "exclamationmark.triangle")
                        .font(.caption).foregroundStyle(.orange)
                }
                if source != "offline" && !hasOnline {
                    Label("Gerät ist nicht mit iCloud verbunden – es kommen nur Offline-Punkte.", systemImage: "exclamationmark.triangle")
                        .font(.caption).foregroundStyle(.orange)
                }
            } header: {
                Text("Datenquelle")
            } footer: {
                Text("Online = iCloud „Geräte suchen“ (GPS/WLAN, nur wenn das Gerät online ist). Offline = Wo-ist-Netzwerk über die Schlüsseldatei (funktioniert auch bei ausgeschaltetem/offline Gerät, Berichte kommen teils gebündelt später).")
            }
            Section("Dauer") {
                Picker("Dauer", selection: $duration) {
                    Text("Unbegrenzt").tag(0.0)
                    Text("1 Stunde").tag(1.0)
                    Text("3 Stunden").tag(3.0)
                    Text("6 Stunden").tag(6.0)
                    Text("12 Stunden").tag(12.0)
                    Text("1 Tag").tag(24.0)
                    Text("3 Tage").tag(72.0)
                    Text("7 Tage").tag(168.0)
                    Text("Bis Datum …").tag(-1.0)
                }
                if duration == -1 {
                    DatePicker("Ende", selection: $until, in: Date()..., displayedComponents: [.date, .hourAndMinute])
                }
            }
        }
        .navigationTitle("Aufzeichnung starten")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Starten") { Task { await start() } }.disabled(busy)
            }
        }
    }

    private func start() async {
        guard let api = model.api else { return }
        busy = true
        defer { busy = false }
        var body: [String: Any] = ["source": source]
        if !name.isEmpty { body["name"] = name }
        if duration > 0 { body["duration_hours"] = duration }
        if duration == -1 { body["end_ts"] = until.timeIntervalSince1970 }
        do {
            let r: Recording = try await api.send("POST", "/api/apple-devices/\(APIClient.seg(device.id))/sessions", json: body)
            Haptics.success()
            model.showToast("Aufzeichnung läuft")
            await model.loadRecordings(device.id)
            await model.reloadAppleDevices()
            dismiss()
            model.openRecording(r.id)
        } catch {
            Haptics.warning()
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }
}

// MARK: - AirPods: Case-Status

struct CaseStatusCard: View {
    @Environment(AppModel.self) private var model
    let device: AppleDevice
    @State private var cfg: CaseConfig?
    @State private var saving = false

    var body: some View {
        GlassSection(title: "Case-Status", systemImage: "airpods.chargingcase.fill") {
            if let cs = device.caseStatus {
                HStack {
                    Text(cs.summary).font(.title3.bold())
                        .foregroundStyle(cs.summary == "Im Case" ? Color.green : cs.summary == "Unbekannt" ? Color.secondary : Color.orange)
                    Spacer()
                    Text("geschätzt").font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Color(.tertiarySystemFill), in: .capsule)
                }
                bud("Linker AirPod", "airpod.left", cs.left, part: device.part(.left))
                bud("Rechter AirPod", "airpod.right", cs.right, part: device.part(.right))
                if let c = device.part(.case) {
                    HStack(spacing: 10) {
                        Image(systemName: "airpods.chargingcase.fill").frame(width: 28)
                        Text("Ladecase").font(.subheadline)
                        Spacer()
                        if let l = c.last { AgeText(date: l.date).font(.caption) }
                        if c.battery != nil { BatteryView(level: c.battery).font(.caption) }
                    }
                }
            } else {
                Text("Importiere die Schlüsseldateien für links, rechts und Case, damit der Status geschätzt werden kann.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            Text("Ohrhörer senden eigene Wo-ist-Signale vor allem, wenn sie außerhalb des Case sind. Wird ein Ohrhörer frisch offline geortet ⇒ „draußen“. Meldet sich danach nur noch das Case ⇒ „im Case“.")
                .font(.caption).foregroundStyle(.secondary)

            if let c = cfg {
                Divider()
                Text("Benachrichtigungen").font(.subheadline.bold())
                Toggle("Aus dem Case genommen", isOn: bind(\.alertOut.enabled))
                if c.alertOut.enabled { LevelPicker(title: "Stufe", level: bind(\.alertOut.level)) }
                Toggle("Wieder ins Case gelegt", isOn: bind(\.alertIn.enabled))
                if c.alertIn.enabled { LevelPicker(title: "Stufe", level: bind(\.alertIn.level)) }
                Toggle("Nur einmalig benachrichtigen", isOn: bind(\.once))
                Stepper("„Draußen“ wenn geortet in den letzten \(Int(c.windowMin)) min", value: bind(\.windowMin), in: 5...180, step: 5)
                    .font(.subheadline)
                HStack {
                    Button(saving ? "Sichere …" : "Sichern") { Task { await save(rearm: false) } }
                        .buttonStyle(.glassProminent).disabled(saving || c == device.settings?.caseConfig)
                    if c.once {
                        Button("Neu scharf schalten") { Task { await save(rearm: true) } }.buttonStyle(.glass)
                    }
                }
            }
        }
        .onAppear { if cfg == nil { cfg = device.settings?.caseConfig } }
        .onChange(of: device.settings?.caseConfig) { old, new in if cfg == old { cfg = new } }
    }

    private func bind<T>(_ kp: WritableKeyPath<CaseConfig, T>) -> Binding<T> {
        Binding(get: { cfg![keyPath: kp] }, set: { cfg![keyPath: kp] = $0; Haptics.selection() })
    }

    private func bud(_ title: String, _ icon: String, _ s: BudState?, part: AppleDevicePart?) -> some View {
        let state = s?.state ?? "no_key"
        let (label, color): (String, Color) = switch state {
        case "out": ("Draußen", .orange)
        case "in_case": ("Im Case", .green)
        case "no_key": ("Keine Datei", .secondary)
        default: ("Unbekannt", .secondary)
        }
        return HStack(spacing: 10) {
            Image(systemName: icon).frame(width: 28)
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.subheadline)
                if let r = s?.reason { Text(r).font(.caption2).foregroundStyle(.secondary).lineLimit(2) }
            }
            Spacer()
            if part?.battery != nil { BatteryView(level: part?.battery).font(.caption) }
            Text(label).font(.caption.bold()).padding(.horizontal, 8).padding(.vertical, 3)
                .background(color.opacity(0.18), in: .capsule).foregroundStyle(color)
        }
    }

    private func save(rearm: Bool) async {
        guard let c = cfg, let api = model.api else { return }
        saving = true
        defer { saving = false }
        let body: [String: Any] = [
            "settings": ["case": ["window_min": c.windowMin, "once": c.once,
                                  "alert_out": ["enabled": c.alertOut.enabled, "level": c.alertOut.level],
                                  "alert_in": ["enabled": c.alertIn.enabled, "level": c.alertIn.level]]],
            "rearm": rearm]
        do {
            let _: AppleDevice = try await api.send("PATCH", "/api/apple-devices/\(APIClient.seg(device.id))", json: body)
            await model.reloadAppleDevices()
            Haptics.success()
            model.showToast(rearm ? "Benachrichtigungen wieder scharf" : "Gesichert")
        } catch {
            Haptics.warning()
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }
}

// MARK: - Datenquellen

struct DataSourcesCard: View {
    let device: AppleDevice
    var body: some View {
        GlassSection(title: "Datenquellen", systemImage: "antenna.radiowaves.left.and.right") {
            source(icon: "icloud.fill", color: .green, title: "Online · iCloud „Geräte suchen“",
                   text: device.isCloud
                   ? "Standort direkt vom Gerät (GPS/WLAN/Mobilfunk), Akku in %. Nur solange das Gerät online ist. \(device.onlinePoints ?? 0) Online-Punkte gespeichert."
                   : "Nicht verbunden – Gerät ist manuell angelegt.")
            source(icon: "antenna.radiowaves.left.and.right", color: .gray, title: "Offline · Wo-ist-Netzwerk (FindMy.py)",
                   text: device.parts.isEmpty
                   ? "Keine Schlüsseldatei hinterlegt."
                   : "Verschlüsselte Berichte fremder Apple-Geräte in der Nähe, lokal entschlüsselt. Funktioniert auch offline/ausgeschaltet. Genauigkeit meist 5–100 m, Berichte teils gebündelt (Batch) oder nachgereicht; Akku grob aus dem Statusbyte. "
                     + device.parts.map { "\(PartRole(rawValue: $0.role)?.short ?? $0.role): \($0.total)" }.joined(separator: " · "))
        }
    }

    private func source(icon: String, color: Color, title: String, text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon).foregroundStyle(.white).frame(width: 30, height: 30).background(color.gradient, in: .circle)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.weight(.semibold))
                Text(text).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

// MARK: - Aufzeichnung ansehen (Timeline auf der Karte)

struct RecordingDetailView: View {
    let recordingID: Int
    @Environment(AppModel.self) private var model
    @State private var playing = false
    @State private var cursorAddress: String?
    @State private var confirmDelete = false
    @State private var gpxURL: URL?
    @State private var showAllRows = false

    private var rec: Recording? { model.recording }
    private var device: AppleDevice? { rec.flatMap { model.appleDevice($0.appleId) } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                if let r = rec { controls(r) }
                timeline
                StaysCard()
                if let p = model.cursorReport { pointCard(p) }
                pointList
            }
            .padding(.horizontal, 16).padding(.top, 16).padding(.bottom, 40)
        }
        .toolbar(.hidden, for: .navigationBar)
        .task(id: recordingID) { await model.loadRecording(recordingID, fit: true) }
        .onDisappear {
            if model.focusedRecordingID == recordingID { model.leaveRecording() }
        }
        .refreshable {
            if let aid = rec?.appleId { await model.refreshApple(aid) }
            await model.loadRecording(recordingID, fit: false)
        }
        .task(id: model.cursorReport?.id) {
            cursorAddress = nil
            guard let r = model.cursorReport else { return }
            try? await Task.sleep(for: .milliseconds(300))
            if !Task.isCancelled { cursorAddress = await model.address(for: r) }
        }
        .task(id: playing) {
            guard playing else { return }
            if (model.cursor ?? 0) >= model.track.count - 1 { model.cursor = 0 }
            while playing && !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(450))
                let c = model.cursor ?? 0
                if c >= model.track.count - 1 { playing = false; Haptics.success(); break }
                model.cursor = c + 1
                Haptics.selection()
            }
        }
        .onChange(of: model.track) { _, _ in writeGPX() }
        .confirmationDialog("Aufzeichnung löschen?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Löschen", role: .destructive) {
                Task {
                    let _: OKResult? = try? await model.api?.send("DELETE", "/api/sessions/\(recordingID)")
                    if let aid = rec?.appleId { await model.loadRecordings(aid) }
                    Haptics.success()
                    if !model.sheetPath.isEmpty { model.sheetPath.removeLast() }
                }
            }
        } message: {
            Text("Nur die Aufzeichnung wird gelöscht – die gesammelten Standorte bleiben gemäß Aufbewahrung erhalten.")
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    if rec?.active == true {
                        Text("LIVE").font(.caption2.weight(.heavy)).padding(.horizontal, 6).padding(.vertical, 2)
                            .background(.red, in: .capsule).foregroundStyle(.white)
                    }
                    Text(rec?.name ?? "Aufzeichnung").font(.title2.bold()).lineLimit(2)
                }
                if let r = rec {
                    Text("\(device?.name ?? "") · \(r.sourceLabel)").foregroundStyle(.secondary)
                    Text("\(r.start.shortDE) – \(r.effectiveEnd.map { Date(timeIntervalSince1970: $0).shortDE } ?? "jetzt")")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
            }
            Spacer()
            Button {
                Haptics.light()
                if !model.sheetPath.isEmpty { model.sheetPath.removeLast() }
            } label: {
                Image(systemName: "chevron.backward").font(.body.weight(.semibold)).frame(width: 40, height: 40)
            }
            .buttonStyle(.plain)
            .glassEffect(.regular.interactive(), in: .circle)
        }
    }

    private func controls(_ r: Recording) -> some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                stat("\(model.track.count)", "Punkte")
                stat("\(model.track.filter(\.isOnline).count)", "Online", .green)
                stat("\(model.track.filter { !$0.isOnline }.count)", "Offline", .gray)
                stat(formatDuration((r.effectiveEnd ?? Date().timeIntervalSince1970) - r.startTs), "Dauer")
            }
            Picker("Quelle", selection: Binding(get: { r.source }, set: { v in Task { await patch(["source": v]) } })) {
                Text("Beides").tag("both")
                Text("Offline").tag("offline")
                Text("Online").tag("online")
            }
            .pickerStyle(.segmented)
            HStack(spacing: 8) {
                if r.active {
                    Button { Task { await stop() } } label: { Label("Stoppen", systemImage: "stop.fill").frame(maxWidth: .infinity) }
                        .buttonStyle(.glass).tint(.red)
                    Menu {
                        ForEach([1, 6, 24, 72], id: \.self) { h in
                            Button("+\(h < 24 ? "\(h) h" : "\(h / 24) T")") { Task { await patch(["extend_hours": h]) } }
                        }
                    } label: { Label("Verlängern", systemImage: "clock.badge.plus").frame(maxWidth: .infinity) }
                    .buttonStyle(.glass)
                } else {
                    Button { Task { await patch(["resume": true, "end_ts": NSNull()]) } } label: {
                        Label("Fortsetzen", systemImage: "play.fill").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.glass)
                }
                if let gpxURL {
                    ShareLink(item: gpxURL) { Image(systemName: "square.and.arrow.up").frame(width: 36, height: 30) }
                        .buttonStyle(.glass)
                }
                Button(role: .destructive) { confirmDelete = true } label: { Image(systemName: "trash").frame(width: 36, height: 30) }
                    .buttonStyle(.glass)
            }
        }
    }

    private func stat(_ v: String, _ l: String, _ c: Color = .primary) -> some View {
        VStack(spacing: 2) {
            Text(v).font(.headline.monospacedDigit()).foregroundStyle(c).lineLimit(1).minimumScaleFactor(0.6)
            Text(l).font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 8)
        .background(Color(.secondarySystemGroupedBackground).opacity(0.7), in: .rect(cornerRadius: 14))
    }

    private var timeline: some View {
        @Bindable var model = model
        let count = model.track.count
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Timeline", systemImage: "clock.arrow.circlepath").font(.headline)
                Spacer()
                HStack(spacing: 8) {
                    Circle().fill(.green).frame(width: 8, height: 8); Text("Online").font(.caption)
                    Circle().fill(.blue).frame(width: 8, height: 8); Text("Offline").font(.caption)
                }
                .foregroundStyle(.secondary)
            }
            if count > 1 {
                strip.frame(height: 22)
                HStack(spacing: 14) {
                    Button { step(-1) } label: { Image(systemName: "backward.fill") }
                    Button { Haptics.light(); playing.toggle() } label: {
                        Image(systemName: playing ? "pause.fill" : "play.fill").font(.title3)
                            .frame(width: 44, height: 44).background(Color.blue, in: .circle).foregroundStyle(.white)
                    }
                    Button { step(1) } label: { Image(systemName: "forward.fill") }
                    Slider(value: Binding(get: { Double(model.cursor ?? count - 1) },
                                          set: { v in let i = Int(v.rounded()); if i != model.cursor { model.cursor = i; Haptics.selection() } }),
                           in: 0...Double(count - 1), step: 1)
                }
                .buttonStyle(.plain).font(.body.weight(.semibold))
            } else {
                Text(count == 0 ? "Noch keine Punkte – sie erscheinen live, sobald Ortungen eintreffen." : "Ein Punkt bisher.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            HStack {
                Text("Genauigkeitskreise").font(.subheadline)
                Spacer()
                Picker("Kreise", selection: $model.circleMode) {
                    ForEach(CircleMode.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented).frame(width: 200)
            }
            Toggle("Karte folgt dem Punkt", isOn: $model.followCursor).font(.subheadline)
        }
        .padding(16)
        .background(Color(.secondarySystemGroupedBackground).opacity(0.7), in: .rect(cornerRadius: 22))
    }

    private var strip: some View {
        let t = model.track
        let first = t.first?.ts ?? 0
        let span = max((t.last?.ts ?? 1) - first, 1)
        let cur = model.cursorReport?.ts
        return GeometryReader { geo in
            Canvas { ctx, size in
                ctx.fill(Path(roundedRect: CGRect(x: 0, y: size.height / 2 - 1, width: size.width, height: 2), cornerRadius: 1),
                         with: .color(.secondary.opacity(0.25)))
                for r in t {
                    let x = (r.ts - first) / span * size.width
                    let y: CGFloat = r.isOnline ? 2 : size.height / 2
                    ctx.fill(Path(roundedRect: CGRect(x: x - 1, y: y, width: 2.5, height: size.height / 2 - 2), cornerRadius: 1),
                             with: .color(r.isOnline ? Color.green : Color.blue))
                }
                if let cur {
                    let x = (cur - first) / span * size.width
                    ctx.fill(Path(roundedRect: CGRect(x: x - 3, y: 0, width: 6, height: size.height), cornerRadius: 3), with: .color(.primary))
                }
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { v in
                let target = first + Double(min(max(v.location.x / geo.size.width, 0), 1)) * span
                if let i = t.firstIndex(where: { $0.ts >= target }), i != model.cursor { model.cursor = i; Haptics.selection() }
            })
        }
    }

    private func step(_ d: Int) {
        guard !model.track.isEmpty else { return }
        model.cursor = min(max((model.cursor ?? model.track.count - 1) + d, 0), model.track.count - 1)
        Haptics.selection()
    }

    private func pointCard(_ r: Report) -> some View {
        GlassSection(title: "Ausgewählter Punkt", systemImage: "mappin.circle.fill") {
            if let cursorAddress { Text(cursorAddress).font(.body.weight(.medium)) }
            HStack(spacing: 6) {
                sourceBadge(r)
                if r.isBatch { badge("BATCH ×\(r.batchSize ?? 1)", .purple) }
                if r.isLate { badge("NACHGEREICHT", .orange) }
            }
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                row("Geortet", "\(r.date.shortDE) (\(findMyTime(r.date).text))")
                row("Empfangen", "\(r.receivedDate.timeDE) · +\(r.delayMinutes) min")
                row("Genauigkeit", "±\(r.accuracy ?? 0) m")
                if let p = r.positionType { row("Ortungsart", positionLabel(p)) }
                if let role = r.role.flatMap(PartRole.init(rawValue:)), role != .main { row("Teil", role.label) }
                if let b = r.batteryLevel { row("Akku", "\(Int(b * 100)) %") }
                else if let b = r.battery { row("Akku (geschätzt)", BatteryLevel.label(b)) }
                row("Herkunft", r.isOnline ? "iCloud „Geräte suchen“" : "Wo-ist-Netzwerk via FindMy.py")
                row("Koordinaten", String(format: "%.6f, %.6f", r.lat, r.lon))
            }
            .font(.subheadline)
        }
    }

    private var pointList: some View {
        let rows = Array(model.track.enumerated().reversed())
        let shown = showAllRows ? rows : Array(rows.prefix(150))
        let groups = Dictionary(grouping: shown) { Calendar.current.startOfDay(for: $0.element.date) }
        return GlassSection(title: "Alle Punkte", systemImage: "list.bullet") {
            ForEach(groups.keys.sorted(by: >), id: \.self) { day in
                Text(day.formatted(.dateTime.weekday(.wide).day().month(.wide).locale(Locale(identifier: "de_DE"))))
                    .font(.footnote.bold()).foregroundStyle(.secondary).padding(.top, 6)
                ForEach(groups[day] ?? [], id: \.element.id) { i, r in
                    Button { model.cursor = i; Haptics.selection() } label: {
                        HStack(spacing: 10) {
                            Circle().fill(r.isOnline ? Color.green : Color.blue)
                                .frame(width: model.cursor == i ? 14 : 10, height: model.cursor == i ? 14 : 10)
                            Text(r.date.timeDE).font(.subheadline.monospacedDigit())
                            Text("±\(r.accuracy ?? 0) m").font(.caption).foregroundStyle(.secondary)
                            if let role = r.role.flatMap(PartRole.init(rawValue:)), role != .main { badge(role.short, .teal) }
                            if r.isBatch { badge("×\(r.batchSize ?? 1)", .purple) }
                            if r.isLate { badge("spät", .orange) }
                            Spacer()
                            Text(r.isOnline ? (r.positionType.map(positionLabel) ?? "Online") : "+\(r.delayMinutes) min")
                                .font(.caption2).foregroundStyle(.tertiary)
                        }
                        .padding(.vertical, 3).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            if !showAllRows && rows.count > 150 {
                Button("Alle \(rows.count) Punkte anzeigen") { showAllRows = true }.buttonStyle(.glass)
            }
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

    private func sourceBadge(_ r: Report) -> some View {
        badge(r.isOnline ? "ONLINE" : "OFFLINE", r.isOnline ? .green : .blue)
    }

    private func badge(_ s: String, _ c: Color) -> some View {
        Text(s).font(.system(size: 9, weight: .heavy)).padding(.horizontal, 5).padding(.vertical, 2)
            .background(c.opacity(0.85), in: .capsule).foregroundStyle(.white)
    }

    private func row(_ k: String, _ v: String) -> some View {
        GridRow { Text(k).foregroundStyle(.secondary); Text(v) }
    }

    private func patch(_ body: [String: Any]) async {
        let _: Recording? = try? await model.api?.send("PATCH", "/api/sessions/\(recordingID)", json: body)
        Haptics.success()
        await model.loadRecording(recordingID, fit: false)
        if let aid = rec?.appleId { await model.loadRecordings(aid) }
        await model.reloadAppleDevices()
    }

    private func stop() async {
        let _: Recording? = try? await model.api?.send("POST", "/api/sessions/\(recordingID)/stop")
        Haptics.success()
        model.showToast("Aufzeichnung beendet")
        await model.loadRecording(recordingID, fit: false)
        if let aid = rec?.appleId { await model.loadRecordings(aid) }
        await model.reloadAppleDevices()
    }

    private func writeGPX() {
        let reports = model.track
        guard !reports.isEmpty else { gpxURL = nil; return }
        let iso = ISO8601DateFormatter()
        var s = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<gpx version=\"1.1\" creator=\"FindMy Ultra\" xmlns=\"http://www.topografix.com/GPX/1/1\">\n<trk><name>\((rec?.name ?? "Aufzeichnung").replacingOccurrences(of: "<", with: ""))</name><trkseg>\n"
        for r in reports {
            s += "<trkpt lat=\"\(r.lat)\" lon=\"\(r.lon)\"><time>\(iso.string(from: r.date))</time><hdop>\(r.accuracy ?? 0)</hdop><src>\(r.source ?? "offline")</src></trkpt>\n"
        }
        s += "</trkseg></trk></gpx>\n"
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("aufzeichnung-\(recordingID).gpx")
        try? s.write(to: url, atomically: true, encoding: .utf8)
        gpxURL = url
    }
}
