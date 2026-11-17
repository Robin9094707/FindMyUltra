import SwiftUI
import MapKit

enum HistoryRange: Double, CaseIterable, Identifiable {
    case h1 = 3600, h6 = 21600, h24 = 86400, d3 = 259200, d7 = 604800, d30 = 2592000, all = 0
    var id: Double { rawValue }
    var label: String {
        switch self {
        case .h1: "1 h"
        case .h6: "6 h"
        case .h24: "24 h"
        case .d3: "3 T"
        case .d7: "7 T"
        case .d30: "30 T"
        case .all: "Alle"
        }
    }
}

struct DeviceDetailView: View {
    let deviceID: String
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @Environment(\.dismiss) private var dismiss

    @State private var range: HistoryRange = .d7
    @State private var reports: [Report] = []
    @State private var cursor: Double = 0
    @State private var playing = false
    @State private var follow = true
    @State private var position: MapCameraPosition = .automatic
    @State private var loading = false
    @State private var cursorAddress: String?
    @State private var sheet: SheetKind?
    @State private var confirmDelete = false
    @State private var showAllRows = false
    @State private var gpxURL: URL?
    @State private var style: MapStyleChoice = .standard

    enum SheetKind: String, Identifiable { case lost, alerts, edit; var id: String { rawValue } }

    private var device: Device? { model.device(deviceID) }
    private var current: Report? {
        reports.isEmpty ? nil : reports[min(max(Int(cursor.rounded()), 0), reports.count - 1)]
    }

