import SwiftUI
import MapKit

enum MapSel: Hashable {
    case device(String)
    case report(Int)
    case stay(String)
    case apple(String)
}

struct Pin: Identifiable {
    let device: Device
    let report: Report
    var id: String { device.id }
}

/// Vollbild-Karte mit dauerhaftem Sheet – Aufbau wie Apples „Wo ist?“.
struct MapScreen: View {
    @Environment(AppModel.self) private var model
    @Namespace private var mapScope

    @State private var position: MapCameraPosition = .automatic
    @State private var style: MapStyleChoice = MapStyleChoice(rawValue: UserDefaults.standard.string(forKey: "mapStyle") ?? "") ?? .standard
    @State private var fitted = false
    @State private var showStyleMenu = false

    private var pins: [Pin] {
        model.items.compactMap { d in d.last.map { Pin(device: d, report: $0) } }
    }

    private var focused: Device? { model.focusedID.flatMap { model.device($0) } }

    /// Für die Karte ausgedünnte Verlaufspunkte (max. ~600), Auswahl bleibt immer enthalten.
    private var dots: [(index: Int, report: Report)] {
        let t = model.track
        guard !t.isEmpty else { return [] }
        let step = max(1, t.count / 600)
        var idx = Set(stride(from: 0, to: t.count, by: step))
        idx.insert(t.count - 1)
        if let c = model.cursor { idx.insert(c) }
        return idx.sorted().map { ($0, t[$0]) }
    }

    var body: some View {
        @Bindable var model = model
        mapView
            .mapStyle(style.style)
            .mapControls {
                MapCompass(scope: mapScope)
                MapScaleView(scope: mapScope)
            }
            .mapScope(mapScope)
            .ignoresSafeArea()
            .overlay(alignment: .topLeading) {
                StatusPill().padding(.leading, 16).padding(.top, 4)
            }
            .overlay(alignment: .topTrailing) { controls.padding(.trailing, 14).padding(.top, 4) }
            .sheet(isPresented: .constant(true)) {
                FindSheet()
                    .environment(model)
                    .presentationDetents([.peek, .medium, .large], selection: $model.detent)
                    .presentationBackgroundInteraction(.enabled(upThrough: .medium))
                    .presentationDragIndicator(.visible)
                    .interactiveDismissDisabled()
                    .presentationContentInteraction(.scrolls)
            }
            .onAppear {
                LocationPermission.request()
                fitIfNeeded()
            }
            .onChange(of: model.devices) { _, _ in fitIfNeeded() }
            .onChange(of: model.cameraTick) { _, _ in
                if let r = model.cameraRegion {
                    withAnimation(.smooth(duration: 0.75)) { position = .region(r) }
                }
            }
            .onChange(of: model.cursor) { _, _ in
                guard model.historyVisible, model.followCursor, let r = model.cursorReport else { return }
                model.show(center: r.coordinate, meters: max(500, Double(r.accuracy ?? 0) * 8))
            }
            .onChange(of: model.detent) { _, _ in Haptics.light() }
            .sensoryFeedback(.impact(weight: .light), trigger: model.isRefreshing)
    }

    // MARK: Karte

