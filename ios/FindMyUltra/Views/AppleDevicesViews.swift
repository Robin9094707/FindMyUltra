import SwiftUI
import MapKit

// MARK: - Symbol / Pin

struct AppleGlyph: View {
    let device: AppleDevice
    var size: CGFloat = 46
    var body: some View {
        Group {
            if let e = device.emoji, !e.isEmpty {
                Text(e).font(.system(size: size * 0.5))
            } else {
                Image(systemName: device.symbol)
                    .font(.system(size: size * 0.44, weight: .regular))
                    .foregroundStyle(.primary)
            }
        }
        .frame(width: size, height: size)
        .background(Color(.tertiarySystemFill), in: .circle)
        .overlay(alignment: .bottomTrailing) {
            if let b = device.best {
                Circle().fill(b.isOnline ? Color.green : Color.gray)
                    .frame(width: size * 0.26, height: size * 0.26)
                    .overlay(Circle().stroke(Color(.systemBackground), lineWidth: 2))
            }
        }
    }
}

/// Karten-Pin für Apple-Geräte (gleicher Stil wie AirTags, mit Gerätesymbol).
struct ApplePin: View {
    let device: AppleDevice
    var selected: Bool = false
    var symbolOverride: String? = nil
    var label: String? = nil

    var body: some View {
        let bubble: CGFloat = selected ? 58 : 46
        VStack(spacing: 0) {
            ZStack {
                Circle()
                    .fill(Color(.secondarySystemGroupedBackground))
                    .frame(width: bubble, height: bubble)
                    .overlay(Circle().stroke(Color.white.opacity(0.12), lineWidth: 1))
                if let e = device.emoji, !e.isEmpty, symbolOverride == nil {
                    Text(e).font(.system(size: bubble * 0.5))
                } else {
                    Image(systemName: symbolOverride ?? device.symbol)
                        .font(.system(size: bubble * 0.42))
                        .foregroundStyle(.primary)
                }
            }
            .overlay(alignment: .topTrailing) {
                if let label {
                    Text(label).font(.system(size: 9, weight: .heavy))
                        .padding(.horizontal, 5).padding(.vertical, 2)
                        .background(Color.blue, in: .capsule).foregroundStyle(.white)
                        .offset(x: 6, y: -4)
                }
            }
            PinTail()
                .fill(Color(.secondarySystemGroupedBackground))
                .frame(width: 14, height: 9)
                .offset(y: -1.5)
            Circle()
                .fill(Color.white)
                .frame(width: 9, height: 9)
                .overlay(Circle().stroke(device.best?.isOnline == true ? Color.green : Color.gray, lineWidth: 3))
                .padding(.top, 3)
        }
        .compositingGroup()
        .shadow(color: .black.opacity(0.3), radius: 8, y: 4)
        .animation(.spring(duration: 0.35, bounce: 0.35), value: selected)
    }
}

struct SourceBadge: View {
    let best: BestLocation
    var body: some View {
        let role = best.role.flatMap(PartRole.init(rawValue:))
        Text(best.isOnline ? "Online" : "Offline\(role.map { $0 == .main ? "" : " · \($0.short)" } ?? "")")
            .font(.system(size: 10, weight: .bold))
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background((best.isOnline ? Color.green : Color.gray).opacity(0.2), in: .capsule)
            .foregroundStyle(best.isOnline ? Color.green : Color.secondary)
    }
}

// MARK: - Geräte-Tab

struct DevicesTabView: View {
    @Environment(AppModel.self) private var model
    @State private var showAdd = false

