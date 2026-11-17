import Foundation
import SwiftUI
import UIKit
import Observation
import Security
import UserNotifications
import CoreLocation
import MapKit

enum SheetSection: String, CaseIterable, Identifiable {
    case items, alerts, me
    var id: String { rawValue }
    var title: String {
        switch self {
        case .items: "Objekte"
        case .alerts: "Mitteilungen"
        case .me: "Ich"
        }
    }
    var icon: String {
        switch self {
        case .items: "circle.grid.2x2.fill"
        case .alerts: "bell.fill"
        case .me: "person.crop.circle.fill"
        }
    }
}
struct DeviceRoute: Hashable { let id: String }

enum CircleMode: String, CaseIterable, Identifiable {
    case off, selected, all
    var id: String { rawValue }
    var label: String {
        switch self {
        case .off: "Aus"
        case .selected: "Auswahl"
        case .all: "Alle"
        }
    }
}

extension PresentationDetent {
    static let peek = PresentationDetent.height(150)
}

@MainActor
@Observable
final class AppModel {
    // Verbindung
    var serverURLString: String = UserDefaults.standard.string(forKey: "serverURL") ?? ""
    var isConnected: Bool = false
    var isBooting: Bool = true
    var liveConnected: Bool = false
    var api: APIClient?

    // Daten
    var devices: [Device] = []
    var status: ServerStatus?
    var settings: ServerSettings?
    var me: MeInfo?
    var notifications: [ServerNotification] = []
    var unreadAlerts: Int = 0
    var history: [String: [Report]] = [:]
    var addresses: [String: String] = [:]

    // UI (Sheet wie in „Wo ist?“)
    var section: SheetSection = .items
    var sheetPath: [DeviceRoute] = [] {
        didSet { if sheetPath.isEmpty { clearFocus() } }
    }
    var detent: PresentationDetent = .medium
    var isRefreshing = false

    // Karte & Verlauf des fokussierten Objekts
    var focusedID: String?
    var historyRange: HistoryRange = .d7
    var track: [Report] = []
    var cursor: Int?
    var circleMode: CircleMode = CircleMode(rawValue: UserDefaults.standard.string(forKey: "circleMode") ?? "") ?? .selected {
        didSet { UserDefaults.standard.set(circleMode.rawValue, forKey: "circleMode") }
    }
    var followCursor = true
    var cameraRegion: MKCoordinateRegion?
    var cameraTick = 0
    var thoroughRefresh: Bool = UserDefaults.standard.object(forKey: "thoroughRefresh") as? Bool ?? true {
        didSet { UserDefaults.standard.set(thoroughRefresh, forKey: "thoroughRefresh") }
    }
    var toast: String?
    var lastError: String?
    var inAppNotifications: Bool = UserDefaults.standard.object(forKey: "inAppNotifications") as? Bool ?? true {
        didSet { UserDefaults.standard.set(inAppNotifications, forKey: "inAppNotifications") }
    }

    private var liveTask: Task<Void, Never>?
    private let geocoder = CLGeocoder()

    init() {
        if let url = APIClient.normalize(serverURLString), let token = Keychain.get("token") {
            api = APIClient(baseURL: url, token: token, pinnedFingerprint: UserDefaults.standard.string(forKey: "pin"))
        }
    }

    var pinnedFingerprint: String? { UserDefaults.standard.string(forKey: "pin") }

    // MARK: Start / Anmeldung

    func boot() async {
        defer { isBooting = false }
        guard api != nil else { return }
        do {
            try await loadAll()
            isConnected = true
            startLive()
        } catch let e as APIError where e.isUnauthorized {
            isConnected = false
        } catch {
            // Server evtl. nur kurz nicht erreichbar – trotzdem App zeigen
            isConnected = true
            lastError = error.localizedDescription
            startLive()
        }
    }

    func health(for urlString: String, pin: String? = nil) async throws -> HealthInfo {
        guard let url = APIClient.normalize(urlString) else { throw APIError.invalidURL }
        let c = APIClient(baseURL: url, pinnedFingerprint: pin ?? pinnedFingerprint)
        return try await c.get("/api/health")
    }

    func trust(fingerprint: String) {
        UserDefaults.standard.set(fingerprint, forKey: "pin")
        api?.pinnedFingerprint = fingerprint
    }

