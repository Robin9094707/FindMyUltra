import Foundation
import CoreLocation
import SwiftUI

// MARK: - Berichte & Geräte

struct Report: Codable, Identifiable, Hashable {
    let id: Int
    let deviceId: String
    let ts: Double
    let lat: Double
    let lon: Double
    let accuracy: Int?
    let confidence: Int?
    let status: Int?
    let battery: String?
    let receivedAt: Double
    let batchId: String?
    let batchSize: Int?
    let late: Int
    // nur bei Aufzeichnungen von Apple-Geräten
    var source: String? = nil
    var role: String? = nil
    var positionType: String? = nil
    var batteryLevel: Double? = nil

    var isOnline: Bool { source == "online" }

    var date: Date { Date(timeIntervalSince1970: ts) }
    var receivedDate: Date { Date(timeIntervalSince1970: receivedAt) }
    var coordinate: CLLocationCoordinate2D { .init(latitude: lat, longitude: lon) }
    var delayMinutes: Int { max(0, Int((receivedAt - ts) / 60)) }
    var isLate: Bool { late != 0 }
    var isBatch: Bool { (batchSize ?? 1) > 1 && !(batchId ?? "").hasPrefix("init-") }
}

struct NewReportAlert: Codable, Hashable { var enabled: Bool; var level: String; var minIntervalMin: Double }
struct MovementAlert: Codable, Hashable { var enabled: Bool; var distanceM: Double; var windowMin: Double; var level: String }
struct GuardAlert: Codable, Hashable {
    var enabled: Bool; var lat: Double?; var lon: Double?; var radiusM: Double; var level: String; var armedAt: Double?
}
struct ZoneAlert: Codable, Hashable { var enabled: Bool; var level: String }
struct OfflineAlert: Codable, Hashable { var enabled: Bool; var hours: Double; var level: String }
struct SimpleAlert: Codable, Hashable { var enabled: Bool; var level: String }

struct AlertConfig: Codable, Hashable {
    var newReport: NewReportAlert
    var movement: MovementAlert
    var guardMode: GuardAlert
    var zones: ZoneAlert
    var offline: OfflineAlert
    var battery: SimpleAlert

    enum CodingKeys: String, CodingKey {
        case newReport, movement, guardMode = "guard", zones, offline, battery
    }
}

struct LostConfig: Codable, Hashable {
    var enabled: Bool
    var since: Double?
    var message: String
    var phone: String
    var level: String
    var notifyEveryReport: Bool
}

struct Device: Codable, Identifiable, Hashable {
    let id: String
    var name: String
    var model: String?
    var emoji: String?
    var color: String?
    var serial: String?
    var kind: String?
    var enabled: Bool
    var retentionDays: Int?
    var alerts: AlertConfig
    var lost: LostConfig
    var total: Int
    var firstTs: Double?
    var last: Report?
    var battery: String?
    var sort: Int?
    var category: String?

    var isItem: Bool { (category ?? "item") == "item" }

    var tint: Color { Color(hex: color ?? "#0A84FF") }
    var symbol: String { (emoji?.isEmpty == false ? emoji : nil) ?? "📍" }
    var isGuarded: Bool { alerts.guardMode.enabled }
}

// MARK: - Status & Einstellungen

struct Stats: Codable, Hashable {
    var total: Int; var today: Int; var batches: Int; var late: Int
    var pollsToday: Int?; var requestsToday: Int?
}

struct TwoFAMethod: Codable, Identifiable, Hashable {
    var index: Int; var type: String; var label: String; var phone: String?
    var id: Int { index }
}

struct AppleStatus: Codable, Hashable {
    var state: String
    var error: String?
    var accountName: String?
    var firstName: String?
    var lastName: String?
    var methods: [TwoFAMethod]?
    var isLoggedIn: Bool { state == "logged_in" }
}

struct ServerStatus: Codable, Hashable {
    var polling: Bool
    var lastPoll: Double?
    var nextPoll: Double?
    var lastError: String?
    var lastNew: Int?
    var lastMode: String?
    var stats: Stats
    var version: String
    var demo: Bool
    var serverTime: Double
    var apple: AppleStatus
    var devices: Int
    var pollInterval: Int
    var retentionDays: Int
}

struct Zone: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var lat: Double
    var lon: Double
    var radius: Double
    var coordinate: CLLocationCoordinate2D { .init(latitude: lat, longitude: lon) }
}

