import UIKit
import SwiftUI
import MapKit
import CoreImage.CIFilterBuiltins

// MARK: - Haptik

@MainActor
enum Haptics {
    static func selection() { UISelectionFeedbackGenerator().selectionChanged() }
    static func light() { UIImpactFeedbackGenerator(style: .light).impactOccurred(intensity: 0.8) }
    static func soft() { UIImpactFeedbackGenerator(style: .soft).impactOccurred(intensity: 0.9) }
    static func rigid() { UIImpactFeedbackGenerator(style: .rigid).impactOccurred(intensity: 0.6) }
    static func success() { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    static func warning() { UINotificationFeedbackGenerator().notificationOccurred(.warning) }
}

// MARK: - Zeitraum

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

// MARK: - Zeit wie in „Wo ist?“

func findMyTime(_ date: Date) -> (text: String, old: Bool) {
    let s = -date.timeIntervalSinceNow
    let de = Locale(identifier: "de_DE")
    let hm = date.formatted(.dateTime.hour(.twoDigits(amPM: .omitted)).minute(.twoDigits).locale(de))
    let cal = Calendar.current
    let text: String
    if s < 60 { text = "Gerade eben" }
    else if s < 3600 { text = "Vor \(Int(s / 60)) Min." }
    else if cal.isDateInToday(date) { text = "Heute um \(hm)" }
    else if cal.isDateInYesterday(date) { text = "Gestern um \(hm)" }
    else if s < 6 * 86400 { text = "\(date.formatted(.dateTime.weekday(.wide).locale(de))) um \(hm)" }
    else { text = "\(date.formatted(.dateTime.day(.twoDigits).month(.twoDigits).year(.twoDigits).locale(de))) um \(hm)" }
    return (text, s > 6 * 3600)
}

/// Farbe der Zeitangabe: < 1 min lila, < 15 min grün, < 1 h gelb, älter rot.
func ageColor(_ date: Date) -> Color {
    let s = -date.timeIntervalSinceNow
    if s < 60 { return .purple }
    if s < 15 * 60 { return .green }
    if s < 3600 { return .yellow }
    return .red
}

/// Zeitangabe, die sich jede Sekunde selbst aktualisiert (Text + Farbe).
struct AgeText: View {
    let date: Date
    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { _ in
            Text(findMyTime(date).text)
                .foregroundStyle(ageColor(date))
                .contentTransition(.numericText())
        }
    }
}

// MARK: - Objekt-Symbol

struct DeviceGlyph: View {
    let device: Device
    var size: CGFloat
    var body: some View {
        if let e = device.emoji, !e.isEmpty, e != "📍" {
            Text(e).font(.system(size: size))
        } else if device.net == .apple {
            Image(systemName: "airtag.fill")
                .font(.system(size: size * 0.85, weight: .regular))
                .foregroundStyle(.white, Color(.systemGray3))
        } else {
            Image(systemName: device.net.trackerSymbol)
                .font(.system(size: size * 0.72, weight: .medium))
                .foregroundStyle(device.net.color.gradient)
        }
    }
}

/// Runder Kreis mit Emoji, wie die Liste in „Wo ist?“.
struct EmojiBadge: View {
    let device: Device
    var size: CGFloat = 46
    var body: some View {
        DeviceGlyph(device: device, size: size * 0.52)
            .frame(width: size, height: size)
            .background(Color(.tertiarySystemFill), in: .circle)
            .overlay(alignment: .bottomTrailing) {
                if device.lost.enabled {
                    Image(systemName: "exclamationmark.circle.fill")
                        .font(.system(size: size * 0.34)).foregroundStyle(.white, .red)
                        .background(Circle().fill(Color(.systemBackground)).padding(1))
                } else if device.isGuarded {
                    Image(systemName: "lock.shield.fill")
                        .font(.system(size: size * 0.3)).foregroundStyle(.white, .orange)
                } else if device.net != .apple {
                    NetworkBadge(network: device.net, size: size * 0.36)
                }
            }
    }
}

/// Kleines Netz-Abzeichen (G / S) wie ein App-Badge.
struct NetworkBadge: View {
    let network: TrackerNetwork
    var size: CGFloat = 16
    var body: some View {
        Image(systemName: network.symbol)
            .font(.system(size: size * 0.78, weight: .bold))
            .foregroundStyle(.white, network.color)
            .frame(width: size, height: size)
            .background(Circle().fill(network == .apple ? Color(.label) : network.color))
            .overlay(Circle().stroke(Color(.systemBackground), lineWidth: max(1, size * 0.1)))
            .accessibilityLabel(network.longLabel)
    }
}

/// Netz-Etikett für Kopfzeilen („Google Find Hub“).
struct NetworkTag: View {
    let network: TrackerNetwork
    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: network.symbol)
            Text(network.longLabel)
        }
        .font(.caption.weight(.semibold))
        .foregroundStyle(network == .apple ? Color.secondary : network.color)
        .padding(.horizontal, 8).padding(.vertical, 3)
        .background((network == .apple ? Color.secondary : network.color).opacity(0.14), in: .capsule)
    }
}

