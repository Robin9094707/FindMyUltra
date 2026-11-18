import SwiftUI
import WebKit
import SpotIntegration

// MARK: - Netz-Filter (Objektliste)

/// Glas-Leiste: Alle · Apple · Google · Samsung. Tippen = nur dieses Netz, nochmal tippen = alle.
/// Lange drücken = Netz zusätzlich ein-/ausblenden.
struct NetworkFilterBar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let all = model.networkFilter.count == TrackerNetwork.allCases.count
        ScrollView(.horizontal, showsIndicators: false) {
            GlassEffectContainer(spacing: 8) {
                HStack(spacing: 8) {
                    chip(title: "Alle", symbol: "square.grid.2x2.fill", color: .accentColor, count: model.items.count,
                         selected: all) { model.showOnly(nil) }
                    ForEach(model.presentNetworks) { n in
                        let only = model.networkFilter == [n]
                        chip(title: n.label, symbol: n.symbol, color: n == .apple ? Color(.label) : n.color,
                             count: model.items.filter { $0.net == n }.count,
                             selected: !all && model.isShown(n)) {
                            only ? model.showOnly(nil) : model.showOnly(n)
                        }
                        .contextMenu {
                            Button {
                                model.toggleFilter(n)
                            } label: {
                                Label(model.isShown(n) ? "Ausblenden" : "Zusätzlich einblenden",
                                      systemImage: model.isShown(n) ? "eye.slash" : "eye")
                            }
                        }
                    }
                }
                .padding(.vertical, 6)
            }
        }
        .scrollClipDisabled()
    }

    private func chip(title: String, symbol: String, color: Color, count: Int, selected: Bool,
                      action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: symbol).foregroundStyle(selected ? .white : color)
                Text(title)
                Text("\(count)").font(.caption.bold().monospacedDigit())
                    .foregroundStyle(selected ? .white.opacity(0.85) : .secondary)
            }
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(selected ? .white : .primary)
            .padding(.horizontal, 14).padding(.vertical, 9)
        }
        .buttonStyle(.plain)
        .glassEffect(selected ? .regular.tint(color.opacity(0.85)).interactive() : .regular.interactive(), in: .capsule)
    }
}

// MARK: - Netz-Zeile in „Ich“

struct NetworkRow: View {
    @Environment(AppModel.self) private var model
    @ObservedObject private var google = GoogleTrackerStore.shared
    let network: TrackerNetwork

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: network.symbol)
                .font(.title3)
                .foregroundStyle(network == .apple ? Color(.label) : network.color)
                .frame(width: 30)
            VStack(alignment: .leading, spacing: 2) {
                Text(network.longLabel)
                Text(subtitle).font(.caption).foregroundStyle(subtitleColor).lineLimit(1)
            }
            Spacer()
            if !model.networkEnabled(network) {
                Text("AUS").font(.caption2.bold()).foregroundStyle(.secondary)
            }
        }
    }

    private var subtitle: String {
        let count = model.items.filter { $0.net == network }.count
        switch network {
        case .apple:
            return model.status?.apple.isLoggedIn == true ? "\(model.status?.apple.accountName ?? "verbunden") · \(count) Objekte" : "nicht angemeldet"
        case .google:
            let s = model.networks?.google
            if google.hasCredentials { return "\(google.account ?? "iPhone") · \(google.trackers.count) Tracker" + (s?.serverReady == true ? " · Server bereit" : "") }
            if s?.secrets == true { return "nur Server · \(count) Tracker" }
            return "nicht verbunden"
        case .samsung:
            let s = model.networks?.samsung
            if s?.connected == true { return "\(s?.account ?? "verbunden") · \(count) SmartTags" }
            return "nicht verbunden"
        }
    }

    private var subtitleColor: Color {
        switch network {
        case .apple: model.status?.apple.isLoggedIn == true ? .secondary : .orange
        case .google: (google.hasCredentials || model.networks?.google?.secrets == true) ? .secondary : .orange
        case .samsung: model.networks?.samsung?.connected == true ? .secondary : .orange
        }
    }
}

/// Kopf einer Netz-Seite im Glas-Stil.
struct NetworkHero: View {
    let network: TrackerNetwork
    let title: String
    let subtitle: String
    var ok: Bool

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: network.symbol)
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 60, height: 60)
                .background(network.color.gradient, in: .rect(cornerRadius: 18))
                .overlay(alignment: .bottomTrailing) {
                    Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                        .font(.system(size: 18)).foregroundStyle(.white, ok ? .green : .orange)
                        .background(Circle().fill(Color(.systemBackground)).padding(1))
                        .offset(x: 5, y: 5)
                }
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.title3.bold())
                Text(subtitle).font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 6)
    }
}

