import UIKit
import SwiftUI
import MapKit
import CoreImage.CIFilterBuiltins

// MARK: - Marker

struct DeviceMarker: View {
    let device: Device
    var selected: Bool = false
    @State private var pulse = false

    var body: some View {
        ZStack {
            if device.lost.enabled || device.isGuarded {
                Circle()
                    .stroke(device.lost.enabled ? Color.red : Color.orange, lineWidth: 3)
                    .frame(width: 54, height: 54)
                    .scaleEffect(pulse ? 1.5 : 0.9)
                    .opacity(pulse ? 0 : 0.9)
                    .animation(.easeOut(duration: 1.6).repeatForever(autoreverses: false), value: pulse)
                    .onAppear { pulse = true }
            }
            Text(device.symbol)
                .font(.system(size: selected ? 26 : 21))
                .frame(width: selected ? 52 : 42, height: selected ? 52 : 42)
                .background(device.tint.gradient, in: .circle)
                .overlay(Circle().stroke(.white, lineWidth: 3))
                .shadow(color: .black.opacity(0.35), radius: 6, y: 3)
        }
        .animation(.spring(duration: 0.35), value: selected)
    }
}

struct EmojiBadge: View {
    let device: Device
    var size: CGFloat = 46
    var body: some View {
        Text(device.symbol)
            .font(.system(size: size * 0.5))
            .frame(width: size, height: size)
            .background(device.tint.opacity(0.25).gradient, in: .circle)
            .overlay(alignment: .bottomTrailing) {
                if device.lost.enabled {
                    Image(systemName: "exclamationmark.circle.fill")
                        .font(.system(size: size * 0.32)).foregroundStyle(.white, .red)
                } else if device.isGuarded {
                    Image(systemName: "shield.lefthalf.filled")
                        .font(.system(size: size * 0.3)).foregroundStyle(.orange)
                }
            }
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
                Text(model.liveConnected ? "Live" : "Offline").font(.caption.bold())
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
            .font(.subheadline.weight(.semibold))
            .padding(.horizontal, 18).padding(.vertical, 12)
            .glassEffect(.regular, in: .capsule)
            .transition(.move(edge: .top).combined(with: .opacity))
    }
}

struct BatteryView: View {
    let level: String?
    var body: some View {
        Image(systemName: BatteryLevel.icon(level))
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

// MARK: - Karte

enum MapStyleChoice: String, CaseIterable, Identifiable {
    case standard, hybrid, imagery
    var id: String { rawValue }
    var style: MapStyle {
        switch self {
        case .standard: .standard(elevation: .realistic, pointsOfInterest: .excludingAll)
        case .hybrid: .hybrid(elevation: .realistic)
        case .imagery: .imagery(elevation: .realistic)
        }
    }
    var icon: String {
        switch self {
        case .standard: "map"
        case .hybrid: "map.fill"
        case .imagery: "globe.europe.africa.fill"
        }
    }
    var next: MapStyleChoice {
        switch self {
        case .standard: .hybrid
        case .hybrid: .imagery
        case .imagery: .standard
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

struct LocationPermission {
    static let manager = CLLocationManager()
    static func request() {
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
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
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassEffect(.regular, in: .rect(cornerRadius: 26))
    }
}