    var body: some View {
        Group {
            if let d = device {
                content(d)
            } else {
                ContentUnavailableView("Objekt nicht gefunden", systemImage: "questionmark.circle")
            }
        }
        .navigationTitle(device?.name ?? "")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { toolbar }
        .task(id: range) { await load(fit: true) }
        .onChange(of: model.history[deviceID]) { _, h in
            guard let h, !playing else { return }
            let atEnd = Int(cursor.rounded()) >= reports.count - 1
            let since = range == .all ? 0 : Date().timeIntervalSince1970 - range.rawValue
            reports = h.filter { $0.ts >= since }
            if atEnd { cursor = Double(max(reports.count - 1, 0)) }
            writeGPX()
        }
        .onChange(of: cursor) { _, _ in
            guard follow, let r = current else { return }
            withAnimation(.smooth(duration: playing ? 0.3 : 0.5)) {
                position = .camera(MapCamera(centerCoordinate: r.coordinate, distance: 1400))
            }
        }
        .task(id: current?.id) {
            cursorAddress = nil
            if let r = current {
                try? await Task.sleep(for: .milliseconds(350))
                if !Task.isCancelled { cursorAddress = await model.address(for: r) }
            }
        }
        .task(id: playing) {
            guard playing else { return }
            if Int(cursor) >= reports.count - 1 { cursor = 0 }
            while playing && !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(420))
                if Int(cursor) >= reports.count - 1 { playing = false; break }
                cursor += 1
            }
        }
        .sheet(item: $sheet) { s in
            if let d = device {
                NavigationStack {
                    switch s {
                    case .lost: LostModeView(device: d)
                    case .alerts: AlertSettingsView(device: d)
                    case .edit: EditDeviceView(device: d)
                    }
                }
                .presentationDetents([.medium, .large])
            }
        }
        .confirmationDialog("Objekt entfernen?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Entfernen (inkl. Verlauf)", role: .destructive) {
                Task {
                    try? await model.deleteDevice(deviceID)
                    dismiss()
                }
            }
        } message: {
            Text("Die Schlüssel werden vom Server gelöscht. Du kannst sie jederzeit erneut importieren.")
        }
    }

    // MARK: Inhalt

    private func content(_ d: Device) -> some View {
        ScrollView {
            VStack(spacing: 16) {
                mapCard(d)
                rangePicker
                actions(d)
                if let r = current { pointInfo(r, d) }
                infoSection(d)
                historyList(d)
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 30)
        }
        .refreshable { _ = await model.refresh(deviceID: d.id); await load(fit: false) }
    }

    private func mapCard(_ d: Device) -> some View {
        let coords = reports.map(\.coordinate)
        let step = max(1, reports.count / 300)
        let dots = Array(stride(from: 0, to: reports.count, by: step)).map { reports[$0] }
        return Map(position: $position) {
            if coords.count > 1 {
                MapPolyline(coordinates: coords)
                    .stroke(d.tint.opacity(0.85), style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
            }
            ForEach(Array(dots.enumerated()), id: \.element.id) { i, r in
                Annotation("", coordinate: r.coordinate, anchor: .center) {
                    Circle()
                        .fill(d.tint.opacity(0.3 + 0.7 * Double(i) / Double(max(dots.count, 1))))
                        .frame(width: 8, height: 8)
                        .overlay(Circle().stroke(.white, lineWidth: 1))
                }
            }
            if let r = current {
                MapCircle(center: r.coordinate, radius: CLLocationDistance(max(r.accuracy ?? 5, 5)))
                    .foregroundStyle(d.tint.opacity(0.18))
                    .stroke(d.tint, lineWidth: 1)
                Annotation(d.name, coordinate: r.coordinate, anchor: .center) {
                    DeviceMarker(device: d, selected: true)
                }
            }
            if let g = d.alerts.guardMode.lat, let gl = d.alerts.guardMode.lon, d.isGuarded {
                MapCircle(center: .init(latitude: g, longitude: gl), radius: d.alerts.guardMode.radiusM)
                    .foregroundStyle(.orange.opacity(0.1))
                    .stroke(.orange, style: StrokeStyle(lineWidth: 2, dash: [6, 4]))
            }
            UserAnnotation()
        }
        .mapStyle(style.style)
        .frame(height: 430)
        .clipShape(.rect(cornerRadius: 30))
        .overlay(alignment: .topTrailing) {
            GlassEffectContainer(spacing: 8) {
                VStack(spacing: 8) {
                    Button { fit() } label: { Image(systemName: "scope").frame(width: 40, height: 40) }
                        .glassEffect(.regular.interactive(), in: .circle)
                    Button { withAnimation { style = style.next } } label: {
                        Image(systemName: style.icon).frame(width: 40, height: 40)
                    }
                    .glassEffect(.regular.interactive(), in: .circle)
                    Button { follow.toggle() } label: {
                        Image(systemName: follow ? "location.fill" : "location").frame(width: 40, height: 40)
                    }
                    .glassEffect(.regular.interactive(), in: .circle)
                }
                .buttonStyle(.plain)
            }
            .padding(10)
        }
        .overlay(alignment: .bottom) { timeline(d).padding(10) }
        .overlay {
            if loading { ProgressView().padding().glassEffect(.regular, in: .circle) }
        }
    }

    // MARK: Verlaufsleiste

    private func timeline(_ d: Device) -> some View {
        VStack(spacing: 8) {
            if reports.count > 1 {
                densityStrip(d).frame(height: 14)
            }
            HStack(spacing: 10) {
                Button { cursor = max(0, cursor - 1) } label: { Image(systemName: "backward.frame.fill") }
                    .disabled(cursor <= 0)
                Button { playing.toggle() } label: {
                    Image(systemName: playing ? "pause.fill" : "play.fill").frame(width: 22)
                }
                .disabled(reports.count < 2)
                Button { cursor = min(Double(reports.count - 1), cursor + 1) } label: { Image(systemName: "forward.frame.fill") }
                    .disabled(Int(cursor) >= reports.count - 1)
                if reports.count > 1 {
                    Slider(value: $cursor, in: 0...Double(reports.count - 1), step: 1)
                        .tint(d.tint)
                } else {
                    Spacer()
                }
            }
            .buttonStyle(.plain)
            .font(.system(size: 16, weight: .semibold))
            HStack {
                if let r = current {
                    Text(r.date.shortDE).font(.caption.monospacedDigit().bold())
                    Text("· ±\(r.accuracy ?? 0) m").font(.caption).foregroundStyle(.secondary)
                    if r.isBatch { badge("BATCH ×\(r.batchSize ?? 1)", .purple) }
                    if r.isLate { badge("NACHGEREICHT", .orange) }
                }
                Spacer()
                Text(reports.isEmpty ? "keine Punkte" : "\(Int(cursor) + 1) / \(reports.count)")
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .glassEffect(.regular, in: .rect(cornerRadius: 22))
        .sensoryFeedback(.selection, trigger: Int(cursor))
    }

    private func densityStrip(_ d: Device) -> some View {
        let first = reports.first?.ts ?? 0
        let span = max((reports.last?.ts ?? 1) - first, 1)
        let cur = current?.ts
        return Canvas { ctx, size in
            for r in reports {
                let x = (r.ts - first) / span * size.width
                ctx.fill(Path(CGRect(x: x, y: 2, width: 1.5, height: size.height - 4)), with: .color(d.tint.opacity(0.55)))
            }
            if let cur {
                let x = (cur - first) / span * size.width
                ctx.fill(Path(roundedRect: CGRect(x: x - 2, y: 0, width: 4, height: size.height), cornerRadius: 2),
                         with: .color(.primary))
            }
        }
        // Auf der Leiste tippen/ziehen springt zum nächstgelegenen Zeitpunkt
        .overlay(GeometryReader { geo in
            Color.clear.contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0).onChanged { v in
                    let t = first + Double(min(max(v.location.x / geo.size.width, 0), 1)) * span
                    if let i = reports.firstIndex(where: { $0.ts >= t }) { cursor = Double(i) }
                })
        })
    }

    private var rangePicker: some View {
        Picker("Zeitraum", selection: $range) {
            ForEach(HistoryRange.allCases) { Text($0.label).tag($0) }
        }
        .pickerStyle(.segmented)
    }

    // MARK: Aktionen

    private func actions(_ d: Device) -> some View {
        GlassEffectContainer(spacing: 10) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: 3), spacing: 10) {
                action("Orten", "location.magnifyingglass", .blue) {
                    Task { _ = await model.refresh(deviceID: d.id); await load(fit: false) }
                }
                action("Route", "car.fill", .green) {
                    if let r = d.last, let u = appleMapsURL(r, name: d.name, directions: true) { openURL(u) }
                }
                action(d.lost.enabled ? "Verloren ✓" : "Verloren", "exclamationmark.triangle.fill",
                       .red, active: d.lost.enabled) { sheet = .lost }
                action(d.isGuarded ? "Wache an" : "Wache", "shield.lefthalf.filled", .orange, active: d.isGuarded) {
                    Task { await toggleGuard(d) }
                }
                action("Alarme", "bell.badge.fill", .purple) { sheet = .alerts }
                if let gpxURL {
                    ShareLink(item: gpxURL) {
                        actionLabel("Export", "square.and.arrow.up", .teal, active: false)
                    }
                    .buttonStyle(.plain)
                } else {
                    action("Export", "square.and.arrow.up", .teal) {}
                        .disabled(true)
                }
            }
        }
    }

    private func action(_ title: String, _ icon: String, _ c: Color, active: Bool = false,
                        _ run: @escaping () -> Void) -> some View {
        Button(action: run) { actionLabel(title, icon, c, active: active) }
            .buttonStyle(.plain)
    }

    private func actionLabel(_ title: String, _ icon: String, _ c: Color, active: Bool) -> some View {
        VStack(spacing: 6) {
            Image(systemName: icon).font(.title3).foregroundStyle(active ? .white : c)
            Text(title).font(.caption.weight(.semibold)).lineLimit(1)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 14)
        .glassEffect(active ? .regular.tint(c.opacity(0.7)).interactive() : .regular.interactive(),
                     in: .rect(cornerRadius: 22))
    }

    // MARK: Infos

    private func pointInfo(_ r: Report, _ d: Device) -> some View {
        GlassSection(title: "Ausgewählter Standort", systemImage: "mappin.circle.fill") {
            if let cursorAddress { Text(cursorAddress).font(.body.weight(.medium)) }
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                row("Geortet", "\(r.date.shortDE) (\(r.date.relativeDE))")
                row("Empfangen", "\(r.receivedDate.timeDE) · +\(r.delayMinutes) min")
                row("Genauigkeit", "±\(r.accuracy ?? 0) m")
                row("Koordinaten", String(format: "%.6f, %.6f", r.lat, r.lon))
                if r.isBatch { row("Batch", "\(r.batchSize ?? 1) Berichte gleichzeitig") }
                if r.isLate { row("Hinweis", "nachgereicht (älter als bisher neuester)") }
                if let b = r.battery { row("Batterie", BatteryLevel.label(b)) }
            }
            .font(.subheadline)
            HStack {
                Button("In Karten öffnen") { if let u = appleMapsURL(r, name: d.name) { openURL(u) } }
                    .buttonStyle(.glass)
                Button {
                    UIPasteboard.general.string = String(format: "%.6f, %.6f", r.lat, r.lon)
                    model.showToast("Koordinaten kopiert")
                } label: { Image(systemName: "doc.on.doc") }
                .buttonStyle(.glass)
            }
        }
    }

    private func infoSection(_ d: Device) -> some View {
        GlassSection(title: "Objekt", systemImage: "info.circle.fill") {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                row("Standorte gesamt", "\(d.total)")
                if let f = d.firstTs { row("Verlauf seit", Date(timeIntervalSince1970: f).shortDE) }
                row("Aufbewahrung", d.retentionDays.map { $0 == 0 ? "unbegrenzt" : "\($0) Tage" }
                    ?? "Standard (\(model.settings?.retentionDays ?? 7) Tage)")
                row("Batterie", BatteryLevel.label(d.battery))
                if let s = d.serial, !s.isEmpty { row("Seriennummer", s) }
                row("Abruf", d.enabled ? (d.lost.enabled || d.isGuarded ? "Schnell (\(model.settings?.lostPollInterval ?? 20) s)" : "Normal (\(model.settings?.pollInterval ?? 60) s)") : "pausiert")
            }
            .font(.subheadline)
        }
    }

    private func historyList(_ d: Device) -> some View {
        let rows = Array(reports.enumerated().reversed())
        let shown = showAllRows ? rows : Array(rows.prefix(150))
        let groups = Dictionary(grouping: shown) { Calendar.current.startOfDay(for: $0.element.date) }
        return GlassSection(title: "Standortverlauf (\(reports.count))", systemImage: "list.bullet.below.rectangle") {
            ForEach(groups.keys.sorted(by: >), id: \.self) { day in
                Text(day.formatted(.dateTime.weekday(.wide).day().month(.wide).locale(Locale(identifier: "de_DE"))))
                    .font(.footnote.bold()).foregroundStyle(.secondary).padding(.top, 6)
                ForEach(groups[day] ?? [], id: \.element.id) { i, r in
                    Button {
                        cursor = Double(i)
                    } label: {
                        HStack(spacing: 10) {
                            Circle().fill(Int(cursor) == i ? d.tint : d.tint.opacity(0.3)).frame(width: 10, height: 10)
                            Text(r.date.timeDE).font(.subheadline.monospacedDigit())
                            Text("±\(r.accuracy ?? 0) m").font(.caption).foregroundStyle(.secondary)
                            if r.isBatch { badge("×\(r.batchSize ?? 1)", .purple) }
                            if r.isLate { badge("spät", .orange) }
                            Spacer()
                            Text("+\(r.delayMinutes) min").font(.caption2).foregroundStyle(.tertiary)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            if !showAllRows && rows.count > 150 {
                Button("Alle \(rows.count) Punkte anzeigen") { showAllRows = true }.buttonStyle(.glass)
            }
            if reports.isEmpty {
                Text(loading ? "Lädt …" : "Keine Standorte in diesem Zeitraum.").foregroundStyle(.secondary)
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

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Menu {
                Button { sheet = .edit } label: { Label("Bearbeiten", systemImage: "pencil") }
                Button { sheet = .alerts } label: { Label("Alarme", systemImage: "bell.badge") }
                Button { sheet = .lost } label: { Label("Verloren-Modus", systemImage: "exclamationmark.triangle") }
                Button {
                    Task { _ = await model.refresh(deviceID: deviceID, full: true); await load(fit: false) }
                } label: { Label("7-Tage-Scan", systemImage: "clock.arrow.2.circlepath") }
                if let d = device {
                    Button {
                        Task { try? await model.patchDevice(deviceID, ["enabled": !d.enabled]) }
                    } label: { Label(d.enabled ? "Abruf pausieren" : "Abruf fortsetzen", systemImage: "pause.circle") }
                }
                Divider()
                Button(role: .destructive) { confirmDelete = true } label: { Label("Entfernen", systemImage: "trash") }
            } label: {
                Image(systemName: "ellipsis")
            }
        }
    }

    // MARK: Logik

    private func load(fit: Bool) async {
        loading = true
        defer { loading = false }
        let since: Double? = range == .all ? nil : Date().timeIntervalSince1970 - range.rawValue
        do {
            reports = try await model.loadHistory(deviceID, since: since)
            cursor = Double(max(reports.count - 1, 0))
            writeGPX()
            if fit { self.fit() }
        } catch {
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }

    private func fit() {
        let coords = reports.map(\.coordinate)
        if let r = region(fitting: coords, padding: 1.4) {
            withAnimation(.smooth) { position = .region(r) }
        } else if let l = device?.last {
            withAnimation(.smooth) {
                position = .region(MKCoordinateRegion(center: l.coordinate, latitudinalMeters: 800, longitudinalMeters: 800))
            }
        }
    }

    private func toggleGuard(_ d: Device) async {
        do {
            try await model.patchDevice(d.id, ["alerts": ["guard": ["enabled": !d.isGuarded]]])
            model.showToast(d.isGuarded ? "Wache deaktiviert" : "🛡️ Wache aktiv – Alarm bei Bewegung")
        } catch {
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }

    private func writeGPX() {
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
            Section("Name & Symbol") {
                TextField("Name", text: $name)
                TextField("Emoji", text: $emoji)
                    .onChange(of: emoji) { _, v in if v.count > 2 { emoji = String(v.suffix(1)) } }
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack {
                        ForEach(palette, id: \.self) { c in
                            Circle().fill(Color(hex: c)).frame(width: 34, height: 34)
                                .overlay(Circle().stroke(.primary, lineWidth: color == c ? 3 : 0))
                                .onTapGesture { color = c }
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
                            dismiss()
                        } catch { model.showToast("⚠️ \(error.localizedDescription)") }
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