/// Gemeinsame Hilfe: Netzwerk-Einstellungen ändern und speichern.
@MainActor
func updateNetworks(_ model: AppModel, _ change: (inout NetworksConfig) -> Void) async {
    guard var s = model.settings, var n = s.networks else { return }
    change(&n)
    s.networks = n
    do { try await model.saveSettings(s) } catch { model.showToast("⚠️ \(error.localizedDescription)") }
    await model.reloadStatus()
}

// MARK: - Google Find Hub

struct GoogleNetworkView: View {
    @Environment(AppModel.self) private var model
    @ObservedObject private var google = GoogleTrackerStore.shared
    @State private var link = GoogleLink.shared
    @State private var busy = false
    @State private var message: String?
    @State private var auth: GoogleAuthDestination?
    @State private var importLocal = false
    @State private var uploadServer = false
    @State private var confirmSignOut = false
    @State private var confirmServerDelete = false

    private var server: NetworkStatus? { model.networks?.google }
    private var cfg: GoogleNetConfig? { model.settings?.networks?.google }

    var body: some View {
        Form {
            Section {
                NetworkHero(network: .google, title: "Google Find Hub",
                            subtitle: google.hasCredentials ? (google.account ?? "Angemeldet") : (server?.secrets == true ? "Nur Server-Zugang" : "Nicht verbunden"),
                            ok: google.hasCredentials && !google.needsKeys || server?.serverReady == true)
                Toggle("Google-Netz verwenden", isOn: Binding(get: { model.networkEnabled(.google) },
                                                              set: { v in Task { await model.setNetworkEnabled(.google, v) } }))
            } footer: {
                Text("Die Ortung läuft direkt auf diesem iPhone: Anmeldung bei Google, Schlüssel entsperren, Standorte lokal entschlüsseln. Der Server speichert den Verlauf und kann als Fallback selbst orten.")
            }

            localSection
            if google.hasCredentials { trackerSection }
            serverSection

            if let error = message ?? google.errorMessage {
                Section { Text(error).font(.footnote).foregroundStyle(.orange).textSelection(.enabled) }
            }
            if google.hasCredentials {
                Section {
                    Button("Google auf diesem iPhone abmelden", role: .destructive) { confirmSignOut = true }
                }
            }
        }
        .navigationTitle("Google")
        .navigationBarTitleDisplayMode(.inline)
        .disabled(busy)
        .overlay { if busy { ProgressView(google.statusMessage ?? "Bitte warten …").padding(24).glassEffect(.regular, in: .rect(cornerRadius: 22)) } }
        .sheet(item: $auth) { GoogleAuthenticationView(destination: $0) }
        .sheet(isPresented: $importLocal) {
            DocumentPicker { urls in
                importLocal = false
                run { try await google.importSecrets(try Self.read(urls)); link.schedule(1); message = "✅ Zugang importiert" }
            } onCancel: { importLocal = false }.ignoresSafeArea()
        }
        .sheet(isPresented: $uploadServer) {
            DocumentPicker { urls in
                uploadServer = false
                run {
                    guard let api = model.api else { return }
                    let r: NetworkActionResult = try await api.uploadOne("/api/google/secrets", name: "secrets.json", data: try Self.read(urls))
                    await model.reloadStatus()
                    message = r.status?.toolsReady == true ? "✅ Server-Zugang gespeichert" : "✅ Gespeichert – Server richtet die Google-Ortung ein (einige Minuten)."
                }
            } onCancel: { uploadServer = false }.ignoresSafeArea()
        }
        .confirmationDialog("Google auf diesem iPhone abmelden?", isPresented: $confirmSignOut, titleVisibility: .visible) {
            Button("Abmelden", role: .destructive) { google.signOut() }
        } message: { Text("Objekte und Verlauf auf dem Server bleiben erhalten.") }
        .confirmationDialog("Google-Zugang vom Server löschen?", isPresented: $confirmServerDelete, titleVisibility: .visible) {
            Button("Löschen", role: .destructive) {
                run { let _: NetworkActionResult = try await model.api!.send("DELETE", "/api/google/secrets"); await model.reloadStatus() }
            }
        } message: { Text("Die Server-Ortung stoppt. Objekte und Verlauf bleiben erhalten.") }
        .task {
            GoogleLink.inUse = true
            GoogleLink.shared.attach(model)
            await google.restoreIfNeeded()
            await model.reloadStatus()
        }
        .task(id: server?.setup?.status) {
            // Einrichtung läuft → Status regelmäßig nachladen
            while server?.setup?.status == "running" && !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                await model.reloadStatus()
            }
        }
    }

    // Lokal (iPhone) -----------------------------------------------------------------
    @ViewBuilder private var localSection: some View {
        Section {
            if google.hasCredentials {
                if google.needsKeys {
                    Label("Schlüssel noch gesperrt – Standorte können noch nicht entschlüsselt werden.", systemImage: "lock.fill")
                        .foregroundStyle(.orange).font(.subheadline)
                    Button { run { auth = GoogleAuthDestination(url: try await google.recoveryURL(), recovery: true) } } label: {
                        Label("Schlüssel entsperren (Displaysperre eines Android-Geräts)", systemImage: "key.fill")
                    }
                }
                Button {
                    run { Haptics.soft(); await google.refresh(); await google.refreshLocations(); await link.push(force: true) }
                } label: { Label("Tracker & Standorte aktualisieren", systemImage: "arrow.clockwise") }
                Picker(selection: $google.refreshInterval) {
                    Text("Manuell").tag(0); Text("Alle 30 Sekunden").tag(30); Text("Jede Minute").tag(60)
                    Text("Alle 2 Minuten").tag(120); Text("Alle 5 Minuten").tag(300); Text("Alle 15 Minuten").tag(900)
                } label: { Label("Automatisch orten", systemImage: "timer") }
                Picker(selection: $google.contributorMode) {
                    Text("Alle Bereiche").tag("AtAllAreas"); Text("Adaptiv").tag("Adaptive"); Text("Nur belebte Bereiche").tag("HighTrafficOnly")
                } label: { Label("Google-Meldungen", systemImage: "person.3.fill") }
                Button { run { auth = GoogleAuthDestination(url: try await google.prepareLogin(), recovery: false) } } label: {
                    Label("Anmeldung erneuern", systemImage: "person.badge.key.fill")
                }
                Button { run { try await google.repairConnection(); message = "✅ Verbindung repariert" } } label: {
                    Label("Verbindung reparieren", systemImage: "wrench.and.screwdriver")
                }
            } else {
                Button {
                    run { auth = GoogleAuthDestination(url: try await google.prepareLogin(), recovery: false) }
                } label: {
                    Label("Bei Google anmelden", systemImage: "person.badge.key.fill").font(.headline)
                }
                Button { importLocal = true } label: {
                    Label("secrets.json importieren", systemImage: "doc.badge.plus")
                }
            }
        } header: {
            Text("Auf diesem iPhone")
        } footer: {
            Text(google.hasCredentials
                 ? "„Adaptiv“ fragt zuerst Geräte in der Nähe und fällt automatisch auf „Alle Bereiche“ zurück, wenn keine Antwort kommt. Automatisches Orten läuft, solange die App geöffnet ist."
                 : "Die Anmeldung läuft auf der echten Google-Seite. Token und Schlüssel bleiben im Schlüsselbund dieses iPhones. Danach einmal die Schlüssel mit der Displaysperre eines deiner Android-Geräte entsperren.")
        }
    }

    // Tracker ----------------------------------------------------------------------------
    @ViewBuilder private var trackerSection: some View {
        Section {
            if google.trackers.isEmpty {
                Text("Noch keine Tracker geladen.").foregroundStyle(.secondary)
            }
            ForEach(google.trackers) { t in
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 12) {
                        Image(systemName: TrackerNetwork.google.trackerSymbol)
                            .foregroundStyle(TrackerNetwork.google.color.gradient)
                            .frame(width: 38, height: 38)
                            .background(Color(.tertiarySystemFill), in: .circle)
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 6) {
                                Text(t.name).font(.headline).lineLimit(1)
                                if t.nearby { Text("IN DER NÄHE").font(.system(size: 9, weight: .heavy)).foregroundStyle(.green) }
                                if !t.unlocked { Image(systemName: "lock.fill").font(.caption).foregroundStyle(.orange) }
                            }
                            Group {
                                if let d = t.reportedAt { AgeText(date: d) } else { Text("Noch kein Standort").foregroundStyle(.secondary) }
                            }
                            .font(.caption)
                            if let st = google.locationStatus[t.id] {
                                Text(st).font(.caption2).foregroundStyle(.secondary).lineLimit(2)
                            }
                        }
                        Spacer()
                        if google.locating.contains(t.id) {
                            ProgressView()
                        } else {
                            Button {
                                Haptics.soft()
                                Task { await google.refreshLocation(t.id); await link.push(force: true) }
                            } label: {
                                Image(systemName: "location.magnifyingglass").frame(width: 36, height: 36)
                            }
                            .buttonStyle(.plain)
                            .glassEffect(.regular.interactive(), in: .circle)
                        }
                    }
                    Toggle(isOn: Binding(get: { t.historyEnabled }, set: { google.setHistoryEnabled(t.id, enabled: $0) })) {
                        Text("Automatisch orten & Verlauf sammeln").font(.subheadline)
                    }
                }
                .padding(.vertical, 2)
                .contextMenu {
                    if t.nearby {
                        Button { run { try await google.ring(t.id) } } label: { Label("Klingeln", systemImage: "speaker.wave.2.fill") }
                    }
                    Button { google.requestBluetooth() } label: { Label("Bluetooth-Nahsuche erlauben", systemImage: "dot.radiowaves.left.and.right") }
                }
            }
        } header: {
            Text("Google-Tracker · \(google.trackers.count)")
        } footer: {
            Text("Optional pro Tracker: automatische Ortung mit gesammeltem Standortverlauf. Gedrückt halten für Klingeln (Bluetooth, in der Nähe).")
        }
    }

    // Server -------------------------------------------------------------------------------
    @ViewBuilder private var serverSection: some View {
        Section {
            Toggle(isOn: $link.syncToServer) {
                Label("Standorte an den Server senden", systemImage: "arrow.up.circle")
            }
            if link.syncToServer {
                Toggle(isOn: $link.sendHistory) {
                    Label("Gesammelten Verlauf mitsenden (optional)", systemImage: "clock.arrow.circlepath")
                }
                if let p = link.lastPush {
                    LabeledContent("Zuletzt gesendet", value: "\(p.relativeDE) · \(link.lastPushCount) neu")
                        .font(.subheadline)
                }
                if let e = link.lastError { Text(e).font(.caption).foregroundStyle(.orange) }
            }
        } header: {
            Text("Server & Verlauf")
        } footer: {
            Text("Gesendete Standorte erscheinen als Objekte mit Verlauf, Aufenthalten und Alarmen – auch in der Web-App. Ohne „Verlauf mitsenden“ wird jeweils nur der neueste Standort übertragen.")
        }

        Section {
            LabeledContent("Server-Zugang", value: server?.secrets == true ? (server?.account ?? "vorhanden") : "keiner")
            LabeledContent("Ortungsdienst", value: setupText)
            if let m = server?.setup?.message, !m.isEmpty, server?.setup?.status != "success" {
                Text(m).font(.caption).foregroundStyle(server?.setup?.status == "error" ? .orange : .secondary)
            }
            if google.hasCredentials {
                Button {
                    run { _ = try await link.handOverToServer(); message = "✅ Zugang an den Server übergeben" }
                } label: { Label("Zugang an Server übergeben", systemImage: "arrow.right.circle.fill") }
                    .disabled(google.needsKeys)
            }
            Button { uploadServer = true } label: { Label("secrets.json an Server senden", systemImage: "square.and.arrow.up") }
            if server?.secrets == true && server?.toolsReady != true && server?.setup?.status != "running" {
                Button {
                    run { _ = try await model.networkAction("/api/google/setup"); message = "Einrichtung gestartet – das dauert einige Minuten." }
                } label: { Label("Server-Ortung einrichten", systemImage: "hammer.fill") }
            }
            if let c = cfg {
                Picker(selection: Binding(get: { c.serverMode }, set: { v in Task { await updateNetworks(model) { $0.google.serverMode = v } } })) {
                    Text("Automatisch (Fallback)").tag("auto")
                    Text("Immer").tag("always")
                    Text("Aus").tag("off")
                } label: { Label("Server ortet", systemImage: "server.rack") }
                Picker(selection: Binding(get: { c.interval }, set: { v in Task { await updateNetworks(model) { $0.google.interval = v } } })) {
                    Text("5 min").tag(300); Text("10 min").tag(600); Text("15 min").tag(900); Text("30 min").tag(1800); Text("1 h").tag(3600)
                } label: { Label("Intervall", systemImage: "timer") }
            }
            if server?.serverReady == true {
                Button { run { let r = try await model.networkAction("/api/google/sync", timeout: 150); message = "✅ \(r.trackers ?? 0) Tracker · \(r.added ?? 0) neu" } } label: {
                    Label("Tracker-Liste vom Server laden", systemImage: "list.bullet.rectangle")
                }
            }
            Button { run { _ = try await model.networkAction("/api/google/sync", json: ["restore": true], timeout: 150); message = "✅ Ausgeblendete Tracker wieder da" } } label: {
                Label("Alle Tracker wieder anzeigen", systemImage: "arrow.uturn.backward")
            }
            .disabled(server?.serverReady != true)
            if let e = server?.error { Text(e).font(.caption).foregroundStyle(.orange) }
            if server?.secrets == true {
                Button("Server-Zugang löschen", role: .destructive) { confirmServerDelete = true }
            }
        } header: {
            Text("Server-Ortung (Fallback)")
        } footer: {
            Text("„Automatisch“: Der Server ortet nur, wenn diese App länger als \(cfg?.appGraceMin ?? 30) Minuten nichts geliefert hat (z. B. iPhone im Hintergrund). Dafür nutzt er GoogleFindMyTools in einer eigenen Python-Umgebung. Firewall: siehe README.")
        }
    }

    private var setupText: String {
        if server?.toolsReady == true { return "bereit" }
        switch server?.setup?.status {
        case "running": return "wird eingerichtet …"
        case "error": return "Fehler"
        default: return "nicht eingerichtet"
        }
    }

    static func read(_ urls: [URL]) throws -> Data {
        guard let u = urls.first else { throw APIError.http(0, "Keine Datei gewählt", needTotp: false) }
        let ok = u.startAccessingSecurityScopedResource()
        defer { if ok { u.stopAccessingSecurityScopedResource() } }
        let d = try Data(contentsOf: u)
        guard d.count < 2_000_000 else { throw APIError.http(0, "Datei zu groß", needTotp: false) }
        return d
    }

    private func run(_ op: @escaping @MainActor () async throws -> Void) {
        busy = true; message = nil; google.clearError()
        Task { @MainActor in
            defer { busy = false }
            do { try await op() } catch { if !(error is CancellationError) { message = "⚠️ \(error.localizedDescription)" } }
        }
    }
}