struct BarkConfig: Codable, Hashable {
    var enabled: Bool
    var server: String
    var deviceKeys: [String]
    var sound: String
    var criticalSound: String
    var criticalVolume: Int
    var group: String
    var icon: String
    var minLevel: String
}

struct QuietHours: Codable, Hashable { var enabled: Bool; var start: String; var end: String }

struct OnlineDevicesConfig: Codable, Hashable {
    var enabled: Bool
    var interval: Int
}

// MARK: - Apple-Geräte (online über iCloud + offline über AirTag-Schlüssel)

struct OnlineLocation: Codable, Hashable {
    var lat: Double
    var lon: Double
    var accuracy: Double?
    var ts: Double
    var positionType: String?
    var isOld: Bool?
    var coordinate: CLLocationCoordinate2D { .init(latitude: lat, longitude: lon) }
    var date: Date { Date(timeIntervalSince1970: ts) }
}

struct BestLocation: Codable, Hashable {
    var lat: Double
    var lon: Double
    var accuracy: Double?
    var ts: Double
    var source: String
    var role: String?
    var coordinate: CLLocationCoordinate2D { .init(latitude: lat, longitude: lon) }
    var date: Date { Date(timeIntervalSince1970: ts) }
    var isOnline: Bool { source == "online" }
}

struct AppleDevicePart: Codable, Hashable, Identifiable {
    var role: String
    var deviceId: String
    var name: String?
    var last: Report?
    var battery: String?
    var batteryTs: Double?
    var statusType: String?
    var total: Int
    var id: String { role }
}

enum PartRole: String, CaseIterable, Identifiable {
    case main, left, right, `case`
    var id: String { rawValue }
    var label: String {
        switch self {
        case .main: "Gerät"
        case .left: "Linker AirPod"
        case .right: "Rechter AirPod"
        case .case: "Ladecase"
        }
    }
    var short: String {
        switch self {
        case .main: "Offline"
        case .left: "Links"
        case .right: "Rechts"
        case .case: "Case"
        }
    }
    var symbol: String {
        switch self {
        case .main: "dot.radiowaves.left.and.right"
        case .left: "airpod.left"
        case .right: "airpod.right"
        case .case: "airpods.chargingcase.fill"
        }
    }
}

struct CaseAlert: Codable, Hashable { var enabled: Bool; var level: String }
struct CaseConfig: Codable, Hashable {
    var windowMin: Double
    var alertOut: CaseAlert
    var alertIn: CaseAlert
    var once: Bool
    var sepDistanceM: Double?
    var sepMinObs: Int?
    var sepLookbackH: Double?
    var alertSeparated: CaseAlert?
}

/// Getrennt-Erkennung zwischen zwei AirPods-Teilen.
struct SeparationPair: Codable, Hashable, Identifiable {
    var a: String
    var b: String
    var state: String
    var distance: Double?
    var observations: Int
    var streak: Int
    var since: Double?
    var lastTs: Double?
    var id: String { a + "-" + b }
}

/// Wert, der als Bool, Zahl oder Text kommen kann (Apple ist da uneinheitlich).
struct Flex: Codable, Hashable {
    var text: String?
    var number: Double?
    var bool: Bool?
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let b = try? c.decode(Bool.self) { bool = b }
        else if let n = try? c.decode(Double.self) { number = n; bool = n != 0 }
        else if let s = try? c.decode(String.self) { text = s; bool = ["true", "1", "yes"].contains(s.lowercased()) }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        if let bool { try c.encode(bool) } else if let number { try c.encode(number) } else { try c.encode(text) }
    }
    var isTrue: Bool { bool ?? false }
    var display: String {
        if let text { return text }
        if let number { return number == number.rounded() ? String(Int(number)) : String(format: "%.1f", number) }
        if let bool { return bool ? "Ja" : "Nein" }
        return "–"
    }
}

struct AudioChannel: Codable, Hashable {
    var name: Flex?
    var available: Flex?
    var playing: Flex?
    var muted: Flex?
}

