import SwiftUI
import MapKit

struct Pin: Identifiable {
    let device: Device
    let report: Report
    var id: String { device.id }
}

struct MapScreen: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @Namespace private var mapScope

    @State private var position: MapCameraPosition = .automatic
    @State private var selection: String?
    @State private var style: MapStyleChoice = .standard
    @State private var track: [Report] = []
    @State private var fitted = false
    @State private var address: String?

    private var pins: [Pin] {
        model.devices.compactMap { d in d.last.map { Pin(device: d, report: $0) } }
    }
    private var selected: Device? { selection.flatMap { model.device($0) } }

    var body: some View {
        Map(position: $position, selection: $selection, scope: mapScope) {
            UserAnnotation()
            ForEach(model.settings?.zones ?? []) { z in
                MapCircle(center: z.coordinate, radius: z.radius)
                    .foregroundStyle(.blue.opacity(0.08))
                    .stroke(.blue.opacity(0.5), lineWidth: 1)
            }
            if let d = selected, track.count > 1 {
                MapPolyline(coordinates: track.map(\.coordinate))
                    .stroke(d.tint.opacity(0.8), style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
            }
            ForEach(pins) { p in
                MapCircle(center: p.report.coordinate, radius: CLLocationDistance(max(p.report.accuracy ?? 5, 5)))
                    .foregroundStyle(p.device.tint.opacity(0.14))
                    .stroke(p.device.tint.opacity(0.5), lineWidth: 1)
                Annotation(p.device.name, coordinate: p.report.coordinate, anchor: .center) {
                    DeviceMarker(device: p.device, selected: selection == p.device.id)
                }
                .tag(p.device.id)
            }
        }
        .mapStyle(style.style)
        .mapControls {
            MapCompass(scope: mapScope)
            MapScaleView(scope: mapScope)
        }
        .mapScope(mapScope)
        .ignoresSafeArea(edges: .top)
        .overlay(alignment: .topLeading) {
            StatusPill().padding(.leading, 16).padding(.top, 8)
        }
        .overlay(alignment: .topTrailing) { controls.padding(.trailing, 16).padding(.top, 8) }
        .safeAreaInset(edge: .bottom) { bottom.padding(.horizontal, 12).padding(.bottom, 6) }
        .toolbar(.hidden, for: .navigationBar)
        .onAppear {
            LocationPermission.request()
            fitIfNeeded()
        }
        .onChange(of: model.devices) { _, _ in
            fitIfNeeded()
            if let id = selection { track = model.history[id] ?? track }
        }
        .onChange(of: selection) { _, id in
            address = nil
            track = []
            guard let id, let d = model.device(id) else { return }
            if let r = d.last {
                withAnimation(.smooth(duration: 0.8)) {
                    position = .region(MKCoordinateRegion(center: r.coordinate, latitudinalMeters: 900, longitudinalMeters: 900))
                }
            }
            Task {
                track = (try? await model.loadHistory(id, since: Date().timeIntervalSince1970 - 86400)) ?? []
                if let r = d.last { address = await model.address(for: r) }
            }
        }
        .sensoryFeedback(.selection, trigger: selection)
    }

    private var controls: some View {
        GlassEffectContainer(spacing: 8) {
            VStack(spacing: 8) {
                Button {
                    Task { await model.refresh() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .symbolEffect(.rotate, isActive: model.isRefreshing)
                        .frame(width: 44, height: 44)
                }
                .glassEffect(.regular.interactive(), in: .circle)
                Button { fitAll() } label: {
                    Image(systemName: "scope").frame(width: 44, height: 44)
                }
                .glassEffect(.regular.interactive(), in: .circle)
                Button { withAnimation { style = style.next } } label: {
                    Image(systemName: style.icon).frame(width: 44, height: 44)
                }
                .glassEffect(.regular.interactive(), in: .circle)
                MapUserLocationButton(scope: mapScope)
                    .frame(width: 44, height: 44)
                    .glassEffect(.regular.interactive(), in: .circle)
            }
            .buttonStyle(.plain)
            .font(.system(size: 17, weight: .semibold))
        }
    }

    @ViewBuilder
    private var bottom: some View {
        if let d = selected {
            selectedCard(d)
                .transition(.move(edge: .bottom).combined(with: .opacity))
        } else if !model.devices.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                GlassEffectContainer(spacing: 10) {
                    HStack(spacing: 10) {
                        ForEach(model.devices) { d in
                            Button { selection = d.id } label: {
                                HStack(spacing: 8) {
                                    Text(d.symbol)
                                    VStack(alignment: .leading, spacing: 0) {
                                        Text(d.name).font(.subheadline.bold()).lineLimit(1)
                                        Text(d.last.map { $0.date.relativeDE } ?? "kein Standort")
                                            .font(.caption2).foregroundStyle(.secondary)
                                    }
                                }
                                .padding(.horizontal, 14).padding(.vertical, 10)
                            }
                            .buttonStyle(.plain)
                            .glassEffect(.regular.tint(d.lost.enabled ? .red.opacity(0.35) : d.tint.opacity(0.18)).interactive(),
                                         in: .capsule)
                        }
                    }
                    .padding(.horizontal, 4)
                }
            }
        } else {
            Label("Noch keine Objekte – importiere Schlüssel in den Einstellungen.", systemImage: "tray")
                .font(.footnote).padding(14)
                .glassEffect(.regular, in: .capsule)
        }
    }

    private func selectedCard(_ d: Device) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                EmojiBadge(device: d, size: 50)
                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Text(d.name).font(.title3.bold()).lineLimit(1)
                        if d.lost.enabled {
                            Text("VERLOREN").font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 2)
                                .background(.red, in: .capsule).foregroundStyle(.white)
                        }
                    }
                    if let r = d.last {
                        Text("\(r.date.relativeDE) · ±\(r.accuracy ?? 0) m")
                            .font(.subheadline).foregroundStyle(.secondary)
                        if let address { Text(address).font(.footnote).foregroundStyle(.secondary).lineLimit(1) }
                    } else {
                        Text("Noch kein Standort").font(.subheadline).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                BatteryView(level: d.battery)
                Button { withAnimation { selection = nil } } label: {
                    Image(systemName: "xmark").font(.footnote.bold()).frame(width: 30, height: 30)
                }
                .buttonStyle(.plain)
                .glassEffect(.regular.interactive(), in: .circle)
            }
            GlassEffectContainer(spacing: 8) {
                HStack(spacing: 8) {
                    Button {
                        Task { await model.refresh(deviceID: d.id) }
                    } label: {
                        Label("Orten", systemImage: "location.magnifyingglass").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.glass)
                    Button {
                        if let r = d.last, let u = appleMapsURL(r, name: d.name, directions: true) { openURL(u) }
                    } label: {
                        Label("Route", systemImage: "car.fill").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.glass)
                    .disabled(d.last == nil)
                    NavigationLink(value: DeviceRoute(id: d.id)) {
                        Label("Verlauf", systemImage: "clock.arrow.circlepath").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.glassProminent)
                }
                .labelStyle(.titleAndIcon)
                .font(.subheadline.weight(.semibold))
            }
        }
        .padding(16)
        .glassEffect(.regular, in: .rect(cornerRadius: 30))
    }

    private func fitIfNeeded() {
        guard !fitted, !pins.isEmpty else { return }
        fitted = true
        fitAll()
    }

    private func fitAll() {
        selection = nil
        if let r = region(fitting: pins.map(\.report.coordinate), padding: 1.8) {
            withAnimation(.smooth(duration: 0.8)) { position = .region(r) }
        }
    }
}