// MARK: - AirTag-Pin auf der Karte (wie „Wo ist?“)

struct PinTail: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: r.minX, y: r.minY))
        p.addQuadCurve(to: CGPoint(x: r.midX, y: r.maxY), control: CGPoint(x: r.midX - r.width * 0.12, y: r.minY + r.height * 0.4))
        p.addQuadCurve(to: CGPoint(x: r.maxX, y: r.minY), control: CGPoint(x: r.midX + r.width * 0.12, y: r.minY + r.height * 0.4))
        p.closeSubpath()
        return p
    }
}

struct AirTagPin: View {
    let device: Device
    var selected: Bool = false
    var stale: Bool = false
    @State private var pulse = false

    var body: some View {
        let bubble: CGFloat = selected ? 62 : 50
        VStack(spacing: 0) {
            ZStack {
                if device.lost.enabled || device.isGuarded {
                    Circle()
                        .stroke(device.lost.enabled ? Color.red : Color.orange, lineWidth: 3)
                        .frame(width: bubble, height: bubble)
                        .scaleEffect(pulse ? 1.6 : 1)
                        .opacity(pulse ? 0 : 0.9)
                        .animation(.easeOut(duration: 1.6).repeatForever(autoreverses: false), value: pulse)
                        .onAppear { pulse = true }
                }
                Circle()
                    .fill(Color(.secondarySystemGroupedBackground))
                    .frame(width: bubble, height: bubble)
                    .overlay(Circle().stroke(device.lost.enabled ? Color.red : Color.white.opacity(0.12), lineWidth: device.lost.enabled ? 3 : 1))
                DeviceGlyph(device: device, size: bubble * 0.5)
                    .opacity(stale ? 0.75 : 1)
                if device.net != .apple {
                    NetworkBadge(network: device.net, size: selected ? 20 : 17)
                        .offset(x: bubble * 0.36, y: bubble * 0.36)
                }
            }
            PinTail()
                .fill(Color(.secondarySystemGroupedBackground))
                .frame(width: 16, height: 10)
                .offset(y: -1.5)
            Circle()
                .fill(Color.white)
                .frame(width: 9, height: 9)
                .overlay(Circle().stroke(device.tint, lineWidth: 3))
                .padding(.top, 3)
        }
        .compositingGroup()
        .shadow(color: .black.opacity(0.3), radius: 8, y: 4)
        .animation(.spring(duration: 0.35, bounce: 0.35), value: selected)
    }
}

/// Gelbes Etikett mit Aufenthaltsdauer auf der Karte.
struct StayLabel: View {
    let stay: Stay
    let selected: Bool
    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: stay.ongoing ? "figure.stand" : "clock.fill")
            Text(formatDuration(stay.duration))
        }
        .font(.system(size: selected ? 13 : 11, weight: .bold))
        .foregroundStyle(.black)
        .padding(.horizontal, 8).padding(.vertical, 4)
        .background(Color.yellow, in: .capsule)
        .overlay(Capsule().stroke(.white, lineWidth: selected ? 2.5 : 1.5))
        .shadow(color: .black.opacity(0.3), radius: 3, y: 1)
        .offset(y: -18)
        .animation(.spring(duration: 0.25), value: selected)
    }
}

/// Großer, gut sichtbarer Verlaufspunkt.
struct HistoryDot: View {
    let color: Color
    let progress: Double
    let selected: Bool
    var body: some View {
        Circle()
            .fill(color.opacity(0.35 + 0.65 * progress))
            .frame(width: selected ? 22 : 14, height: selected ? 22 : 14)
            .overlay(Circle().stroke(.white, lineWidth: selected ? 3.5 : 2))
            .shadow(color: .black.opacity(0.25), radius: 2, y: 1)
            .contentShape(Circle().inset(by: -8))
            .animation(.spring(duration: 0.25), value: selected)
    }
}

// MARK: - Status

struct LiveDot: View {
    let on: Bool
    @State private var anim = false
    var body: some View {
        Circle()
            .fill(on ? Color.green : Color.orange)
            .frame(width: 8, height: 8)
            .overlay(Circle().stroke(on ? Color.green : .clear, lineWidth: 2).scaleEffect(anim ? 2.4 : 1).opacity(anim ? 0 : 0.8))
            .onAppear { withAnimation(.easeOut(duration: 1.5).repeatForever(autoreverses: false)) { anim = true } }
    }
}

struct StatusPill: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        HStack(spacing: 8) {
            if model.isRefreshing || model.status?.polling == true {
                ProgressView().controlSize(.mini)
            } else {
                LiveDot(on: model.liveConnected)
            }
            VStack(alignment: .leading, spacing: 0) {
                Text(model.isRefreshing ? "Suche …" : (model.liveConnected ? "Live" : "Offline")).font(.caption.bold())
                if let lp = model.status?.lastPoll {
                    Text("Abruf \(Date(timeIntervalSince1970: lp).relativeDE)").font(.caption2).foregroundStyle(.secondary)
                } else if model.status?.apple.isLoggedIn == false {
                    Text("Apple-Login fehlt").font(.caption2).foregroundStyle(.orange)
                }
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .glassEffect(.regular, in: .capsule)
    }
}