/// Zusatzinfos von iCloud „Geräte suchen“ (alles optional & tolerant).
struct DeviceExtra: Codable, Hashable {
    var lowPowerMode: Flex?
    var batteryStatus: Flex?
    var altitude: Flex?
    var verticalAccuracy: Flex?
    var floorLevel: Flex?
    var positionType: Flex?
    var locationEnabled: Flex?
    var isLocating: Flex?
    var lostModeCapable: Flex?
    var lostModeEnabled: Flex?
    var lostMessage: Flex?
    var lostNumber: Flex?
    var activationLocked: Flex?
    var canSound: Flex?
    var canMessage: Flex?
    var canLocate: Flex?
    var canLost: Flex?
    var deviceColor: Flex?
    var modelDisplayName: Flex?
    var owner: Flex?
    var family: Flex?
    var audioChannels: [AudioChannel]?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func f(_ k: CodingKeys) -> Flex? { (try? c.decodeIfPresent(Flex.self, forKey: k)) ?? nil }
        lowPowerMode = f(.lowPowerMode); batteryStatus = f(.batteryStatus); altitude = f(.altitude)
        verticalAccuracy = f(.verticalAccuracy); floorLevel = f(.floorLevel); positionType = f(.positionType)
        locationEnabled = f(.locationEnabled); isLocating = f(.isLocating); lostModeCapable = f(.lostModeCapable)
        lostModeEnabled = f(.lostModeEnabled); lostMessage = f(.lostMessage); lostNumber = f(.lostNumber)
        activationLocked = f(.activationLocked); canSound = f(.canSound); canMessage = f(.canMessage)
        canLocate = f(.canLocate); canLost = f(.canLost); deviceColor = f(.deviceColor)
        modelDisplayName = f(.modelDisplayName); owner = f(.owner); family = f(.family)
        audioChannels = (try? c.decodeIfPresent([AudioChannel].self, forKey: .audioChannels)) ?? nil
    }
}
struct AppleSettings: Codable, Hashable {
    var caseConfig: CaseConfig
    enum CodingKeys: String, CodingKey { case caseConfig = "case" }
}
struct BudState: Codable, Hashable {
    var state: String
    var since: Double?
    var reason: String
}
struct CaseStatus: Codable, Hashable {
    var left: BudState?
    var right: BudState?
    var summary: String
    var estimated: Bool?
}

/// Aufzeichnung (Session) des Standortverlaufs eines Apple-Geräts.
struct Recording: Codable, Identifiable, Hashable {
    var id: Int
    var appleId: String
    var name: String
    var source: String
    var startTs: Double
    var endTs: Double?
    var stoppedTs: Double?
    var active: Bool
    var effectiveEnd: Double?
    var points: Int?
    var onlinePoints: Int?
    var offlinePoints: Int?
    var lastTs: Double?
    var start: Date { Date(timeIntervalSince1970: startTs) }
    var sourceLabel: String {
        switch source {
        case "online": "Nur online"
        case "offline": "Nur offline"
        default: "Online + Offline"
        }
    }
}
struct RecordingsEnvelope: Codable { var sessions: [Recording] }
struct RecordingPoints: Codable {
    var session: Recording
    var points: [Report]
    var stays: [Stay]
    var places: [Place]
    var totalStayTime: Double
}

struct AppleDevice: Codable, Identifiable, Hashable {
    let id: String
    var kind: String
    var mode: String
    var emoji: String?
    var model: String?
    var displayName: String?
    var deviceClass: String?
    var batteryLevel: Double?
    var batteryStatus: String?
    var deviceStatus: String?
    var hidden: Bool?
    var name: String
    var appleName: String?
    var online: OnlineLocation?
    var parts: [AppleDevicePart]
    var best: BestLocation?
    var reachable: Bool?
    var settings: AppleSettings?
    var caseStatus: CaseStatus?
    var activeSession: Recording?
    var sessionsCount: Int?
    var onlinePoints: Int?
    var extra: DeviceExtra?
    var separation: [SeparationPair]?

    var isAirPods: Bool { mode == "airpods" }
    var isCloud: Bool { kind == "fmip" }
    var roles: [PartRole] { isAirPods ? [.left, .right, .case] : [.main] }
    func part(_ r: PartRole) -> AppleDevicePart? { parts.first { $0.role == r.rawValue } }

    var symbol: String {
        if isAirPods { return "airpodspro" }
        let c = "\(deviceClass ?? "") \(displayName ?? "") \(model ?? "")".lowercased()
        if c.contains("iphone") { return "iphone.gen3" }
        if c.contains("ipad") { return "ipad" }
        if c.contains("watch") { return "applewatch" }
        if c.contains("macbook") { return "laptopcomputer" }
        if c.contains("imac") { return "desktopcomputer" }
        if c.contains("mac") { return "macmini" }
        if c.contains("vision") { return "visionpro" }
        if c.contains("airpod") || c.contains("beats") { return "airpodspro" }
        return "iphone.gen3"
    }