struct GoogleAuthDestination: Identifiable { let id = UUID(); let url: URL; let recovery: Bool }

/// Google-Anmeldung bzw. Schlüssel-Entsperrung auf der echten Google-Seite (aus RJ TrackerApp).
struct GoogleAuthenticationView: View {
    let destination: GoogleAuthDestination
    @Environment(\.dismiss) private var dismiss
    @State private var message: String?
    @State private var busy = false
    @State private var webID = UUID()

    var body: some View {
        NavigationStack {
            GoogleAccountWebView(url: destination.url, recovery: destination.recovery) { value in
                guard !busy else { return }
                busy = true; message = nil
                Task { @MainActor in
                    defer { busy = false }
                    do {
                        if destination.recovery { try await GoogleTrackerStore.shared.recoverKeys(vaultKeys: value) }
                        else { try await GoogleTrackerStore.shared.finishLogin(oauthToken: value) }
                        Haptics.success()
                        GoogleLink.shared.schedule(3)
                        dismiss()
                    } catch { message = error.localizedDescription }
                }
            }
            .id(webID)
            .safeAreaInset(edge: .top) {
                VStack(spacing: 8) {
                    if busy {
                        ProgressView(destination.recovery ? "Schlüssel werden geprüft …" : "Anmeldung wird gespeichert …")
                    }
                    if let message {
                        Text(message).font(.footnote).foregroundStyle(.orange).multilineTextAlignment(.center)
                        Button("Noch einmal versuchen") { self.message = nil; webID = UUID() }.buttonStyle(.glass)
                    }
                }
                .padding(busy || message != nil ? 12 : 0)
                .frame(maxWidth: .infinity)
                .glassEffect(busy || message != nil ? .regular : .identity, in: .rect(cornerRadius: 20))
                .padding(.horizontal, busy || message != nil ? 12 : 0)
            }
            .navigationTitle(destination.recovery ? "Schlüssel entsperren" : "Google anmelden")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Schließen") { dismiss() } } }
        }
    }
}

