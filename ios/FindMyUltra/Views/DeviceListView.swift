import SwiftUI

struct DeviceListView: View {
    @Environment(AppModel.self) private var model
    @State private var importing = false
    @State private var importMessage: String?

    var body: some View {
        List {
            Section {
                ForEach(model.devices) { d in
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
                            Task { await model.refresh(deviceID: d.id) }
                        } label: { Label("Orten", systemImage: "location.magnifyingglass") }
                        .tint(.blue)
                    }
                    .contextMenu {
                        Button { Task { await model.refresh(deviceID: d.id) } } label: {
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
            } header: {
                HStack(alignment: .firstTextBaseline) {
                    Text("Meine Objekte")
                    Spacer()
                    if let s = model.status {
                        Text("\(s.stats.total) Standorte · \(s.stats.today) heute")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .textCase(nil)
            }

            if model.devices.isEmpty {
                ContentUnavailableView {
                    Label("Keine Objekte", systemImage: "airtag")
                } description: {
                    Text("Importiere die JSON- oder plist-Schlüssel deiner AirTags.")
                } actions: {
                    Button("Schlüssel importieren") { importing = true }.buttonStyle(.glassProminent)
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
                    if device.lost.enabled { tag("VERLOREN", .red) }
                    if device.isGuarded { tag("WACHE", .orange) }
                    if !device.enabled { tag("PAUSE", .gray) }
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
