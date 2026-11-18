import SwiftUI

struct DeviceListView: View {
    @Environment(AppModel.self) private var model
    @State private var importing = false
    @State private var importMessage: String?

    var body: some View {
        List {
            if let ns = model.newSince, ns.total > 0 {
                Section {
                    NewSinceCard(info: ns)
                        .listRowBackground(Color.yellow.opacity(0.12))
                }
            }
            if model.presentNetworks.count > 1 {
                Section {
                    NetworkFilterBar()
                        .listRowBackground(Color.clear)
                        .listRowInsets(EdgeInsets(top: 0, leading: 12, bottom: 0, trailing: 12))
                }
            }
            let groups = groupedItems
            ForEach(groups, id: \.network) { g in
                Section {
                    ForEach(g.items) { d in row(d) }
                } header: {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        if groups.count > 1 {
                            Image(systemName: g.network.symbol).foregroundStyle(g.network == .apple ? Color.primary : g.network.color)
                            Text("\(g.network.label) · \(g.items.count)")
                        } else {
                            Text("Meine Objekte")
                        }
                        Spacer()
                        if g.network == groups.first?.network, let s = model.status {
                            Text("\(s.stats.total) Standorte · \(s.stats.today) heute")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .textCase(nil)
                }
            }

            if model.items.isEmpty {
                ContentUnavailableView {
                    Label("Keine Objekte", systemImage: "airtag")
                } description: {
                    Text("Importiere die JSON- oder plist-Schlüssel deiner AirTags oder verbinde Google bzw. Samsung unter „Ich → Netzwerke“.")
                } actions: {
                    Button("Schlüssel importieren") { importing = true }.buttonStyle(.glassProminent)
                    Button("Netzwerke verbinden") { model.section = .me; model.sheetPath = [] }.buttonStyle(.glass)
                }
                .listRowBackground(Color.clear)
            } else if model.visibleItems.isEmpty {
                ContentUnavailableView {
                    Label("Nichts in diesem Netz", systemImage: "line.3.horizontal.decrease.circle")
                } description: {
                    Text("Der Netz-Filter blendet gerade alle Objekte aus.")
                } actions: {
                    Button("Alle Netze zeigen") { model.showOnly(nil) }.buttonStyle(.glass)
                }
                .listRowBackground(Color.clear)
            }
            if let importMessage {
                Text(importMessage).font(.footnote).listRowBackground(Color.clear)
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .refreshable { await model.refresh() }
        .safeAreaInset(edge: .top, spacing: 0) {
            HStack {
                Text("Objekte").font(.largeTitle.bold())
                Spacer()
                Button {
                    Haptics.light()
                    importing = true
                } label: {
                    Image(systemName: "plus").font(.title3.weight(.semibold)).frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .glassEffect(.regular.interactive(), in: .circle)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
        }
        .sheet(isPresented: $importing) {
            DocumentPicker { urls in
                importing = false
                Task { importMessage = await KeyImporter.importFiles(urls, model: model) }
            } onCancel: { importing = false }
            .ignoresSafeArea()
        }
    }
}

extension DeviceListView {
    struct NetworkGroup { let network: TrackerNetwork; let items: [Device] }

    /// Bei mehreren sichtbaren Netzen nach Netz gruppiert, sonst eine Liste.
    var groupedItems: [NetworkGroup] {
        let items = model.visibleItems
        guard !items.isEmpty else { return [] }
        let nets = TrackerNetwork.allCases.filter { n in items.contains { $0.net == n } }
        if nets.count <= 1 { return [NetworkGroup(network: nets.first ?? .apple, items: items)] }
        return nets.map { n in NetworkGroup(network: n, items: items.filter { $0.net == n }) }
    }

    func row(_ d: Device) -> some View {
        Button {
            model.openDevice(d.id)
        } label: {
            DeviceRow(device: d)
        }
        .buttonStyle(.plain)
        .listRowBackground(Color.clear)
        .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 6, trailing: 16))
        .swipeActions(edge: .trailing) {
            Button {
                Task { await model.locate(d) }
            } label: { Label("Orten", systemImage: "location.magnifyingglass") }
            .tint(.blue)
        }
        .contextMenu {
            Button { Task { await model.locate(d) } } label: {
                Label("Jetzt orten", systemImage: "location.magnifyingglass")
            }
            Button {
                Haptics.light()
                Task { try? await model.patchDevice(d.id, ["enabled": !d.enabled]) }
            } label: {
                Label(d.enabled ? "Abruf pausieren" : "Abruf fortsetzen",
                      systemImage: d.enabled ? "pause.circle" : "play.circle")
            }
        }
    }
}

struct DeviceRow: View {
    @Environment(AppModel.self) private var model
    let device: Device
    @State private var address: String?

    var body: some View {
        HStack(spacing: 14) {
            EmojiBadge(device: device, size: 50)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(device.name).font(.headline).lineLimit(1)
                    if device.net != .apple { tag(device.net.label.uppercased(), device.net.color) }
                    if device.lost.enabled { tag("VERLOREN", .red) }
                    if device.isGuarded { tag("WACHE", .orange) }
                    if !device.enabled { tag("PAUSE", .gray) }
                    let n = model.newCount(device.id)
                    if n > 0 { tag("+\(n) NEU", .purple) }
                }
                if let r = device.last {
                    HStack(spacing: 0) {
                        Text(address ?? "Standort wird ermittelt …")
                            .foregroundStyle(.secondary)
                        Text(" · ").foregroundStyle(.secondary).layoutPriority(1)
                        AgeText(date: r.date).fontWeight(.medium).layoutPriority(2)
                    }
                    .font(.subheadline)
                    .lineLimit(1)
                } else {
                    Text("Kein Standort gefunden").font(.subheadline).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 4) {
                if let r = device.last, let dist = model.distanceFromUser(r) {
                    Text(dist).font(.subheadline).foregroundStyle(.secondary)
                }
                if device.battery != nil { BatteryView(level: device.battery).font(.footnote) }
            }
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
        .task(id: device.last?.id) {
            if let r = device.last { address = await model.address(for: r) }
        }
    }

    private func tag(_ s: String, _ c: Color) -> some View {
        Text(s).font(.system(size: 9, weight: .heavy)).padding(.horizontal, 5).padding(.vertical, 2)
            .background(c, in: .capsule).foregroundStyle(.white)
    }
}

/// Gemeinsamer Import (Picker & Zwischenablage).
@MainActor
enum KeyImporter {
    static func importFiles(_ urls: [URL], model: AppModel) async -> String {
        var files: [(name: String, data: Data)] = []
        for u in urls {
            let ok = u.startAccessingSecurityScopedResource()
            defer { if ok { u.stopAccessingSecurityScopedResource() } }
            if let d = try? Data(contentsOf: u) { files.append((u.lastPathComponent, d)) }
        }
        guard !files.isEmpty else { return "❌ Datei konnte nicht gelesen werden" }
        return await upload(files, model: model)
    }

    static func upload(_ files: [(name: String, data: Data)], model: AppModel) async -> String {
        guard let api = model.api else { return "" }
        do {
            let r = try await api.upload(files: files)
            let added = (r.added ?? []).map { "✅ \($0.name)\($0.new ? "" : " (aktualisiert)")" }
            let failed = (r.errors ?? []).map { "❌ \($0.file): \($0.error)" }
            await model.reloadDevices()
            if !added.isEmpty {
                Haptics.success()
                model.showToast("\(added.count) Objekt(e) importiert")
            } else {
                Haptics.warning()
            }
            return (added + failed).joined(separator: "\n")
        } catch {
            Haptics.warning()
            return "❌ \(error.localizedDescription)"
        }
    }
}

/// Aufklappbare Info: neue Standorte seit dem letzten Öffnen der App.
struct NewSinceCard: View {
    @Environment(AppModel.self) private var model
    let info: NewSince
    @State private var expanded = false

    var body: some View {
        DisclosureGroup(isExpanded: $expanded.animation(.spring(duration: 0.35))) {
            VStack(spacing: 8) {
                ForEach(info.devices.sorted { $0.n > $1.n }, id: \.deviceId) { item in
                    if let d = model.device(item.deviceId) {
                        Button { model.openDevice(d.id) } label: {
                            HStack(spacing: 10) {
                                EmojiBadge(device: d, size: 32)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(d.name).font(.subheadline.weight(.semibold)).lineLimit(1)
                                    HStack(spacing: 4) {
                                        if let t = item.newest { AgeText(date: Date(timeIntervalSince1970: t)) }
                                        if (item.batches ?? 0) > 0 { Text("· \(item.batches ?? 0) Batch").foregroundStyle(.secondary) }
                                        if (item.late ?? 0) > 0 { Text("· \(item.late ?? 0) nachgereicht").foregroundStyle(.secondary) }
                                    }
                                    .font(.caption)
                                }
                                Spacer()
                                Text("+\(item.n)")
                                    .font(.subheadline.bold().monospacedDigit())
                                    .padding(.horizontal, 10).padding(.vertical, 4)
                                    .background(Color.purple.opacity(0.18), in: .capsule)
                                    .foregroundStyle(.purple)
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                Button("Als gesehen markieren") { model.markAllSeen() }
                    .buttonStyle(.glass)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .padding(.top, 4)
            }
            .padding(.top, 8)
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "sparkles")
                    .font(.headline).foregroundStyle(.black)
                    .frame(width: 32, height: 32).background(Color.yellow, in: .circle)
                VStack(alignment: .leading, spacing: 1) {
                    Text("\(info.total) neue Standorte").font(.headline)
                    Text("seit \(findMyTime(Date(timeIntervalSince1970: info.since)).text.replacingOccurrences(of: "Vor", with: "vor")) · \(info.devices.count) Objekt(e)")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .tint(.primary)
        .onChange(of: expanded) { _, _ in Haptics.light() }
    }
}
