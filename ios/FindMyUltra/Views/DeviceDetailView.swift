import SwiftUI
import MapKit

/// Objekt-Karte im Sheet (wie in „Wo ist?“). Die Hauptkarte zeigt dazu Spur, Punkte & Genauigkeitskreise.
struct DeviceDetailView: View {
    let deviceID: String
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL

    @State private var playing = false
    @State private var address: String?
    @State private var cursorAddress: String?
    @State private var sheet: SheetKind?
    @State private var confirmDelete = false
    @State private var showAllRows = false
    @State private var gpxURL: URL?

    enum SheetKind: String, Identifiable { case lost, alerts, edit; var id: String { rawValue } }

    private var device: Device? { model.device(deviceID) }

    var body: some View {
        Group {
            if let d = device {
                content(d)
            } else {
                ContentUnavailableView("Objekt nicht gefunden", systemImage: "questionmark.circle")
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .task(id: deviceID) { await model.focus(deviceID) }
        .onChange(of: model.historyRange) { _, _ in
            Task {
                await model.reloadTrack(deviceID, keepCursor: false)
                model.fitTrack()
            }
        }
        .task(id: device?.last?.id) {
            if let r = device?.last { address = await model.address(for: r) }
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
        .sheet(item: $sheet) { s in
            if let d = device {
                NavigationStack {
                    switch s {
                    case .lost: LostModeView(device: d)
                    case .alerts: AlertSettingsView(device: d)
                    case .edit: EditDeviceView(device: d)
                    }
                }
                .presentationDetents([.large])
            }
        }
        .confirmationDialog("Objekt entfernen?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Entfernen (inkl. Verlauf)", role: .destructive) {
                Task {
                    try? await model.deleteDevice(deviceID)
                    Haptics.success()
                    model.sheetPath = []
                }
            }
        } message: {
            Text("Die Schlüssel werden vom Server gelöscht. Du kannst sie jederzeit erneut importieren.")
        }
    }

    // MARK: Inhalt

    private func content(_ d: Device) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header(d)
                if d.lost.enabled { lostBanner(d) }
                actions(d)
                historyCard(d)
                if let r = model.cursorReport { pointCard(r, d) }
                infoCard(d)
                pointList(d)
                Button(role: .destructive) { confirmDelete = true } label: {
                    Label("Objekt entfernen", systemImage: "trash").frame(maxWidth: .infinity)
                }
                .buttonStyle(.glass)
                .tint(.red)
                .padding(.top, 4)
            }
            .padding(.horizontal, 16)
            .padding(.top, 16)
            .padding(.bottom, 40)
        }
        .refreshable { await model.refresh(deviceID: d.id) }
    }

    private func header(_ d: Device) -> some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(d.name).font(.title.bold()).lineLimit(2)
                if let r = d.last {
                    Text(address ?? String(format: "%.5f, %.5f", r.lat, r.lon))
                        .font(.body).foregroundStyle(.secondary).lineLimit(1)
                    HStack(spacing: 6) {
                        AgeText(date: r.date).fontWeight(.medium)
                        Text("·").foregroundStyle(.secondary)
                        Text("±\(r.accuracy ?? 0) m").foregroundStyle(.secondary)
                        if d.battery != nil {
                            Text("·").foregroundStyle(.secondary)
                            BatteryView(level: d.battery)
                        }
                    }
                    .font(.subheadline)
                } else {
                    Text("Noch kein Standort gefunden").foregroundStyle(.secondary)
                }
            }
            Spacer()
            Menu {
                Button { sheet = .edit } label: { Label("Bearbeiten", systemImage: "pencil") }
                Button { sheet = .alerts } label: { Label("Alarme", systemImage: "bell.badge") }
                Button {
                    Task { await model.refresh(deviceID: deviceID, full: true) }
                } label: { Label("7-Tage-Scan", systemImage: "clock.arrow.2.circlepath") }
                Button {
                    Haptics.light()
                    Task { try? await model.patchDevice(deviceID, ["enabled": !d.enabled]) }
                } label: { Label(d.enabled ? "Abruf pausieren" : "Abruf fortsetzen", systemImage: d.enabled ? "pause.circle" : "play.circle") }
                if let gpxURL {
                    ShareLink(item: gpxURL) { Label("Verlauf exportieren (GPX)", systemImage: "square.and.arrow.up") }
                }
            } label: {
                Image(systemName: "ellipsis").font(.body.weight(.semibold)).frame(width: 40, height: 40)
            }
            .glassEffect(.regular.interactive(), in: .circle)
            Button {
                Haptics.light()
                model.sheetPath = []
            } label: {
                Image(systemName: "xmark").font(.body.weight(.semibold)).frame(width: 40, height: 40)
            }
            .buttonStyle(.plain)
            .glassEffect(.regular.interactive(), in: .circle)
        }
    }

    private func lostBanner(_ d: Device) -> some View {
        Button { sheet = .lost } label: {
            HStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle.fill").font(.title2).foregroundStyle(.white)
                    .symbolEffect(.pulse)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Als verloren markiert").font(.headline).foregroundStyle(.white)
                    Text(d.lost.since.map { "Seit \(Date(timeIntervalSince1970: $0).shortDE) · Abruf alle \(model.settings?.lostPollInterval ?? 20) s" } ?? "")
                        .font(.subheadline).foregroundStyle(.white.opacity(0.85))
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(.white.opacity(0.7))
            }
            .padding(16)
            .background(.red.gradient, in: .rect(cornerRadius: 22))
        }
        .buttonStyle(PressableStyle())
    }

    // MARK: Aktionen

    private func actions(_ d: Device) -> some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
            Button {
                Task { await model.refresh(deviceID: d.id) }
            } label: {
                ActionTile(title: model.isRefreshing ? "Suche …" : "Orten",
                           subtitle: model.thoroughRefresh ? "Gründlich (7 Tage)" : "Schnell", icon: "location.magnifyingglass", color: .blue)
            }
            .disabled(model.isRefreshing)
            Button {
                Haptics.light()
                if let r = d.last, let u = appleMapsURL(r, name: d.name, directions: true) { openURL(u) }
            } label: {
                ActionTile(title: "Route", subtitle: d.last.flatMap { model.distanceFromUser($0) } ?? "Apple Karten",
                           icon: "arrow.triangle.turn.up.right.diamond.fill", color: .blue)
            }
            .disabled(d.last == nil)
            Button { Haptics.light(); sheet = .lost } label: {
                ActionTile(title: "Verloren", subtitle: d.lost.enabled ? "Aktiviert" : "Aus",
                           icon: "exclamationmark.triangle.fill", color: .red, active: d.lost.enabled)
            }
            Button { Task { await toggleGuard(d) } } label: {
                ActionTile(title: "Wache", subtitle: d.isGuarded ? "Aktiv · \(formatDistance(d.alerts.guardMode.radiusM))" : "Aus",
                           icon: "lock.shield.fill", color: .orange, active: d.isGuarded)
            }
            Button { Haptics.light(); sheet = .alerts } label: {
                ActionTile(title: "Mitteilungen", subtitle: alertSummary(d), icon: "bell.badge.fill", color: .purple)
            }
            Button { Haptics.light(); sheet = .edit } label: {
                ActionTile(title: "Bearbeiten", subtitle: "Name, Emoji, Verlauf", icon: "pencil", color: .gray)
            }
        }
        .buttonStyle(PressableStyle())
    }

    private func alertSummary(_ d: Device) -> String {
        let a = d.alerts
        let n = [a.movement.enabled, a.zones.enabled, a.newReport.enabled, a.offline.enabled, a.battery.enabled]
            .filter { $0 }.count + (a.guardMode.enabled ? 1 : 0)
        return n == 0 ? "Keine aktiv" : "\(n) aktiv"
    }

    // MARK: Verlauf

    private func historyCard(_ d: Device) -> some View {
        @Bindable var model = model
        let count = model.track.count
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Standortverlauf", systemImage: "clock.arrow.circlepath").font(.headline)
                Spacer()
                Text("\(count) Punkte").font(.subheadline).foregroundStyle(.secondary)
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(HistoryRange.allCases) { r in
                        Button {
                            Haptics.selection()
                            model.historyRange = r
                        } label: {
                            Text(r.label)
                                .font(.subheadline.weight(.semibold))
                                .padding(.horizontal, 14).padding(.vertical, 7)
                                .background(model.historyRange == r ? d.tint : Color(.tertiarySystemFill), in: .capsule)
                                .foregroundStyle(model.historyRange == r ? Color.white : Color.primary)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            if count > 1 {
                densityStrip(d).frame(height: 22)
                HStack(spacing: 14) {
                    Button { step(-1) } label: { Image(systemName: "backward.fill") }
                        .disabled((model.cursor ?? 0) <= 0)
                    Button {
                        Haptics.light()
                        playing.toggle()
                    } label: {
                        Image(systemName: playing ? "pause.fill" : "play.fill")
                            .font(.title3).frame(width: 44, height: 44)
                            .background(d.tint, in: .circle).foregroundStyle(.white)
                    }
                    Button { step(1) } label: { Image(systemName: "forward.fill") }
                        .disabled((model.cursor ?? 0) >= count - 1)
                    Slider(value: Binding(
                        get: { Double(model.cursor ?? count - 1) },
                        set: { v in
                            let i = Int(v.rounded())
                            if i != model.cursor { model.cursor = i; Haptics.selection() }
                        }), in: 0...Double(count - 1), step: 1)
                        .tint(d.tint)
                }
                .buttonStyle(.plain)
                .font(.body.weight(.semibold))
                if let r = model.cursorReport {
                    HStack(spacing: 6) {
                        Text(r.date.shortDE).font(.subheadline.monospacedDigit().bold())
                        Text("±\(r.accuracy ?? 0) m").font(.subheadline).foregroundStyle(.secondary)
                        if r.isBatch { badge("BATCH ×\(r.batchSize ?? 1)", .purple) }
                        if r.isLate { badge("NACHGEREICHT", .orange) }
                        Spacer()
                        Text("\((model.cursor ?? 0) + 1)/\(count)").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                    }
                }
            } else if count == 0 {
                Text("Keine Standorte in diesem Zeitraum.").font(.subheadline).foregroundStyle(.secondary)
            }
            HStack {
                Text("Genauigkeitskreise").font(.subheadline)
                Spacer()
                Picker("Kreise", selection: $model.circleMode) {
                    ForEach(CircleMode.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                .frame(width: 200)
                .onChange(of: model.circleMode) { _, _ in Haptics.selection() }
            }
            Toggle("Karte folgt dem Punkt", isOn: $model.followCursor)
                .font(.subheadline)
                .onChange(of: model.followCursor) { _, _ in Haptics.light() }
        }
        .padding(16)
        .background(Color(.secondarySystemGroupedBackground).opacity(0.7), in: .rect(cornerRadius: 22))
    }

    private func densityStrip(_ d: Device) -> some View {
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
                    ctx.fill(Path(roundedRect: CGRect(x: x - 1, y: 4, width: 2.5, height: size.height - 8), cornerRadius: 1),
                             with: .color(d.tint.opacity(0.6)))
                }
                if let cur {
                    let x = (cur - first) / span * size.width
                    ctx.fill(Path(roundedRect: CGRect(x: x - 3, y: 0, width: 6, height: size.height), cornerRadius: 3),
                             with: .color(.primary))
                }
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { v in
                let target = first + Double(min(max(v.location.x / geo.size.width, 0), 1)) * span
                if let i = t.firstIndex(where: { $0.ts >= target }), i != model.cursor {
                    model.cursor = i
                    Haptics.selection()
                }
            })
        }
    }

    private func step(_ delta: Int) {
        guard !model.track.isEmpty else { return }
        let c = (model.cursor ?? model.track.count - 1) + delta
        model.cursor = min(max(c, 0), model.track.count - 1)
        Haptics.selection()
    }

    private func pointCard(_ r: Report, _ d: Device) -> some View {
        GlassSection(title: "Ausgewählter Standort", systemImage: "mappin.circle.fill") {
            if let cursorAddress { Text(cursorAddress).font(.body.weight(.medium)) }
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                row("Geortet", "\(r.date.shortDE) (\(findMyTime(r.date).text))")
                row("Empfangen", "\(r.receivedDate.timeDE) · +\(r.delayMinutes) min")
                row("Genauigkeit", "±\(r.accuracy ?? 0) m")
                row("Koordinaten", String(format: "%.6f, %.6f", r.lat, r.lon))
                if r.isBatch { row("Batch", "\(r.batchSize ?? 1) Berichte gleichzeitig") }
                if r.isLate { row("Hinweis", "nachgereicht") }
                if let b = r.battery { row("Batterie", BatteryLevel.label(b)) }
            }
            .font(.subheadline)
            HStack {
                Button("In Karten öffnen") { Haptics.light(); if let u = appleMapsURL(r, name: d.name) { openURL(u) } }
                    .buttonStyle(.glass)
                Button {
                    UIPasteboard.general.string = String(format: "%.6f, %.6f", r.lat, r.lon)
                    Haptics.success()
                    model.showToast("Koordinaten kopiert")
                } label: { Image(systemName: "doc.on.doc") }
                .buttonStyle(.glass)
            }
        }
    }

    private func infoCard(_ d: Device) -> some View {
        GlassSection(title: "Details", systemImage: "info.circle.fill") {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                row("Standorte gesamt", "\(d.total)")
                if let f = d.firstTs { row("Verlauf seit", Date(timeIntervalSince1970: f).shortDE) }
                row("Aufbewahrung", d.retentionDays.map { $0 == 0 ? "unbegrenzt" : "\($0) Tage" }
                    ?? "Standard (\(model.settings?.retentionDays ?? 7) Tage)")
                row("Batterie", BatteryLevel.label(d.battery))
                if let s = d.serial, !s.isEmpty { row("Seriennummer", s) }
                row("Abruf", d.enabled ? (d.lost.enabled || d.isGuarded
                                          ? "Schnell (alle \(model.settings?.lostPollInterval ?? 20) s)"
                                          : "Normal (alle \(model.settings?.pollInterval ?? 60) s)") : "pausiert")
            }
            .font(.subheadline)
        }
    }

    private func pointList(_ d: Device) -> some View {
        let rows = Array(model.track.enumerated().reversed())
        let shown = showAllRows ? rows : Array(rows.prefix(120))
        let groups = Dictionary(grouping: shown) { Calendar.current.startOfDay(for: $0.element.date) }
        return GlassSection(title: "Alle Punkte", systemImage: "list.bullet") {
            ForEach(groups.keys.sorted(by: >), id: \.self) { day in
                Text(day.formatted(.dateTime.weekday(.wide).day().month(.wide).locale(Locale(identifier: "de_DE"))))
                    .font(.footnote.bold()).foregroundStyle(.secondary).padding(.top, 6)
                ForEach(groups[day] ?? [], id: \.element.id) { i, r in
                    Button {
                        model.cursor = i
                        Haptics.selection()
                    } label: {
                        HStack(spacing: 10) {
                            Circle().fill(model.cursor == i ? d.tint : d.tint.opacity(0.3)).frame(width: 12, height: 12)
                            Text(r.date.timeDE).font(.subheadline.monospacedDigit())
                            Text("±\(r.accuracy ?? 0) m").font(.caption).foregroundStyle(.secondary)
                            if r.isBatch { badge("×\(r.batchSize ?? 1)", .purple) }
                            if r.isLate { badge("spät", .orange) }
                            Spacer()
                            Text("+\(r.delayMinutes) min").font(.caption2).foregroundStyle(.tertiary)
                        }
                        .padding(.vertical, 3)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            if !showAllRows && rows.count > 120 {
                Button("Alle \(rows.count) Punkte anzeigen") { Haptics.light(); showAllRows = true }.buttonStyle(.glass)
            }
            if rows.isEmpty {
                Text("Keine Punkte.").foregroundStyle(.secondary)
            }
        }
    }

    private func row(_ k: String, _ v: String) -> some View {
        GridRow {
            Text(k).foregroundStyle(.secondary)
            Text(v)
        }
    }

    private func badge(_ s: String, _ c: Color) -> some View {
        Text(s).font(.system(size: 9, weight: .heavy)).padding(.horizontal, 5).padding(.vertical, 2)
            .background(c.opacity(0.85), in: .capsule).foregroundStyle(.white)
    }

    // MARK: Logik

    private func toggleGuard(_ d: Device) async {
        do {
            try await model.patchDevice(d.id, ["alerts": ["guard": ["enabled": !d.isGuarded]]])
            Haptics.success()
            model.showToast(d.isGuarded ? "Wache deaktiviert" : "Wache aktiv – Alarm bei Bewegung")
        } catch {
            Haptics.warning()
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }

    private func writeGPX() {
        let reports = model.track
        guard !reports.isEmpty, let d = device else { gpxURL = nil; return }
        let iso = ISO8601DateFormatter()
        var s = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<gpx version=\"1.1\" creator=\"FindMy Ultra\" xmlns=\"http://www.topografix.com/GPX/1/1\">\n<trk><name>\(d.name.replacingOccurrences(of: "<", with: ""))</name><trkseg>\n"
        for r in reports {
            s += "<trkpt lat=\"\(r.lat)\" lon=\"\(r.lon)\"><time>\(iso.string(from: r.date))</time><hdop>\(r.accuracy ?? 0)</hdop></trkpt>\n"
        }
        s += "</trkseg></trk></gpx>\n"
        let safe = d.name.components(separatedBy: CharacterSet.alphanumerics.inverted).joined(separator: "_")
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(safe.isEmpty ? "verlauf" : safe).gpx")
        try? s.write(to: url, atomically: true, encoding: .utf8)
        gpxURL = url
    }
}

// MARK: - Bearbeiten

struct EditDeviceView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let device: Device
    @State private var name = ""
    @State private var emoji = ""
    @State private var color = ""
    @State private var retention = -1
    @State private var enabled = true
    @State private var saving = false

    private let palette = ["#0A84FF", "#FF9F0A", "#30D158", "#FF375F", "#BF5AF2", "#64D2FF", "#FFD60A", "#FF6482", "#5E5CE6", "#66D4CF"]

    var body: some View {
        Form {
            Section {
                HStack {
                    Spacer()
                    Text(emoji.isEmpty ? "📍" : emoji).font(.system(size: 54))
                        .frame(width: 96, height: 96)
                        .background(Color(.tertiarySystemFill), in: .circle)
                    Spacer()
                }
                .listRowBackground(Color.clear)
            }
            Section("Name & Symbol") {
                TextField("Name", text: $name)
                TextField("Emoji", text: $emoji)
                    .onChange(of: emoji) { _, v in if v.count > 2 { emoji = String(v.suffix(1)) } }
            }
            Section("Farbe der Spur") {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack {
                        ForEach(palette, id: \.self) { c in
                            Circle().fill(Color(hex: c)).frame(width: 34, height: 34)
                                .overlay(Circle().stroke(.primary, lineWidth: color == c ? 3 : 0))
                                .onTapGesture { color = c; Haptics.selection() }
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
            Section {
                Picker("Standortverlauf", selection: $retention) {
                    Text("Standard (\(model.settings?.retentionDays ?? 7) T)").tag(-1)
                    ForEach([1, 3, 7, 14, 30, 90, 180, 365], id: \.self) { Text("\($0) Tage").tag($0) }
                    Text("Unbegrenzt").tag(0)
                }
                Toggle("Standorte abrufen", isOn: $enabled)
            } footer: {
                Text("Apple speichert Berichte max. 7 Tage – der Server bewahrt sie so lange auf, wie du hier einstellst.")
            }
        }
        .navigationTitle("Bearbeiten")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Sichern") {
                    Task {
                        saving = true
                        defer { saving = false }
                        do {
                            try await model.patchDevice(device.id, ["name": name, "emoji": emoji, "color": color,
                                                                    "retention_days": retention, "enabled": enabled])
                            Haptics.success()
                            dismiss()
                        } catch { Haptics.warning(); model.showToast("⚠️ \(error.localizedDescription)") }
                    }
                }
                .disabled(name.isEmpty || saving)
            }
        }
        .onAppear {
            name = device.name; emoji = device.emoji ?? ""; color = device.color ?? palette[0]
            retention = device.retentionDays ?? -1; enabled = device.enabled
        }
    }
}