struct GoogleAccountWebView: UIViewRepresentable {
    let url: URL
    let recovery: Bool
    let onResult: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "googleVault")
        if recovery {
            config.userContentController.addUserScript(WKUserScript(
                source: "window.mm={setVaultSharedKeys:function(s,k){window.webkit.messageHandlers.googleVault.postMessage(k);}};",
                injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        context.coordinator.start(view)
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) { context.coordinator.parent = self }

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        coordinator.timer?.invalidate()
        view.stopLoading()
        view.configuration.userContentController.removeScriptMessageHandler(forName: "googleVault")
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        var parent: GoogleAccountWebView
        var timer: Timer?
        var lastValue: String?
        init(_ parent: GoogleAccountWebView) { self.parent = parent }

        func start(_ view: WKWebView) {
            guard !parent.recovery else { return }
            timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self, weak view] _ in
                guard let self, view != nil else { return }
                WKWebsiteDataStore.default().httpCookieStore.getAllCookies { [weak self] cookies in
                    guard let self, let cookie = cookies.first(where: { GoogleTrackerStore.isOAuthCookie($0) }),
                          self.lastValue != cookie.value else { return }
                    self.lastValue = cookie.value
                    DispatchQueue.main.async { self.parent.onResult(cookie.value) }
                }
            }
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            let origin = message.frameInfo.securityOrigin
            guard parent.recovery, message.frameInfo.isMainFrame, origin.protocol == "https", origin.host == "accounts.google.com" else { return }
            if let value = message.body as? String { parent.onResult(value) }
            else if JSONSerialization.isValidJSONObject(message.body),
                    let data = try? JSONSerialization.data(withJSONObject: message.body),
                    let value = String(data: data, encoding: .utf8) { parent.onResult(value) }
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if parent.recovery, navigationAction.request.url?.host == "myaccount.google.com" {
                webView.load(URLRequest(url: parent.url))
                decisionHandler(.cancel)
            } else {
                decisionHandler(.allow)
            }
        }
    }
}