    func login(server: String, username: String, password: String, totp: String?) async throws {
        guard let url = APIClient.normalize(server) else { throw APIError.invalidURL }
        let c = APIClient(baseURL: url, pinnedFingerprint: pinnedFingerprint)
        var body: [String: Any] = ["username": username, "password": password,
                                   "label": "iPhone – \(UIDevice.current.name)"]
        if let totp, !totp.isEmpty { body["totp"] = totp }
        let r: LoginResult = try await c.send("POST", "/api/auth/login", json: body)
        guard let token = r.token else { throw APIError.http(401, r.error ?? "Anmeldung fehlgeschlagen", needTotp: r.needTotp ?? false) }
        try await finishLogin(url: url, token: token)
    }

    func finishLogin(url: URL, token: String) async throws {
        Keychain.set(token, for: "token")
        serverURLString = url.absoluteString
        UserDefaults.standard.set(serverURLString, forKey: "serverURL")
        api = APIClient(baseURL: url, token: token, pinnedFingerprint: pinnedFingerprint)
        try await loadAll()
        isConnected = true
        startLive()
        requestNotificationPermission()
    }

    func logout() async {
        _ = try? await api?.send("POST", "/api/auth/logout", as: OKResult.self)
        disconnect()
    }

    func disconnect() {
        stopLive()
        Keychain.delete("token")
        api = nil
        isConnected = false
        devices = []; status = nil; settings = nil; me = nil; notifications = []; history = [:]
        sheetPath = []
    }

    // MARK: Laden

    func loadAll() async throws {
        guard let api else { return }
        async let d: DevicesEnvelope = api.get("/api/devices")
        async let s: ServerStatus = api.get("/api/status")
        async let st: ServerSettings = api.get("/api/settings")
        async let m: MeInfo = api.get("/api/auth/me")
        async let n: NotificationsEnvelope = api.get("/api/notifications", query: [.init(name: "limit", value: "150")])
        let (dd, ss, sett, mm, nn) = try await (d, s, st, m, n)
        devices = dd.devices
        status = ss
        settings = sett
        me = mm
        notifications = nn.notifications
    }

    func reloadDevices() async {
        guard let api else { return }
        if let d: DevicesEnvelope = try? await api.get("/api/devices") { devices = d.devices }
    }

    func reloadStatus() async {
        guard let api else { return }
        if let s: ServerStatus = try? await api.get("/api/status") { status = s }
    }

    func reloadMe() async {
        guard let api else { return }
        if let m: MeInfo = try? await api.get("/api/auth/me") { me = m }
    }

    func reloadNotifications() async {
        guard let api else { return }
        if let n: NotificationsEnvelope = try? await api.get("/api/notifications", query: [.init(name: "limit", value: "150")]) {
            notifications = n.notifications
        }
    }

    func device(_ id: String) -> Device? { devices.first { $0.id == id } }

    func loadHistory(_ id: String, since: Double?) async throws -> [Report] {
        guard let api else { return [] }
        var q: [URLQueryItem] = []
        if let since { q.append(.init(name: "since", value: String(since))) }
        let r: ReportsEnvelope = try await api.get("/api/devices/\(id)/reports", query: q)
        history[id] = r.reports
        return r.reports
    }

    // MARK: Aktionen

    /// Aktualisieren: standardmäßig gründlich (Schnell-Abruf + 24 h + 7 Tage in einer gebündelten Abfrage).
    @discardableResult
    func refresh(deviceID: String? = nil, full: Bool? = nil) async -> RefreshResult? {
        guard let api else { return nil }
        guard !isRefreshing else { return nil }
        Haptics.soft()
        isRefreshing = true
        defer { isRefreshing = false }
        var body: [String: Any] = ["wait": true, "full": full ?? thoroughRefresh, "timeout": 110]
        if let deviceID { body["device_id"] = deviceID }
        do {
            let r: RefreshResult = try await api.send("POST", "/api/refresh", json: body, timeout: 120)
            await reloadDevices()
            await reloadStatus()
            if let id = focusedID { await reloadTrack(id, keepCursor: true) }
            if let e = r.error { Haptics.warning(); showToast("⚠️ \(e)") }
            else if r.timeout == true { Haptics.light(); showToast("Abruf läuft im Hintergrund weiter …") }
            else if (r.new ?? 0) > 0 { Haptics.success(); showToast("\(r.new ?? 0) neue Standorte") }
            else { Haptics.light(); showToast("Alles aktuell – keine neuen Standorte") }
            return r
        } catch {
            Haptics.warning()
            showToast("⚠️ \(error.localizedDescription)")
            return nil
        }
    }