    var batteryText: String? {
        guard let b = batteryLevel else { return nil }
        return "\(Int((b * 100).rounded())) %"
    }
    var batteryColor: Color {
        guard let b = batteryLevel else { return .secondary }
        return b > 0.5 ? .green : (b > 0.2 ? .yellow : .red)
    }
    var batteryIcon: String {
        guard let b = batteryLevel else { return "battery.100percent.circle" }
        if batteryStatus == "Charging" { return "battery.100percent.bolt" }
        return b > 0.75 ? "battery.100percent" : b > 0.5 ? "battery.75percent" : b > 0.25 ? "battery.50percent" : b > 0.1 ? "battery.25percent" : "battery.0percent"
    }
}

struct OnlineStatus: Codable, Hashable {
    var enabled: Bool
    var interval: Int?
    var state: String?
    var account: String?
    var delivery: String?
    var error: String?
    var lastRefresh: Double?
    var isConnected: Bool { state == "connected" }
}

struct AppleDevicesEnvelope: Codable {
    var devices: [AppleDevice]
    var online: OnlineStatus?
}

struct AppleRefreshResult: Codable {
    var ok: Bool?
    var onlineDevices: Int?
    var newOffline: Int?
    var onlineError: String?
    var devices: [AppleDevice]?
    var online: OnlineStatus?
}

struct StaysConfig: Codable, Hashable {
    var radiusM: Double
    var minMinutes: Double
    var minPoints: Int
    var maxOutliers: Int
    var outlierMinutes: Double
    var maxGapHours: Double
    var maxAccuracyM: Double
    var mergeMinutes: Double
}

/// Aufenthalt an einem Ort (vom Server aus den Berichten berechnet).
struct Stay: Codable, Identifiable, Hashable {
    var id: String
    var lat: Double
    var lon: Double
    var radius: Double
    var start: Double
    var end: Double
    var duration: Double
    var leftAt: Double?
    var points: Int
    var outliers: Int
    var firstReportId: Int?
    var lastReportId: Int?
    var ongoing: Bool
    var placeId: String?
    var coordinate: CLLocationCoordinate2D { .init(latitude: lat, longitude: lon) }
    var startDate: Date { Date(timeIntervalSince1970: start) }
    var endDate: Date { Date(timeIntervalSince1970: end) }
}

struct Place: Codable, Identifiable, Hashable {
    var id: String
    var lat: Double
    var lon: Double
    var visits: Int
    var totalDuration: Double
    var lastSeen: Double
    var radius: Double
    var coordinate: CLLocationCoordinate2D { .init(latitude: lat, longitude: lon) }
}

struct NewSince: Codable, Hashable {
    struct Item: Codable, Hashable {
        var deviceId: String
        var n: Int
        var newest: Double?
        var late: Int?
        var batches: Int?
    }
    var since: Double
    var total: Int
    var devices: [Item]
}

struct StaysResponse: Codable {
    var stays: [Stay]
    var places: [Place]
    var totalStayTime: Double
}

struct ServerSettings: Codable, Hashable {
    var pollInterval: Int
    var lostPollInterval: Int
    var quickHours: Double
    var daySweepMinutes: Int
    var fullSweepMinutes: Int
    var retentionDays: Int
    var geocode: Bool
    var anisetteServer: String
    var zones: [Zone]
    var bark: BarkConfig
    var quietHours: QuietHours
    var stays: StaysConfig?
    var onlineDevices: OnlineDevicesConfig?
}

struct Passkey: Codable, Identifiable, Hashable {
    var id: String; var name: String; var created: String?; var lastUsed: String?; var rpId: String?
}

struct SessionInfo: Codable, Identifiable, Hashable {
    var id: String; var label: String?; var ip: String?; var created: Double; var lastUsed: Double
    var kind: String?; var current: Bool
}

struct MeInfo: Codable, Hashable {
    var username: String
    var passwordIsGenerated: Bool
    var totpEnabled: Bool
    var passkeys: [Passkey]
    var sessions: [SessionInfo]
}

struct ServerNotification: Codable, Identifiable, Hashable {
    var id: Int
    var ts: Double
    var deviceId: String?
    var kind: String
    var level: String
    var title: String
    var body: String
    var lat: Double?
    var lon: Double?
    var delivered: Bool?
    var error: String?
    var date: Date { Date(timeIntervalSince1970: ts) }
}