// MARK: - Samsung SmartThings Find

struct SamsungNetworkView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @State private var busy = false
    @State private var message: String?
    @State private var login: SamsungLoginDestination?
    @State private var lastLoginURL: URL?
    @State private var manualRedirect = ""
    @State private var pin = ""
    @State private var confirmLogout = false

    private var s: NetworkStatus? { model.networks?.samsung }
    private var cfg: SamsungNetConfig? { model.settings?.networks?.samsung }
    private var connected: Bool { s?.connected == true }

    var body: some View {
        Form {
            Section {
                NetworkHero(network: .samsung, title: "SmartThings Find",
                            subtitle: connected ? (s?.account ?? "Verbunden") : "Nicht verbunden",
                            ok: connected && s?.pinRequired != true)
                Toggle("Samsung-Netz verwenden", isOn: Binding(get: { model.networkEnabled(.samsung) },
                                                               set: { v in Task { await model.setNetworkEnabled(.samsung, v) } }))
            } footer: {
                Text("Deine Galaxy SmartTags aus dem eigenen Samsung-Konto. Die Anmeldung erfolgt direkt hier in der App; der Server ruft danach die Standorte ab und speichert den Verlauf.")
            }

            if connected { connectedSection } else { loginSection }

            Section {
                if s?.pin == true {
                    Label("PIN gespeichert", systemImage: "checkmark.shield.fill").foregroundStyle(.green)
                    Button("PIN entfernen", role: .destructive) {
                        run { let _: NetworkActionResult = try await model.api!.send("DELETE", "/api/samsung/pin"); await model.reloadStatus() }
                    }
                }
                if s?.pinRequired == true {
                    Label("Standorte sind Ende-zu-Ende verschlüsselt – PIN nötig.", systemImage: "lock.fill").foregroundStyle(.orange)
                }
                SecureField("Samsung-Find-PIN", text: $pin)
                    .keyboardType(.numberPad).textContentType(.oneTimeCode)
                Button("PIN speichern") {
                    run {
                        _ = try await model.networkAction("/api/samsung/pin", json: ["pin": pin])
                        pin = ""
                        message = "✅ PIN gespeichert – Standorte werden entschlüsselt."
                    }
                }
                .disabled(pin.isEmpty)
            } header: {
                Text("Verschlüsselung")
            } footer: {
                Text("Nur nötig, wenn in SmartThings „Standorte verschlüsseln“ aktiv ist. Es ist die PIN, die du dort festgelegt hast. Sie wird nur auf deinem Server gespeichert.")
            }

            if let c = cfg {
                Section {
                    Toggle(isOn: Binding(get: { c.history }, set: { v in Task { await updateNetworks(model) { $0.samsung.history = v } } })) {
                        Label("Standortverlauf von Samsung laden (optional)", systemImage: "clock.arrow.circlepath")
                    }
                    Picker(selection: Binding(get: { c.interval }, set: { v in Task { await updateNetworks(model) { $0.samsung.interval = v } } })) {
                        Text("30 s").tag(30); Text("1 min").tag(60); Text("2 min").tag(120); Text("5 min").tag(300); Text("15 min").tag(900)
                    } label: { Label("Abruf alle", systemImage: "timer") }
                } header: {
                    Text("Abruf")
                } footer: {
                    Text("Mit Verlauf holt der Server zusätzlich die von Samsung gespeicherten Standorte der letzten 7 Tage – so fehlen keine Punkte, wenn der Server zwischendurch aus war.")
                }
            }

            if let message { Section { Text(message).font(.footnote).textSelection(.enabled) } }
            if let e = s?.error, message == nil { Section { Text(e).font(.footnote).foregroundStyle(.orange) } }

            if connected {
                Section { Button("Samsung-Konto trennen", role: .destructive) { confirmLogout = true } }
            }
        }
        .navigationTitle("Samsung")
        .navigationBarTitleDisplayMode(.inline)
        .disabled(busy)
        .overlay { if busy { ProgressView().controlSize(.large).padding(30).glassEffect(.regular, in: .rect(cornerRadius: 24)) } }
        .sheet(item: $login) { dest in
            SamsungLoginView(url: dest.url) { redirect in
                login = nil
                complete(redirect)
            }
        }
        .confirmationDialog("Samsung-Konto trennen?", isPresented: $confirmLogout, titleVisibility: .visible) {
            Button("Trennen", role: .destructive) {
                run { _ = try await model.networkAction("/api/samsung/logout"); message = "Samsung-Konto getrennt." }
            }
        } message: { Text("Objekte und Verlauf bleiben erhalten.") }
        .task { await model.reloadStatus() }
    }

    @ViewBuilder private var loginSection: some View {
        Section {
            Button {
                run {
                    guard let api = model.api else { return }
                    let r: SamsungLoginStart = try await api.send("POST", "/api/samsung/login", timeout: 40)
                    guard let u = URL(string: r.loginUrl) else { return }
                    lastLoginURL = u
                    login = SamsungLoginDestination(url: u)
                }
            } label: {
                Label("Mit Samsung-Konto anmelden", systemImage: "person.badge.key.fill").font(.headline)
            }
        } header: {
            Text("Anmelden")
        } footer: {
            Text("Melde dich auf der Samsung-Seite an. Die Rückleitung wird automatisch abgefangen – kein Kopieren nötig.")
        }
        Section {
            if let u = lastLoginURL {
                Button { openURL(u) } label: { Label("Login stattdessen in Safari öffnen", systemImage: "safari") }
                ShareLink(item: u) { Label("Login-Link teilen", systemImage: "square.and.arrow.up") }
            }
            TextField("ms-app://…?state=…&code=…", text: $manualRedirect, axis: .vertical)
                .font(.caption.monospaced()).lineLimit(2...4)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            HStack {
                Button { manualRedirect = UIPasteboard.general.string ?? "" } label: { Label("Einfügen", systemImage: "doc.on.clipboard") }
                    .buttonStyle(.glass)
                Spacer()
                Button("Anmeldung abschließen") { complete(manualRedirect) }
                    .buttonStyle(.glassProminent)
                    .disabled(manualRedirect.isEmpty)
            }
        } header: {
            Text("Falls die Anmeldung hängen bleibt")
        } footer: {
            Text("Login in Safari oder am Computer öffnen, anmelden, dann die Adresse kopieren, auf die Samsung weiterleitet (beginnt mit „ms-app://“), und hier einfügen. Gültig 30 Minuten.")
        }
    }

    @ViewBuilder private var connectedSection: some View {
        Section {
            LabeledContent("Konto", value: s?.account ?? "–")
            LabeledContent("SmartTags", value: "\(s?.devices ?? 0)")
            if let t = s?.lastRefresh {
                LabeledContent("Letzter Abruf", value: Date(timeIntervalSince1970: t).relativeDE)
            }
            Button {
                run { let r = try await model.networkAction("/api/samsung/refresh", timeout: 120); Haptics.success(); message = "✅ \(r.new ?? 0) neue Standorte" }
            } label: { Label("Jetzt abrufen", systemImage: "arrow.clockwise") }
            Button {
                run { let r = try await model.networkAction("/api/samsung/sync", timeout: 90); message = "✅ \(r.tags ?? 0) SmartTags · \(r.added ?? 0) neu" }
            } label: { Label("Geräteliste neu laden", systemImage: "list.bullet.rectangle") }
            Button {
                run { _ = try await model.networkAction("/api/samsung/sync", json: ["restore": true], timeout: 90); message = "✅ Ausgeblendete SmartTags wieder da" }
            } label: { Label("Alle Tracker wieder anzeigen", systemImage: "arrow.uturn.backward") }
            Button {
                run {
                    guard let api = model.api else { return }
                    let r: SamsungLoginStart = try await api.send("POST", "/api/samsung/login", timeout: 40)
                    if let u = URL(string: r.loginUrl) { lastLoginURL = u; login = SamsungLoginDestination(url: u) }
                }
            } label: { Label("Neu anmelden", systemImage: "person.badge.key") }
        } header: {
            Text("Verbunden")
        }
    }

    private func complete(_ redirect: String) {
        run {
            guard let api = model.api else { return }
            var body: [String: Any] = ["redirect_url": redirect]
            if !pin.isEmpty { body["pin"] = pin }
            let r: NetworkActionResult = try await api.send("POST", "/api/samsung/complete", json: body, timeout: 120)
            manualRedirect = ""
            Haptics.success()
            message = "✅ Samsung verbunden · \(r.tags ?? 0) SmartTags gefunden"
            await model.reloadStatus()
            await model.reloadDevices()
        }
    }

    private func run(_ op: @escaping @MainActor () async throws -> Void) {
        busy = true; message = nil
        Task { @MainActor in
            defer { busy = false }
            do { try await op() } catch { Haptics.warning(); message = "⚠️ \(error.localizedDescription)" }
        }
    }
}

