import Foundation
import SwiftUI
import Combine
import Observation
import SpotIntegration

// MARK: - Google Find Hub direkt auf dem iPhone → Server

/// Verbindet die lokale Google-Ortung (Spot-Engine) mit dem FindMy-Ultra-Server:
/// lokal entschlüsselte Standorte werden an den Server übertragen und landen dort
/// als normale Objekte (Netz „google“) mit Verlauf, Alarmen und Aufenthalten.
@MainActor
@Observable
final class GoogleLink {
    static let shared = GoogleLink()

    /// Google wurde auf diesem iPhone eingerichtet. Erst dann startet die Engine
    /// (spart Speicher, Bluetooth und Netzwerk, wenn Google gar nicht genutzt wird).
    static var inUse: Bool {
        get { UserDefaults.standard.bool(forKey: "googleInUse") }
        set { UserDefaults.standard.set(newValue, forKey: "googleInUse") }
    }

    @ObservationIgnored weak var model: AppModel?
    @ObservationIgnored private var subscription: AnyCancellable?
    @ObservationIgnored private var pending: Task<Void, Never>?
    @ObservationIgnored private var lastSignature = ""

    var isPushing = false
    var lastPush: Date?
    var lastPushCount = 0
    var lastError: String?

    /// Standorte automatisch an den Server senden (empfohlen – sonst nur in dieser Ansicht sichtbar).
    var syncToServer: Bool = UserDefaults.standard.object(forKey: "googleSyncToServer") as? Bool ?? true {
        didSet { UserDefaults.standard.set(syncToServer, forKey: "googleSyncToServer"); if syncToServer { schedule(0.2) } }
    }
    /// Optional: gesammelten Google-Standortverlauf mitsenden statt nur des jeweils neuesten Standorts.
    var sendHistory: Bool = UserDefaults.standard.object(forKey: "googleSendHistory") as? Bool ?? false {
        didSet { UserDefaults.standard.set(sendHistory, forKey: "googleSendHistory"); if sendHistory { schedule(0.2) } }
    }

    private var sent: [String: Double] {
        get { UserDefaults.standard.dictionary(forKey: "googleSentTs") as? [String: Double] ?? [:] }
        set { UserDefaults.standard.set(newValue, forKey: "googleSentTs") }
    }

    var store: GoogleTrackerStore { GoogleTrackerStore.shared }

    func attach(_ model: AppModel) {
        self.model = model
        guard subscription == nil, Self.inUse else { return }
        subscription = GoogleTrackerStore.shared.$trackers
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in Task { @MainActor in self?.schedule() } }
    }

    func start() async {
        guard Self.inUse, model?.networkEnabled(.google) ?? true else { return }
        if let model, subscription == nil { attach(model) }
        await store.restoreIfNeeded()
        schedule(1)
    }

    func schedule(_ delay: Double = 2) {
        pending?.cancel()
        pending = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled else { return }
            await self?.push()
        }
    }

    private static func battery(_ s: String?) -> String? {
        switch s {
        case "Normal": "full"
        case "Low": "low"
        case "Critical": "critical"
        default: nil
        }
    }

    /// Überträgt neue Standorte. Gibt die Zahl neuer Berichte auf dem Server zurück.
    @discardableResult
    func push(force: Bool = false) async -> Int? {
        guard syncToServer, let model, let api = model.api, model.networkEnabled(.google), store.hasCredentials else { return nil }
        guard !isPushing else { return nil }
        let trackers = store.trackers
        guard !trackers.isEmpty else { return nil }
        var sentTs = sent
        var devices: [[String: Any]] = []
        var newest: [String: Double] = [:]
        var reportCount = 0
        for t in trackers {
            let last = sentTs[t.id] ?? 0
            var reports: [[String: Any]] = []
            if sendHistory {
                let all = await store.reports(for: t.id)
                for r in all {
                    guard let lat = r.latitude, let lon = r.longitude else { continue }
                    let ts = r.date.timeIntervalSince1970
                    guard ts > last else { continue }
                    var item: [String: Any] = ["ts": ts, "lat": lat, "lon": lon]
                    if let a = r.accuracy { item["accuracy"] = a }
                    reports.append(item)
                }
                reports.sort { ($0["ts"] as? Double ?? 0) < ($1["ts"] as? Double ?? 0) }
                if reports.count > 4000 { reports = Array(reports.suffix(4000)) }
            }
            if let lat = t.latitude, let lon = t.longitude, let d = t.reportedAt, d.timeIntervalSince1970 > last,
               !reports.contains(where: { ($0["ts"] as? Double) == d.timeIntervalSince1970 }) {
                var item: [String: Any] = ["ts": d.timeIntervalSince1970, "lat": lat, "lon": lon]
                if let a = t.accuracy { item["accuracy"] = a }
                if let b = Self.battery(t.battery) { item["battery"] = b }
                reports.append(item)
            }
            if let maxTs = reports.compactMap({ $0["ts"] as? Double }).max() { newest[t.id] = maxTs }
            reportCount += reports.count
            devices.append(["id": t.id, "name": t.name, "reports": reports])
        }
        let signature = trackers.map { "\($0.id)|\($0.name)" }.joined(separator: ",")
        guard force || reportCount > 0 || signature != lastSignature else { return 0 }
        isPushing = true
        defer { isPushing = false }
        do {
            let r: NetworkActionResult = try await api.send("POST", "/api/google/app-reports",
                                                            json: ["devices": devices, "account": store.account ?? ""],
                                                            timeout: 90)
            for (id, ts) in newest { sentTs[id] = max(sentTs[id] ?? 0, ts) }
            sent = sentTs
            lastSignature = signature
            lastPush = .now
            lastPushCount = r.new ?? 0
            lastError = nil
            if (r.new ?? 0) > 0 { await model.reloadDevices() }
            return r.new
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }

    /// Lokalen Zugang an den eigenen Server übergeben (für die Server-Ortung als Fallback).
    func handOverToServer() async throws -> NetworkStatus? {
        guard let api = model?.api else { throw APIError.invalidURL }
        guard let secrets = store.exportSecrets() else {
            throw APIError.http(0, "Bitte zuerst in der App bei Google anmelden und die Schlüssel entsperren.", needTotp: false)
        }
        let r: NetworkActionResult = try await api.send("POST", "/api/google/secrets", json: secrets, timeout: 60)
        await model?.reloadStatus()
        return r.status
    }

    func snapshot(for device: Device) -> GoogleTrackerSnapshot? {
        guard Self.inUse, device.net == .google, let ext = device.extId else { return nil }
        return store.trackers.first { $0.id == ext }
    }
}