struct HealthInfo: Codable { var ok: Bool; var app: String?; var version: String?; var demo: Bool?; var totp: Bool?; var passkeys: Int? }
struct LoginResult: Codable { var ok: Bool; var token: String?; var error: String?; var needTotp: Bool?; var passwordIsGenerated: Bool? }
struct OKResult: Codable { var ok: Bool?; var error: String? }
struct RefreshResult: Codable { var ok: Bool?; var new: Int?; var polled: Int?; var error: String?; var queued: Bool?; var timeout: Bool? }
struct TOTPSetup: Codable { var ok: Bool; var secret: String; var uri: String }
struct LinkCode: Codable { var ok: Bool; var code: String }
struct ImportResult: Codable {
    struct Added: Codable, Hashable { var id: String; var name: String; var new: Bool }
    struct Failed: Codable, Hashable { var file: String; var error: String }
    var ok: Bool; var added: [Added]?; var errors: [Failed]?
}
struct DevicesEnvelope: Codable { var devices: [Device] }
struct ReportsEnvelope: Codable { var reports: [Report] }
struct NotificationsEnvelope: Codable { var notifications: [ServerNotification] }
struct ReportsEvent: Codable { var deviceId: String; var reports: [Report] }

// MARK: - Hilfen

enum AlertLevel: String, CaseIterable, Identifiable {
    case passive, active, timeSensitive, critical
    var id: String { rawValue }
    var label: String {
        switch self {
        case .passive: "Leise"
        case .active: "Normal"
        case .timeSensitive: "Dringend"
        case .critical: "Kritisch"
        }
    }
    var icon: String {
        switch self {
        case .passive: "bell.slash"
        case .active: "bell"
        case .timeSensitive: "bell.badge"
        case .critical: "exclamationmark.triangle.fill"
        }
    }
    var color: Color {
        switch self {
        case .passive: .gray
        case .active: .blue
        case .timeSensitive: .orange
        case .critical: .red
        }
    }
    static func of(_ s: String) -> AlertLevel { AlertLevel(rawValue: s) ?? .active }
}

enum BatteryLevel {
    static func icon(_ s: String?) -> String {
        switch s {
        case "full": "battery.100percent"
        case "medium": "battery.50percent"
        case "low": "battery.25percent"
        case "critical": "battery.0percent"
        default: "battery.100percent.circle"
        }
    }
    static func label(_ s: String?) -> String {
        switch s {
        case "full": "Voll"
        case "medium": "Mittel"
        case "low": "Schwach"
        case "critical": "Kritisch"
        default: "Unbekannt"
        }
    }
    static func color(_ s: String?) -> Color {
        switch s {
        case "full": .green
        case "medium": .yellow
        case "low", "critical": .red
        default: .secondary
        }
    }
}

extension Color {
    init(hex: String) {
        var s = hex.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        var v: UInt64 = 0
        Scanner(string: s).scanHexInt64(&v)
        let r, g, b: Double
        if s.count == 6 {
            r = Double((v >> 16) & 0xFF) / 255; g = Double((v >> 8) & 0xFF) / 255; b = Double(v & 0xFF) / 255
        } else {
            r = 0.04; g = 0.52; b = 1
        }
        self.init(red: r, green: g, blue: b)
    }
}

extension Date {
    var relativeDE: String {
        let f = RelativeDateTimeFormatter()
        f.locale = Locale(identifier: "de_DE")
        f.unitsStyle = .short
        let s = -timeIntervalSinceNow
        if s < 45 { return "gerade eben" }
        return f.localizedString(for: self, relativeTo: .now)
    }
    var shortDE: String {
        formatted(.dateTime.day(.twoDigits).month(.twoDigits).hour().minute().locale(Locale(identifier: "de_DE")))
    }
    var timeDE: String {
        formatted(.dateTime.hour().minute().second().locale(Locale(identifier: "de_DE")))
    }
}

func formatDuration(_ s: Double) -> String {
    let m = Int((s / 60).rounded())
    if m < 1 { return "< 1 min" }
    if m < 60 { return "\(m) min" }
    let h = m / 60, rm = m % 60
    if h < 24 { return rm == 0 ? "\(h) h" : "\(h) h \(rm) min" }
    let d = h / 24, rh = h % 24
    return rh == 0 ? "\(d) T" : "\(d) T \(rh) h"
}

func formatDistance(_ m: Double) -> String {
    m >= 1000 ? String(format: "%.1f km", m / 1000) : String(format: "%.0f m", m)
}

func distance(_ a: CLLocationCoordinate2D, _ b: CLLocationCoordinate2D) -> Double {
    CLLocation(latitude: a.latitude, longitude: a.longitude)
        .distance(from: CLLocation(latitude: b.latitude, longitude: b.longitude))
}