struct SamsungLoginDestination: Identifiable { let id = UUID(); let url: URL }

/// Samsung-Login im In-App-Browser. Die Rückleitung „ms-app://…“ wird abgefangen.
struct SamsungLoginView: View {
    let url: URL
    let onRedirect: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var loading = true

    var body: some View {
        NavigationStack {
            SamsungWebView(url: url, loading: $loading, onRedirect: onRedirect)
                .ignoresSafeArea(edges: .bottom)
                .overlay(alignment: .top) {
                    if loading {
                        ProgressView().padding(12).glassEffect(.regular, in: .circle).padding(.top, 8)
                    }
                }
                .navigationTitle("Samsung-Konto")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } } }
        }
    }
}

struct SamsungWebView: UIViewRepresentable {
    let url: URL
    @Binding var loading: Bool
    let onRedirect: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: config)
        view.customUserAgent = "Mozilla/5.0 (Linux; Android 15; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36"
        view.navigationDelegate = context.coordinator
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) { context.coordinator.parent = self }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var parent: SamsungWebView
        private var done = false
        init(_ parent: SamsungWebView) { self.parent = parent }

        private func isRedirect(_ s: String) -> Bool {
            s.lowercased().hasPrefix("ms-app:") || (s.contains("retValue=") && s.contains("auth_server_url=") && s.contains("code="))
        }

        private func finish(_ s: String) {
            guard !done else { return }
            done = true
            DispatchQueue.main.async { self.parent.onRedirect(s) }
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if let s = navigationAction.request.url?.absoluteString, isRedirect(s) {
                decisionHandler(.cancel)
                finish(s)
                return
            }
            decisionHandler(.allow)
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            DispatchQueue.main.async { self.parent.loading = true }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            DispatchQueue.main.async { self.parent.loading = false }
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            DispatchQueue.main.async { self.parent.loading = false }
            let ns = error as NSError
            if let s = ns.userInfo[NSURLErrorFailingURLStringErrorKey] as? String, isRedirect(s) { finish(s) }
        }
    }
}