// MARK: - AppModel: Netze

extension AppModel {
    var networks: NetworksStatus? { status?.networks }

    func networkEnabled(_ n: TrackerNetwork) -> Bool {
        settings?.networks?.enabled(n) ?? true
    }

    func isShown(_ n: TrackerNetwork) -> Bool { networkFilter.contains(n) }

    /// Objekte, die der Netz-Filter gerade zeigt.
    var visibleItems: [Device] { items.filter { networkFilter.contains($0.net) } }

    /// Verlauf eines Objekts oder eine Aufzeichnung ist offen → auf der Karte nur diese Spur zeigen.
    var isolating: Bool { historyVisible && (focusedID != nil || focusedRecordingID != nil) }

    /// Objekt-Pins auf der Karte: Netz-Filter, ausgewähltes Objekt immer, im Verlauf nur dieses.
    var mapItems: [Device] {
        if isolating {
            guard let id = focusedID, let d = device(id) else { return [] }
            return [d]
        }
        var list = visibleItems
        if let id = focusedID, let d = device(id), !list.contains(where: { $0.id == id }) { list.append(d) }
        return list
    }

    /// Apple-Geräte auf der Karte: im Geräte-Tab immer, sonst wenn „Apple“ im Filter ist
    /// (und „Apple-Geräte anzeigen“ an). Das ausgewählte Gerät ist immer sichtbar.
    var mapAppleDevices: [AppleDevice] {
        if isolating { return [] }
        let located = appleDevices.filter { $0.best != nil }
        if section == .devices || (showAppleOnMap && networkFilter.contains(.apple)) { return located }
        return located.filter { $0.id == focusedAppleID }
    }

    /// Netze, in denen es Objekte gibt (für die Filter-Leiste).
    var presentNetworks: [TrackerNetwork] {
        let nets = Set(items.map(\.net))
        return TrackerNetwork.allCases.filter { nets.contains($0) || ($0 != .apple && networks?.of($0)?.connected == true) }
    }

    func toggleFilter(_ n: TrackerNetwork) {
        Haptics.selection()
        var f = networkFilter
        if f.contains(n) && f.count > 1 { f.remove(n) } else { f.insert(n) }
        withAnimation(.spring(duration: 0.3)) { networkFilter = f }
    }

    func showOnly(_ n: TrackerNetwork?) {
        Haptics.selection()
        withAnimation(.spring(duration: 0.3)) { networkFilter = n.map { Set([$0]) } ?? Set(TrackerNetwork.allCases) }
    }

    /// „Orten“ – je nach Netz: Google zuerst direkt auf dem iPhone, sonst über den Server.
    func locate(_ d: Device) async {
        guard !isRefreshing else { return }
        if d.net == .google, GoogleLink.inUse, let ext = d.extId, GoogleTrackerStore.shared.hasDevice(ext) {
            Haptics.soft()
            isRefreshing = true
            await GoogleTrackerStore.shared.refreshLocation(ext)
            let n = await GoogleLink.shared.push(force: true) ?? 0
            isRefreshing = false
            await reloadDevices()
            if let id = focusedID { await reloadTrack(id, keepCursor: true) }
            if GoogleTrackerStore.shared.locationSucceeded[ext] == false,
               networks?.google?.serverReady == true {
                showToast("iPhone ohne Antwort – Server ortet als Fallback …")
                await refresh(deviceID: d.id)
            } else {
                Haptics.success()
                showToast(n > 0 ? "\(n) neue Google-Standorte" : (GoogleTrackerStore.shared.locationStatus[ext] ?? "Google aktualisiert"))
            }
            return
        }
        await refresh(deviceID: d.id)
    }

    func networkAction(_ path: String, json: [String: Any]? = nil, timeout: TimeInterval = 90) async throws -> NetworkActionResult {
        guard let api else { throw APIError.invalidURL }
        let r: NetworkActionResult = try await api.send("POST", path, json: json ?? [:], timeout: timeout)
        await reloadStatus()
        await reloadDevices()
        return r
    }

    func setNetworkEnabled(_ n: TrackerNetwork, _ on: Bool) async {
        guard var s = settings, var nets = s.networks else { return }
        nets.setEnabled(n, on)
        s.networks = nets
        try? await saveSettings(s)
        await reloadStatus()
        if on && n == .google { await GoogleLink.shared.start() }
    }
}