    var body: some View {
        List {
            if let st = model.onlineStatus, let e = st.error, st.enabled {
                Section {
                    Label {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Online-Ortung nicht verfügbar").font(.subheadline.bold())
                            Text(e).font(.caption).foregroundStyle(.secondary)
                        }
                    } icon: {
                        Image(systemName: "icloud.slash").foregroundStyle(.orange)
                    }
                    .listRowBackground(Color.orange.opacity(0.12))
                }
            }
            Section {
                ForEach(model.appleDevices) { d in
                    Button { model.openApple(d.id) } label: { AppleDeviceRow(device: d) }
                        .buttonStyle(.plain)
                        .listRowBackground(Color.clear)
                        .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 6, trailing: 16))
                }
            } header: {
                HStack {
                    Text("Meine Geräte")
                    Spacer()
                    if let t = model.onlineStatus?.lastRefresh {
                        Text("Online \(Date(timeIntervalSince1970: t).relativeDE)").font(.caption).foregroundStyle(.secondary)
                    }
                }
                .textCase(nil)
            }
            if model.appleDevices.isEmpty {
                ContentUnavailableView {
                    Label("Keine Geräte", systemImage: "iphone.gen3")
                } description: {
                    Text("Deine Apple-Geräte erscheinen automatisch, sobald der Server bei Apple angemeldet ist. Du kannst Geräte auch manuell anlegen und ihre Offline-Schlüssel (AirTag-JSON) importieren.")
                } actions: {
                    Button("Gerät hinzufügen") { showAdd = true }.buttonStyle(.glassProminent)
                }
                .listRowBackground(Color.clear)
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .refreshable { await model.refreshApple() }
        .safeAreaInset(edge: .top, spacing: 0) {
            HStack {
                Text("Geräte").font(.largeTitle.bold())
                Spacer()
                Button { Task { await model.refreshApple() } } label: {
                    Group {
                        if model.isRefreshingApple { ProgressView() } else { Image(systemName: "arrow.clockwise") }
                    }
                    .font(.title3.weight(.semibold)).frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .glassEffect(.regular.interactive(), in: .circle)
                Button { Haptics.light(); showAdd = true } label: {
                    Image(systemName: "plus").font(.title3.weight(.semibold)).frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .glassEffect(.regular.interactive(), in: .circle)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
        }
        .sheet(isPresented: $showAdd) {
            NavigationStack { AddAppleDeviceView() }
                .presentationDetents([.medium, .large])
        }
        .task { await model.reloadAppleDevices() }
    }
}

struct AppleDeviceRow: View {
    @Environment(AppModel.self) private var model
    let device: AppleDevice
    @State private var address: String?

    var body: some View {
        HStack(spacing: 14) {
            AppleGlyph(device: device, size: 50)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(device.name).font(.headline).lineLimit(1)
                    if let b = device.best { SourceBadge(best: b) }
                }
                if let b = device.best {
                    HStack(spacing: 0) {
                        Text(address ?? "Standort wird ermittelt …").foregroundStyle(.secondary)
                        Text(" · ").foregroundStyle(.secondary).layoutPriority(1)
                        AgeText(date: b.date).fontWeight(.medium).layoutPriority(2)
                    }
                    .font(.subheadline).lineLimit(1)
                } else {
                    Text(device.parts.isEmpty && !device.isCloud ? "Keine Offline-Datei importiert" : "Kein Standort gefunden")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                if device.isAirPods {
                    HStack(spacing: 8) {
                        ForEach(PartRole.allCases.filter { $0 != .main }) { r in
                            let p = device.part(r)
                            Label(r.short, systemImage: r.symbol)
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(p?.last != nil ? ageColor(p!.last!.date) : Color.secondary.opacity(0.5))
                        }
                    }
                }
            }
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 4) {
                if let b = device.best, let dist = model.distanceFromUser(lat: b.lat, lon: b.lon) {
                    Text(dist).font(.subheadline).foregroundStyle(.secondary)
                }
                if let t = device.batteryText {
                    HStack(spacing: 3) {
                        Text(t).font(.caption.monospacedDigit())
                        Image(systemName: device.batteryIcon)
                    }
                    .foregroundStyle(device.batteryColor)
                }
            }
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
        .task(id: device.best?.ts) {
            if let b = device.best { address = await model.address(lat: b.lat, lon: b.lon) }
        }
    }
}

// MARK: - Gerät hinzufügen

struct AddAppleDeviceView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var type = "iPhone"
    @State private var saving = false

    private let types: [(String, String)] = [("iPhone", "iphone.gen3"), ("iPad", "ipad"), ("MacBook", "laptopcomputer"),
                                             ("Mac", "desktopcomputer"), ("Watch", "applewatch"), ("AirPods", "airpodspro"),
                                             ("Sonstiges", "dot.radiowaves.left.and.right")]

    var body: some View {
        Form {
            Section {
                TextField("Name (z. B. iPhone von Robin)", text: $name)
            }
            Section("Typ") {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 4), spacing: 12) {
                    ForEach(types, id: \.0) { t in
                        Button {
                            Haptics.selection()
                            type = t.0
                        } label: {
                            VStack(spacing: 6) {
                                Image(systemName: t.1).font(.title2)
                                    .frame(width: 52, height: 52)
                                    .background(type == t.0 ? Color.blue.opacity(0.25) : Color(.tertiarySystemFill), in: .circle)
                                    .overlay(Circle().stroke(type == t.0 ? Color.blue : .clear, lineWidth: 2))
                                Text(t.0).font(.caption2)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.vertical, 6)
            }
            Section {
                Text(type == "AirPods"
                     ? "AirPods-Modus: Danach kannst du für den linken AirPod, den rechten AirPod und das Ladecase je eine AirTag-JSON-Datei importieren."
                     : "Danach kannst du die Offline-Schlüsseldatei (AirTag-JSON) des Geräts importieren. Online-Standorte kommen automatisch, wenn das Gerät in deinem Apple-Account ist.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Gerät hinzufügen")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Hinzufügen") { Task { await save() } }.disabled(saving)
            }
        }
    }

    private func save() async {
        guard let api = model.api else { return }
        saving = true
        defer { saving = false }
        do {
            let d: AppleDevice = try await api.send("POST", "/api/apple-devices", json: [
                "name": name.isEmpty ? type : name, "mode": type == "AirPods" ? "airpods" : "device",
                "device_class": type])
            await model.reloadAppleDevices()
            Haptics.success()
            dismiss()
            model.openApple(d.id)
        } catch {
            Haptics.warning()
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }
}

// MARK: - Gerätedetail

struct AppleDeviceDetailView: View {
    let deviceID: String
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @State private var address: String?
    @State private var importRole: PartRole?
    @State private var renaming = false
    @State private var newName = ""
    @State private var confirmDelete = false
    @State private var busy = false

    private var device: AppleDevice? { model.appleDevice(deviceID) }

    var body: some View {
        Group {
            if let d = device {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        header(d)
                        actions(d)
                        locationsCard(d)
                        offlineCard(d)
                        infoCard(d)
                    }
                    .padding(.horizontal, 16).padding(.top, 16).padding(.bottom, 40)
                }
                .refreshable { await model.refreshApple(d.id) }
            } else {
                ContentUnavailableView("Gerät nicht gefunden", systemImage: "questionmark.circle")
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .onAppear { model.focusApple(deviceID) }
        .task(id: device?.best?.ts) {
            if let b = device?.best { address = await model.address(lat: b.lat, lon: b.lon) }
        }
        .sheet(item: $importRole) { role in
            DocumentPicker(multiple: false) { urls in
                importRole = nil
                Task { await importFile(urls.first, role: role) }
            } onCancel: { importRole = nil }
            .ignoresSafeArea()
        }
        .alert("Umbenennen", isPresented: $renaming) {
            TextField("Name", text: $newName)
            Button("Sichern") { Task { await patch(["name": newName]) } }
            Button("Abbrechen", role: .cancel) {}
        }
        .confirmationDialog(device?.isCloud == true ? "Gerät ausblenden?" : "Gerät entfernen?",
                            isPresented: $confirmDelete, titleVisibility: .visible) {
            Button(device?.isCloud == true ? "Ausblenden" : "Entfernen", role: .destructive) {
                Task {
                    _ = try? await model.api?.send("DELETE", "/api/apple-devices/\(deviceID)", as: OKResult.self)
                    await model.reloadAppleDevices()
                    Haptics.success()
                    model.sheetPath = []
                }
            }
        } message: {
            Text("Importierte Offline-Schlüssel dieses Geräts werden vom Server gelöscht.")
        }
    }

    private func header(_ d: AppleDevice) -> some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(d.name).font(.title.bold()).lineLimit(2)
                if let b = d.best {
                    Text(address ?? String(format: "%.5f, %.5f", b.lat, b.lon))
                        .foregroundStyle(.secondary).lineLimit(1)
                    HStack(spacing: 6) {
                        AgeText(date: b.date).fontWeight(.medium)
                        SourceBadge(best: b)
                        if let t = d.batteryText {
                            Text("·").foregroundStyle(.secondary)
                            Text(t).foregroundStyle(d.batteryColor)
                            Image(systemName: d.batteryIcon).foregroundStyle(d.batteryColor)
                        }
                    }
                    .font(.subheadline)
                } else {
                    Text("Kein Standort gefunden").foregroundStyle(.secondary)
                }
            }
            Spacer()
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

    private func actions(_ d: AppleDevice) -> some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
            Button { Task { await model.refreshApple(d.id) } } label: {
                ActionTile(title: model.isRefreshingApple ? "Suche …" : "Orten", subtitle: "Online + Offline",
                           icon: "location.magnifyingglass", color: .blue)
            }
            .disabled(model.isRefreshingApple)
            Button {
                Haptics.light()
                if let b = d.best, let u = URL(string: "https://maps.apple.com/?daddr=\(b.lat),\(b.lon)") { openURL(u) }
            } label: {
                ActionTile(title: "Route", subtitle: "Apple Karten", icon: "arrow.triangle.turn.up.right.diamond.fill", color: .blue)
            }
            .disabled(d.best == nil)
            Button { Task { await playSound(d) } } label: {
                ActionTile(title: "Ton abspielen", subtitle: d.isCloud ? (busy ? "Wird gesendet …" : "Über iCloud") : "Nur online-Geräte",
                           icon: "speaker.wave.2.fill", color: .purple)
            }
            .disabled(!d.isCloud || busy)
            Button { newName = d.name; renaming = true } label: {
                ActionTile(title: "Umbenennen", subtitle: d.appleName.map { "Apple: \($0)" } ?? "Name ändern", icon: "pencil", color: .gray)
            }
        }
        .buttonStyle(PressableStyle())
    }

    private func locationsCard(_ d: AppleDevice) -> some View {
        GlassSection(title: "Ortung", systemImage: "location.circle.fill") {
            locRow(icon: "icloud.fill", color: .green, title: "Online (iCloud)",
                   date: d.online?.date,
                   detail: d.online.map { "±\(Int($0.accuracy ?? 0)) m\($0.positionType.map { " · \($0)" } ?? "")" },
                   empty: d.isCloud ? "Kein Online-Standort" : "Nicht mit iCloud verbunden",
                   coord: d.online?.coordinate)
            ForEach(d.roles) { r in
                let p = d.part(r)
                locRow(icon: r == .main ? "antenna.radiowaves.left.and.right" : r.symbol, color: .gray,
                       title: r == .main ? "Offline (Wo-ist-Netzwerk)" : r.label,
                       date: p?.last?.date,
                       detail: p?.last.map { "±\($0.accuracy ?? 0) m · \(p?.total ?? 0) Standorte" },
                       empty: p == nil ? "Keine Schlüsseldatei" : "Noch kein Standort",
                       coord: p?.last?.coordinate)
            }
        }
    }

    private func locRow(icon: String, color: Color, title: String, date: Date?, detail: String?,
                        empty: String, coord: CLLocationCoordinate2D?) -> some View {
        Button {
            if let coord {
                Haptics.selection()
                model.show(center: coord, meters: 700)
            }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: icon).font(.body).foregroundStyle(.white)
                    .frame(width: 32, height: 32).background(color.gradient, in: .circle)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.subheadline.weight(.semibold))
                    if let date {
                        HStack(spacing: 4) {
                            AgeText(date: date)
                            if let detail { Text("· \(detail)").foregroundStyle(.secondary) }
                        }
                        .font(.caption)
                    } else {
                        Text(empty).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if coord != nil { Image(systemName: "scope").foregroundStyle(.secondary) }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func offlineCard(_ d: AppleDevice) -> some View {
        GlassSection(title: d.isAirPods ? "AirPods-Schlüssel" : "Offline-Schlüssel", systemImage: "key.fill") {
            Picker("Modus", selection: Binding(get: { d.mode }, set: { m in Task { await patch(["mode": m]) } })) {
                Text("Gerät").tag("device")
                Text("AirPods (L/R/Case)").tag("airpods")
            }
            .pickerStyle(.segmented)
            ForEach(d.roles) { r in
                let p = d.part(r)
                HStack(spacing: 12) {
                    Image(systemName: r == .main ? d.symbol : r.symbol)
                        .frame(width: 32, height: 32)
                        .background(Color(.tertiarySystemFill), in: .circle)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(r.label).font(.subheadline.weight(.semibold))
                        Text(p == nil ? "Keine Datei importiert" : "Importiert · \(p?.total ?? 0) Standorte")
                            .font(.caption).foregroundStyle(p == nil ? Color.secondary : Color.green)
                    }
                    Spacer()
                    Menu {
                        Button { importRole = r } label: {
                            Label(p == nil ? "Datei importieren" : "Datei ändern", systemImage: "square.and.arrow.down")
                        }
                        if p != nil {
                            Button(role: .destructive) { Task { await removeRole(r) } } label: {
                                Label("Entfernen", systemImage: "trash")
                            }
                        }
                    } label: {
                        Text(p == nil ? "Importieren" : "Ändern").font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 12).padding(.vertical, 7)
                            .background(Color.blue.opacity(0.15), in: .capsule)
                    }
                }
            }
            Text("Klassische AirTag-JSON-Datei (FindMy.py-Format) oder entschlüsselte .plist – genau wie bei Objekten. Ohne Standortverlauf; es zählt nur der jeweils neueste Standort.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private func infoCard(_ d: AppleDevice) -> some View {
        GlassSection(title: "Details", systemImage: "info.circle.fill") {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                if let m = d.displayName ?? d.model { row("Modell", m) }
                row("Quelle", d.isCloud ? "Apple-Account (iCloud)" : "Manuell angelegt")
                if let a = d.appleName, a != d.name { row("Name bei Apple", a) }
                if let s = d.batteryStatus, d.batteryLevel != nil {
                    row("Akku", s == "Charging" ? "Lädt" : (s == "NotCharging" ? "Lädt nicht" : s))
                }
                if d.isCloud { row("Erreichbar", d.reachable == true ? "Ja" : "Nein") }
            }
            .font(.subheadline)
            Button(role: .destructive) { confirmDelete = true } label: {
                Label(d.isCloud ? "Gerät ausblenden" : "Gerät entfernen", systemImage: "trash").frame(maxWidth: .infinity)
            }
            .buttonStyle(.glass)
            .tint(.red)
        }
    }

    private func row(_ k: String, _ v: String) -> some View {
        GridRow {
            Text(k).foregroundStyle(.secondary)
            Text(v)
        }
    }

    // MARK: Aktionen

    private func patch(_ body: [String: Any]) async {
        do {
            let _: AppleDevice = try await model.api!.send("PATCH", "/api/apple-devices/\(deviceID)", json: body)
            await model.reloadAppleDevices()
            Haptics.success()
        } catch {
            Haptics.warning()
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }

    private func importFile(_ url: URL?, role: PartRole) async {
        guard let url, let api = model.api else { return }
        let ok = url.startAccessingSecurityScopedResource()
        defer { if ok { url.stopAccessingSecurityScopedResource() } }
        guard let data = try? Data(contentsOf: url) else {
            model.showToast("❌ Datei konnte nicht gelesen werden")
            return
        }
        do {
            let _: AppleDevice = try await api.uploadOne("/api/apple-devices/\(deviceID)/offline",
                                                         query: [.init(name: "role", value: role.rawValue)],
                                                         name: url.lastPathComponent, data: data)
            await model.reloadAppleDevices()
            await model.reloadDevices()
            Haptics.success()
            model.showToast("\(role.label): Schlüssel importiert – Standorte werden geholt")
        } catch {
            Haptics.warning()
            model.showToast("❌ \(error.localizedDescription)")
        }
    }

    private func removeRole(_ r: PartRole) async {
        do {
            let _: AppleDevice = try await model.api!.send("DELETE", "/api/apple-devices/\(deviceID)/offline/\(r.rawValue)")
            await model.reloadAppleDevices()
            Haptics.success()
        } catch {
            Haptics.warning()
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }

    private func playSound(_ d: AppleDevice) async {
        busy = true
        defer { busy = false }
        do {
            let _: OKResult = try await model.api!.send("POST", "/api/apple-devices/\(d.id)/sound")
            Haptics.success()
            model.showToast("🔊 Ton wird auf \(d.name) abgespielt")
        } catch {
            Haptics.warning()
            model.showToast("⚠️ \(error.localizedDescription)")
        }
    }
}