    private var mapView: some View {
        let selection = Binding<MapSel?>(
            get: { nil },
            set: { sel in
                switch sel {
                case .device(let id): model.openDevice(id)
                case .report(let rid): model.select(reportID: rid)
                case .stay(let sid): if let st = model.stays.first(where: { $0.id == sid }) { model.select(stay: st) }
                case .apple(let aid): model.openApple(aid)
                case nil: break
                }
            }
        )
        return Map(position: $position, selection: selection, scope: mapScope) {
            UserAnnotation()

            ForEach(model.settings?.zones ?? []) { z in
                MapCircle(center: z.coordinate, radius: z.radius)
                    .foregroundStyle(.blue.opacity(0.07))
                    .stroke(.blue.opacity(0.45), lineWidth: 1)
            }

            // Wache-Radius
            if let d = focused, d.isGuarded, let gl = d.alerts.guardMode.lat, let gn = d.alerts.guardMode.lon {
                MapCircle(center: .init(latitude: gl, longitude: gn), radius: d.alerts.guardMode.radiusM)
                    .foregroundStyle(.orange.opacity(0.08))
                    .stroke(.orange, style: StrokeStyle(lineWidth: 2, dash: [6, 4]))
            }

            // Verlauf nur, wenn eingeblendet
            if let tint = model.trackTint, model.historyVisible {
                // Aufenthalte (gelb)
                if model.showStays {
                    ForEach(model.stays) { st in
                        MapCircle(center: st.coordinate, radius: st.radius)
                            .foregroundStyle(Color.yellow.opacity(st.id == model.selectedStayID ? 0.32 : 0.2))
                            .stroke(Color.yellow, lineWidth: st.id == model.selectedStayID ? 3 : 2)
                    }
                }
                // Genauigkeitskreise (blau)
                if model.circleMode == .all {
                    ForEach(dots, id: \.report.id) { item in
                        MapCircle(center: item.report.coordinate, radius: CLLocationDistance(max(item.report.accuracy ?? 5, 5)))
                            .foregroundStyle(Color.blue.opacity(0.06))
                            .stroke(Color.blue.opacity(0.4), lineWidth: 0.8)
                    }
                }
                if model.circleMode != .off, let r = model.cursorReport {
                    MapCircle(center: r.coordinate, radius: CLLocationDistance(max(r.accuracy ?? 5, 5)))
                        .foregroundStyle(Color.blue.opacity(0.16))
                        .stroke(Color.blue, lineWidth: 1.5)
                }
                // Spur
                if model.track.count > 1 {
                    MapPolyline(coordinates: model.track.map(\.coordinate))
                        .stroke(tint.opacity(0.7), style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
                }
                // Punkte (antippbar)
                ForEach(dots, id: \.report.id) { item in
                    Annotation("", coordinate: item.report.coordinate, anchor: .center) {
                        HistoryDot(color: item.report.isOnline ? Color.green : tint,
                                   progress: Double(item.index) / Double(max(model.track.count - 1, 1)),
                                   selected: item.index == model.cursor)
                    }
                    .tag(MapSel.report(item.report.id))
                    .annotationTitles(.hidden)
                }
                // Aufenthalts-Etiketten (antippbar)
                if model.showStays {
                    ForEach(model.stays) { st in
                        Annotation("", coordinate: st.coordinate, anchor: .center) {
                            StayLabel(stay: st, selected: st.id == model.selectedStayID)
                        }
                        .tag(MapSel.stay(st.id))
                        .annotationTitles(.hidden)
                    }
                }
            }

            // Apple-Geräte (bester Standort: online oder offline)
            if model.showAppleOnMap {
                ForEach(model.appleDevices.filter { $0.best != nil }) { a in
                    if let b = a.best {
                        if model.circleMode != .off {
                            MapCircle(center: b.coordinate, radius: CLLocationDistance(max(b.accuracy ?? 5, 5)))
                                .foregroundStyle(Color.blue.opacity(0.1))
                                .stroke(Color.blue.opacity(0.45), lineWidth: 1)
                        }
                        Annotation(a.name, coordinate: b.coordinate, anchor: .bottom) {
                            ApplePin(device: a, selected: a.id == model.focusedAppleID)
                        }
                        .tag(MapSel.apple(a.id))
                        .annotationTitles(a.id == model.focusedAppleID ? .visible : .automatic)
                    }
                }
            }
            // AirPods/Teile des ausgewählten Geräts einzeln (links/rechts/Case/online)
            if let a = model.focusedAppleID.flatMap({ model.appleDevice($0) }) {
                ForEach(a.parts.filter { $0.last != nil && !(a.best?.role == $0.role && a.best?.isOnline == false) }) { p in
                    if let l = p.last, let role = PartRole(rawValue: p.role) {
                        Annotation(role.short, coordinate: l.coordinate, anchor: .bottom) {
                            ApplePin(device: a, selected: false, symbolOverride: role == .main ? nil : role.symbol,
                                     label: role == .main ? "OFF" : role.short.uppercased())
                                .scaleEffect(0.8, anchor: .bottom)
                        }
                    }
                }
                if let o = a.online, a.best?.isOnline == false {
                    Annotation("Online", coordinate: o.coordinate, anchor: .bottom) {
                        ApplePin(device: a, selected: false, label: "ON").scaleEffect(0.8, anchor: .bottom)
                    }
                }
            }

            // Objekte (AirTag-Pins)
            ForEach(pins) { p in
                if model.circleMode != .off && (p.device.id != model.focusedID || !model.historyVisible) {
                    MapCircle(center: p.report.coordinate, radius: CLLocationDistance(max(p.report.accuracy ?? 5, 5)))
                        .foregroundStyle(Color.blue.opacity(0.1))
                        .stroke(Color.blue.opacity(0.45), lineWidth: 1)
                }
                Annotation(p.device.name, coordinate: p.report.coordinate, anchor: .bottom) {
                    AirTagPin(device: p.device,
                              selected: p.device.id == model.focusedID,
                              stale: findMyTime(p.report.date).old)
                }
                .tag(MapSel.device(p.device.id))
                .annotationTitles(p.device.id == model.focusedID ? .visible : .automatic)
            }
        }
    }

    // MARK: Bedienelemente (oben rechts, wie „Wo ist?“)

    private var controls: some View {
        VStack(spacing: 10) {
            VStack(spacing: 0) {
                Menu {
                    Picker("Karte", selection: $style) {
                        ForEach(MapStyleChoice.allCases) { s in
                            Label(s.label, systemImage: s.icon).tag(s)
                        }
                    }
                    Picker("Genauigkeitskreise", selection: Binding(get: { model.circleMode }, set: { model.circleMode = $0 })) {
                        ForEach(CircleMode.allCases) { Text("Kreise: \($0.label)").tag($0) }
                    }
                    Toggle("Apple-Geräte anzeigen", isOn: Binding(get: { model.showAppleOnMap }, set: { model.showAppleOnMap = $0; Haptics.light() }))
                    Toggle("Aufenthalte anzeigen", isOn: Binding(get: { model.showStays }, set: { model.showStays = $0; Haptics.light() }))
                } label: {
                    Image(systemName: style == .standard ? "map" : "map.fill")
                        .frame(width: 46, height: 44)
                        .contentShape(Rectangle())
                }
                Divider().frame(width: 28)
                Button {
                    Haptics.light()
                    if let c = LocationPermission.manager.location?.coordinate {
                        model.show(center: c, meters: 1200)
                    } else {
                        LocationPermission.request()
                    }
                } label: {
                    Image(systemName: "location")
                        .frame(width: 46, height: 44)
                        .contentShape(Rectangle())
                }
                Divider().frame(width: 28)
                Button {
                    Haptics.light()
                    if model.historyVisible, !model.track.isEmpty { model.fitTrack() }
                    else if let id = model.focusedID, let r = model.device(id)?.last { model.show(center: r.coordinate, meters: 900) }
                    else if let id = model.focusedAppleID, let b = model.appleDevice(id)?.best { model.show(center: b.coordinate, meters: 900) }
                    else { model.fitAll() }
                } label: {
                    Image(systemName: "scope")
                        .frame(width: 46, height: 44)
                        .contentShape(Rectangle())
                }
            }
            .glassEffect(.regular.interactive(), in: .capsule)

            Button {
                Task { await model.refresh(deviceID: model.focusedID) }
            } label: {
                Group {
                    if model.isRefreshing {
                        ProgressView()
                    } else {
                        Image(systemName: "arrow.clockwise")
                    }
                }
                .frame(width: 46, height: 46)
                .contentShape(Circle())
            }
            .glassEffect(.regular.interactive(), in: .circle)
            .disabled(model.isRefreshing)
        }
        .buttonStyle(.plain)
        .font(.system(size: 18, weight: .medium))
        .foregroundStyle(.primary)
        .onChange(of: style) { _, s in
            Haptics.selection()
            UserDefaults.standard.set(s.rawValue, forKey: "mapStyle")
        }
    }

    private func fitIfNeeded() {
        guard !fitted, !pins.isEmpty else { return }
        fitted = true
        model.fitAll()
    }
}