struct ToastView: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.footnote.weight(.semibold))
            .lineLimit(2)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 16).padding(.vertical, 9)
            .frame(maxWidth: 320)
            .glassEffect(.regular, in: .capsule)
            .transition(.move(edge: .top).combined(with: .opacity))
    }
}

struct BatteryView: View {
    let level: String?
    var body: some View {
        Image(systemName: BatteryLevel.icon(level))
            .symbolRenderingMode(.hierarchical)
            .foregroundStyle(BatteryLevel.color(level))
            .accessibilityLabel("Batterie \(BatteryLevel.label(level))")
    }
}

struct LevelPicker: View {
    let title: String
    @Binding var level: String
    var body: some View {
        Picker(title, selection: $level) {
            ForEach(AlertLevel.allCases) { l in
                Label(l.label, systemImage: l.icon).tag(l.rawValue)
            }
        }
        .onChange(of: level) { _, _ in Haptics.selection() }
    }
}

struct QRCodeView: View {
    let text: String
    var body: some View {
        if let img = Self.make(text) {
            Image(uiImage: img).interpolation(.none).resizable().scaledToFit()
        } else {
            Image(systemName: "qrcode")
        }
    }

    static func make(_ s: String) -> UIImage? {
        let f = CIFilter.qrCodeGenerator()
        f.message = Data(s.utf8)
        f.correctionLevel = "M"
        guard let out = f.outputImage?.transformed(by: .init(scaleX: 10, y: 10)),
              let cg = CIContext().createCGImage(out, from: out.extent) else { return nil }
        return UIImage(cgImage: cg)
    }
}

/// Karte im Stil der „Wo ist?“-Aktionskacheln.
struct ActionTile: View {
    let title: String
    let subtitle: String?
    let icon: String
    let color: Color
    var active: Bool = false
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 34, height: 34)
                .background(active ? color : color.opacity(0.9), in: .circle)
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.headline).foregroundStyle(.primary).lineLimit(1)
                if let subtitle {
                    Text(subtitle).font(.subheadline).foregroundStyle(active ? color : .secondary).lineLimit(1)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color(.secondarySystemGroupedBackground).opacity(0.7), in: .rect(cornerRadius: 22))
        .overlay(RoundedRectangle(cornerRadius: 22).stroke(active ? color.opacity(0.6) : .clear, lineWidth: 1.5))
        .contentShape(.rect(cornerRadius: 22))
    }
}

struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .animation(.spring(duration: 0.2), value: configuration.isPressed)
    }
}

// MARK: - Karte

enum MapStyleChoice: String, CaseIterable, Identifiable {
    case standard, hybrid, imagery
    var id: String { rawValue }
    var style: MapStyle {
        switch self {
        case .standard: .standard(elevation: .realistic, pointsOfInterest: .including([.publicTransport, .parking, .store, .restaurant, .cafe]))
        case .hybrid: .hybrid(elevation: .realistic)
        case .imagery: .imagery(elevation: .realistic)
        }
    }
    var label: String {
        switch self {
        case .standard: "Standard"
        case .hybrid: "Hybrid"
        case .imagery: "Satellit"
        }
    }
    var icon: String {
        switch self {
        case .standard: "map"
        case .hybrid: "map.fill"
        case .imagery: "globe.europe.africa.fill"
        }
    }
}

func region(fitting coords: [CLLocationCoordinate2D], padding: Double = 1.5, minSpan: Double = 0.004) -> MKCoordinateRegion? {
    guard let first = coords.first else { return nil }
    var minLat = first.latitude, maxLat = first.latitude, minLon = first.longitude, maxLon = first.longitude
    for c in coords {
        minLat = min(minLat, c.latitude); maxLat = max(maxLat, c.latitude)
        minLon = min(minLon, c.longitude); maxLon = max(maxLon, c.longitude)
    }
    let center = CLLocationCoordinate2D(latitude: (minLat + maxLat) / 2, longitude: (minLon + maxLon) / 2)
    let span = MKCoordinateSpan(latitudeDelta: max((maxLat - minLat) * padding, minSpan),
                                longitudeDelta: max((maxLon - minLon) * padding, minSpan))
    return MKCoordinateRegion(center: center, span: span)
}

func appleMapsURL(_ r: Report, name: String, directions: Bool = false) -> URL? {
    let q = name.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
    return URL(string: directions
               ? "https://maps.apple.com/?daddr=\(r.lat),\(r.lon)&q=\(q)"
               : "https://maps.apple.com/?ll=\(r.lat),\(r.lon)&q=\(q)")
}

@MainActor
struct LocationPermission {
    static let manager: CLLocationManager = {
        let m = CLLocationManager()
        m.desiredAccuracy = kCLLocationAccuracyHundredMeters
        return m
    }()
    static func request() {
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
        manager.startUpdatingLocation()
    }
}

// MARK: - Glas-Karte

struct GlassSection<Content: View>: View {
    var title: String?
    var systemImage: String?
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title {
                Label(title, systemImage: systemImage ?? "circle").font(.headline)
            }
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground).opacity(0.7), in: .rect(cornerRadius: 22))
    }
}