    func patchDevice(_ id: String, _ body: [String: Any]) async throws {
        guard let api else { return }
        let d: Device = try await api.send("PATCH", "/api/devices/\(id)", json: body)
        replace(d)
    }

    func patchDevice<B: Encodable>(_ id: String, encodable: B) async throws {
        guard let api else { return }
        let d: Device = try await api.sendEncodable("PATCH", "/api/devices/\(id)", body: encodable)
        replace(d)
    }

    func deleteDevice(_ id: String) async throws {
        guard let api else { return }
        let _: OKResult = try await api.send("DELETE", "/api/devices/\(id)")
        devices.removeAll { $0.id == id }
    }

    func saveSettings(_ s: ServerSettings) async throws {
        guard let api else { return }
        settings = try await api.sendEncodable("PUT", "/api/settings", body: s)
    }

    private func replace(_ d: Device) {
        if let i = devices.firstIndex(where: { $0.id == d.id }) { devices[i] = d } else { devices.append(d) }
    }

    func showToast(_ s: String) {
        toast = s
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(3.5))
            if toast == s { toast = nil }
        }
    }

    func openDevice(_ id: String) {
        Haptics.selection()
        section = .items
        if sheetPath.last?.id != id { sheetPath = [DeviceRoute(id: id)] }
        if detent == .peek { detent = .medium }
    }

    // MARK: Fokus, Verlauf & Kamera

    func focus(_ id: String) async {
        if focusedID != id {
            focusedID = id
            track = []
            cursor = nil
        }
        if let r = device(id)?.last { show(center: r.coordinate, meters: 900) }
        await reloadTrack(id, keepCursor: false)
        fitTrack()
    }

    func clearFocus() {
        focusedID = nil
        track = []
        cursor = nil
    }

    func reloadTrack(_ id: String, keepCursor: Bool) async {
        let since: Double? = historyRange == .all ? nil : Date().timeIntervalSince1970 - historyRange.rawValue
        guard let r = try? await loadHistory(id, since: since), focusedID == id else { return }
        let wasAtEnd = cursor == nil || cursor == track.count - 1
        track = r
        if !keepCursor || wasAtEnd { cursor = r.isEmpty ? nil : r.count - 1 }
        else if let c = cursor, c >= r.count { cursor = r.count - 1 }
    }

    var cursorReport: Report? {
        guard let c = cursor, track.indices.contains(c) else { return nil }
        return track[c]
    }

    func select(reportID: Int) {
        if let i = track.firstIndex(where: { $0.id == reportID }) {
            Haptics.selection()
            cursor = i
        }
    }

    /// Verschiebt die Kamera so, dass der Punkt oberhalb des Sheets sichtbar ist.
    func show(center: CLLocationCoordinate2D, meters: Double) {
        let r = MKCoordinateRegion(center: center, latitudinalMeters: meters, longitudinalMeters: meters)
        show(region: r)
    }

    func show(region r: MKCoordinateRegion) {
        var r = r
        let shift: Double = switch detent {
        case .large: 0.0
        case .peek: 0.12
        default: 0.32
        }
        let grow = 1 + shift * 1.6
        r.span.latitudeDelta *= grow
        r.span.longitudeDelta *= grow
        r.center.latitude -= r.span.latitudeDelta * shift * 0.75
        cameraRegion = r
        cameraTick += 1
    }

    func fitTrack() {
        let coords = track.map(\.coordinate)
        if let r = region(fitting: coords, padding: 1.35, minSpan: 0.006) { show(region: r) }
    }

    func fitAll() {
        let coords = devices.compactMap(\.last).map(\.coordinate)
        if let r = region(fitting: coords, padding: 1.6) { show(region: r) }
    }

    func distanceFromUser(_ r: Report) -> String? {
        guard let loc = LocationPermission.manager.location else { return nil }
        return formatDistance(loc.distance(from: CLLocation(latitude: r.lat, longitude: r.lon)))
    }

    func handle(url: URL) {
        guard url.scheme == "findmyultra" else { return }
        if url.host == "device" {
            let id = url.pathComponents.dropFirst().first ?? ""
            if !id.isEmpty { openDevice(id) }
        }
    }

    // MARK: Adressen

    func address(for r: Report) async -> String? {
        let key = String(format: "%.4f,%.4f", r.lat, r.lon)
        if let a = addresses[key] { return a }
        guard let p = try? await geocoder.reverseGeocodeLocation(CLLocation(latitude: r.lat, longitude: r.lon)).first
        else { return nil }
        let street = [p.thoroughfare, p.subThoroughfare].compactMap { $0 }.joined(separator: " ")
        let s = [street.isEmpty ? p.name : street, p.locality].compactMap { $0 }.joined(separator: ", ")
        addresses[key] = s
        return s
    }

    // MARK: Live

    func startLive() {
        guard liveTask == nil, api != nil else { return }
        liveTask = Task { [weak self] in
            var delay: Double = 1
            while !Task.isCancelled {
                guard let self, let api = self.api else { return }
                do {
                    for try await (event, data) in api.events() {
                        self.liveConnected = true
                        delay = 1
                        self.handleEvent(event, data)
                    }
                } catch {
                    if (error as? APIError)?.isUnauthorized == true {
                        self.liveConnected = false
                        self.isConnected = false
                        return
                    }
                }
                self.liveConnected = false
                try? await Task.sleep(for: .seconds(delay))
                delay = min(delay * 2, 30)
            }
        }
    }

    func stopLive() {
        liveTask?.cancel()
        liveTask = nil
        liveConnected = false
    }

    private func handleEvent(_ event: String, _ data: Data) {
        guard let api else { return }
        switch event {
        case "status":
            if let s = try? api.decoder.decode(ServerStatus.self, from: data) { status = s }
        case "devices":
            if let d = try? api.decoder.decode(DevicesEnvelope.self, from: data) { devices = d.devices }
        case "device":
            if let d = try? api.decoder.decode(Device.self, from: data) { replace(d) }
        case "reports":
            if let r = try? api.decoder.decode(ReportsEvent.self, from: data) {
                if var h = history[r.deviceId] {
                    h.append(contentsOf: r.reports)
                    h.sort { $0.ts < $1.ts }
                    history[r.deviceId] = h
                }
                if r.deviceId == focusedID {
                    let atEnd = cursor == nil || cursor == track.count - 1
                    let since = historyRange == .all ? 0 : Date().timeIntervalSince1970 - historyRange.rawValue
                    var t = track + r.reports.filter { $0.ts >= since }
                    t.sort { $0.ts < $1.ts }
                    track = t
                    if atEnd { cursor = t.isEmpty ? nil : t.count - 1 }
                    Haptics.light()
                }
            }
        case "settings":
            if let s = try? api.decoder.decode(ServerSettings.self, from: data) { settings = s }
        case "notification":
            if let n = try? api.decoder.decode(ServerNotification.self, from: data) {
                notifications.insert(n, at: 0)
                if section != .alerts { unreadAlerts += 1 }
                if n.level == "critical" { Haptics.warning() }
                if inAppNotifications { postLocal(n) }
            }
        default: break
        }
    }

    // MARK: Lokale Mitteilungen (zusätzlich zu Bark)

    func requestNotificationPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    private func postLocal(_ n: ServerNotification) {
        let c = UNMutableNotificationContent()
        c.title = n.title
        c.body = n.body
        c.sound = n.level == "critical" ? .defaultCritical : .default
        c.interruptionLevel = switch n.level {
        case "critical", "timeSensitive": .timeSensitive
        case "passive": .passive
        default: .active
        }
        if let d = n.deviceId { c.userInfo = ["url": "findmyultra://device/\(d)"] }
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "n\(n.id)", content: c, trigger: nil))
    }
}

// MARK: - Keychain

enum Keychain {
    private static let service = "de.findmyultra.app"

    static func set(_ value: String, for key: String) {
        delete(key)
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: key, kSecValueData as String: Data(value.utf8),
                                kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock]
        SecItemAdd(q as CFDictionary, nil)
    }

    static func get(_ key: String) -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: key, kSecReturnData as String: true,
                                kSecMatchLimit as String: kSecMatchLimitOne]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    static func delete(_ key: String) {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: key]
        SecItemDelete(q as CFDictionary)
    }
}
