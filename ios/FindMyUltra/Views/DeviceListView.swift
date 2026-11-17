import SwiftUI

struct DeviceListView: View {
    @Environment(AppModel.self) private var model
    @State private var search = ""

    private var filtered: [Device] {
        search.isEmpty ? model.devices : model.devices.filter { $0.name.localizedCaseInsensitiveContains(search) }
    }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                summary
                ForEach(filtered) { d in
                    NavigationLink(value: DeviceRoute(id: d.id)) { DeviceRow(device: d) }
                        .buttonStyle(.plain)
                        .contextMenu {
                            Button { Task { await model.refresh(deviceID: d.id) } } label: {
                                Label("Jetzt orten", systemImage: "location.magnifyingglass")
                            }
                            Button {
                                Task { try? await model.patchDevice(d.id, ["enabled": !d.enabled]) }
                            } label: {
                                Label(d.enabled ? "Abruf pausieren" : "Abruf fortsetzen",
                                      systemImage: d.enabled ? "pause.circle" : "play.circle")
                            }
                        }
                }
                if model.devices.isEmpty {
                    ContentUnavailableView("Keine Objekte",
                                           systemImage: "airtag",
                                           description: Text("Importiere die JSON-/plist-Schlüssel deiner AirTags unter Einstellungen → Schlüssel importieren."))
                        .padding(.top, 60)
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 24)
        }
        .navigationTitle("Objekte")
        .searchable(text: $search, prompt: "Suchen")
        .refreshable { await model.refresh() }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { Task { await model.refresh(full: true) } } label: {
                    Label("7-Tage-Scan", systemImage: "clock.arrow.2.circlepath")
                }
            }
        }
    }

    private var summary: some View {
        HStack(spacing: 10) {
            stat("\(model.status?.stats.total ?? 0)", "Standorte", "mappin.and.ellipse")
            stat("\(model.status?.stats.today ?? 0)", "heute", "sun.max")
            stat("\(model.status?.stats.batches ?? 0)", "Batches", "square.stack.3d.up")
        }
    }

    private func stat(_ v: String, _ l: String, _ icon: String) -> some View {
        VStack(spacing: 4) {
            Image(systemName: icon).foregroundStyle(.tint)
            Text(v).font(.title3.bold()).contentTransition(.numericText())
            Text(l).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
        .glassEffect(.regular, in: .rect(cornerRadius: 22))
    }
}

struct DeviceRow: View {
    @Environment(AppModel.self) private var model
    let device: Device
    @State private var address: String?

    var body: some View {
        HStack(spacing: 14) {
            EmojiBadge(device: device, size: 52)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(device.name).font(.headline).lineLimit(1)
                    if device.lost.enabled { tag("VERLOREN", .red) }
                    if device.isGuarded { tag("WACHE", .orange) }
                    if !device.enabled { tag("PAUSE", .gray) }
                }
                if let r = device.last {
                    Text(address ?? String(format: "%.5f, %.5f", r.lat, r.lon))
                        .font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                    Text("\(r.date.relativeDE) · ±\(r.accuracy ?? 0) m · \(device.total) Punkte")
                        .font(.caption).foregroundStyle(.tertiary)
                } else {
                    Text("Noch kein Standort").font(.subheadline).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
            VStack(spacing: 6) {
                BatteryView(level: device.battery)
                Image(systemName: "chevron.right").font(.footnote.bold()).foregroundStyle(.tertiary)
            }
        }
        .padding(14)
        .glassEffect(.regular.tint(device.lost.enabled ? .red.opacity(0.18) : .clear).interactive(),
                     in: .rect(cornerRadius: 26))
        .task(id: device.last?.id) {
            if let r = device.last { address = await model.address(for: r) }
        }
    }

    private func tag(_ s: String, _ c: Color) -> some View {
        Text(s).font(.system(size: 9, weight: .heavy)).padding(.horizontal, 5).padding(.vertical, 2)
            .background(c, in: .capsule).foregroundStyle(.white)
    }
}
