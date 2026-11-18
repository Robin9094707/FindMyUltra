import Foundation

/// Letzter bekannter Stand (Objekte, Geräte, Status, Einstellungen) für einen sofortigen Start.
/// Liegt im Caches-Ordner – iOS darf ihn jederzeit löschen, dann wird einfach neu geladen.
struct AppSnapshot: Codable {
    var devices: [Device]
    var appleDevices: [AppleDevice]
    var onlineStatus: OnlineStatus?
    var status: ServerStatus?
    var settings: ServerSettings?
    var savedAt: Double
}

enum AppCache {
    private static var url: URL? {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?
            .appendingPathComponent("findmyultra-snapshot.json")
    }

    static func load() -> AppSnapshot? {
        guard let url, let data = try? Data(contentsOf: url) else { return nil }
        // Ein unlesbarer Cache (z. B. nach einem Update) wird einfach ignoriert.
        guard let snap = try? JSONDecoder().decode(AppSnapshot.self, from: data) else {
            try? FileManager.default.removeItem(at: url)
            return nil
        }
        return snap
    }

    static func save(_ snap: AppSnapshot) {
        guard let url, let data = try? JSONEncoder().encode(snap) else { return }
        try? data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    static func clear() {
        guard let url else { return }
        try? FileManager.default.removeItem(at: url)
    }
}
