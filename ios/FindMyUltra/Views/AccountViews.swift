import SwiftUI
import AuthenticationServices

// MARK: - Apple-Account (Login mit 2FA über den Server)

struct AppleAccountView: View {
    @Environment(AppModel.self) private var model
    @State private var apple: AppleStatus?
    @State private var email = ""
    @State private var password = ""
    @State private var anisette = ""
    @State private var methodIndex = 0
    @State private var code = ""
    @State private var busy = false
    @State private var info: String?
    @State private var error: String?

    var body: some View {
        Form {
            if let a = apple {
                switch a.state {
                case "logged_in":
                    Section {
                        Label {
                            VStack(alignment: .leading) {
                                Text([a.firstName, a.lastName].compactMap { $0 }.joined(separator: " ")).font(.headline)
                                Text(a.accountName ?? "").foregroundStyle(.secondary)
                            }
                        } icon: {
                            Image(systemName: "checkmark.seal.fill").foregroundStyle(.green)
                        }
                        Button("Standorte jetzt vollständig abrufen") {
                            Task { await model.refresh(full: true) }
                        }
                    } footer: {
                        Text("Der Server ist angemeldet und ruft die Standortberichte deiner Objekte direkt bei Apple ab. Die Sitzung wird auf dem Server gespeichert (data/apple_account.json).")
                    }
                    Section {
                        Button("Apple-Account abmelden", role: .destructive) { Task { await logout() } }
                    }
                case "require_2fa":
                    twoFactor(a)
                default:
                    loginForm(a)
                }
            } else {
                ProgressView()
            }
            if let info { Section { Text(info).foregroundStyle(.green) } }
            if let error { Section { Text(error).foregroundStyle(.red) } }
        }
        .navigationTitle("Apple-Account")
        .task { await reload() }
        .task(id: apple?.runtime?.state) {
            // Während die macOS-Komponente eingerichtet wird, Fortschritt nachladen
            while apple?.runtime?.state == "installing" && !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                await reload()
            }
        }
        .disabled(busy)
        .overlay { if busy { ProgressView().controlSize(.large).padding(30).glassEffect(.regular, in: .rect(cornerRadius: 24)) } }
    }

    /// Status der macOS-Komponente (seit Okt. 2026 für die Apple-Anmeldung nötig).
    @ViewBuilder
    private func runtimeSection(_ r: AppleRuntimeStatus?) -> some View {
        if let r, !r.isReady {
            Section {
                switch r.state ?? "" {
                case "installing":
                    VStack(alignment: .leading, spacing: 8) {
                        Label("macOS-Komponente wird eingerichtet", systemImage: "arrow.down.circle")
                            .font(.headline)
                        ProgressView(value: r.progress ?? 0)
                        Text(r.message ?? "").font(.caption).foregroundStyle(.secondary)
                    }
                default:
                    Label(r.message ?? "macOS-Komponente fehlt", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                    Button("Jetzt einrichten") { Task { await installRuntime() } }
                }
            } header: {
                Text("Vorbereitung")
            } footer: {
                Text("Apple akzeptiert seit Oktober 2026 nur noch Anmeldungen mit einer Mac-Identität. Dein Server lädt dafür einmalig Apples offiziellen iTunes-Installer (~290 MB) und nutzt daraus die Anmelde-Komponente. Danach geht die Anmeldung wie gewohnt.")
            }
        }
    }

    private func installRuntime() async {
        await run {
            apple = try await model.api!.send("POST", "/api/apple/runtime/install")
        }
    }

    @ViewBuilder
    private func loginForm(_ a: AppleStatus) -> some View {
        runtimeSection(a.runtime)
        Section {
            TextField("Apple-ID (E-Mail)", text: $email)
                .textContentType(.username).keyboardType(.emailAddress)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            SecureField("Passwort", text: $password).textContentType(.password)
            Button("Bei Apple anmelden") { Task { await login() } }
                .disabled(email.isEmpty || password.isEmpty || !(a.runtime?.isReady ?? true))
        } header: {
            Text("Anmelden")
        } footer: {
            Text("Die Zugangsdaten gehen nur an deinen eigenen Server, der sich damit bei Apple anmeldet (wie FindMy.py). Danach folgt die Zwei-Faktor-Bestätigung über ein vertrauenswürdiges Gerät oder per SMS. Bei einem Fehler nicht mehrfach direkt hintereinander versuchen – Apple sperrt sonst vorübergehend.")
        }
        if let e = a.error { Section { Text(e).foregroundStyle(.orange) } }
    }

    @ViewBuilder
    private func twoFactor(_ a: AppleStatus) -> some View {
        let methods = a.methods ?? []
        Section {
            if methods.isEmpty {
                Text("Keine 2FA-Methode gefunden – bitte erneut anmelden.")
            } else {
                Picker("Methode", selection: $methodIndex) {
                    ForEach(methods) { m in
                        Label(m.label, systemImage: m.type == "sms" ? "message.fill" : "iphone.gen3").tag(m.index)
                    }
                }
                .pickerStyle(.inline)
                Button("Code senden / anfordern") { Task { await requestCode() } }
            }
        } header: {
            Text("Zwei-Faktor-Authentifizierung")
        } footer: {
            Text("Bei „Vertrauenswürdiges Gerät“ erscheint der Code auf deinem iPhone/Mac (ggf. erst „Erlauben“ tippen).")
        }
        Section {
            TextField("6-stelliger Code", text: $code)
                .textContentType(.oneTimeCode).keyboardType(.numberPad)
                .font(.title2.monospacedDigit())
            Button("Bestätigen") { Task { await submit() } }
                .disabled(code.count < 6)
        }
        Section {
            Button("Abbrechen", role: .destructive) { Task { await logout() } }
        }
    }

    private func reload() async {
        apple = try? await model.api?.get("/api/apple/status")
        if let first = apple?.methods?.first { methodIndex = first.index }
    }

    private func run(_ op: () async throws -> Void) async {
        busy = true; error = nil; info = nil
        defer { busy = false }
        do { try await op() } catch { self.error = error.localizedDescription }
    }

    private func login() async {
        await run {
            let s: AppleStatus = try await model.api!.send("POST", "/api/apple/login",
                                                           json: ["email": email, "password": password, "anisette_server": ""],
                                                           timeout: 120)
            apple = s
            password = ""
            if let first = s.methods?.first {
                methodIndex = first.index
                // Vertrauenswürdige Geräte: Code direkt anfordern
                if first.type == "trusted_device" { try? await requestCodeRaw() }
            }
            if s.isLoggedIn { info = "✅ Angemeldet" }
            await model.reloadStatus()
        }
    }

    private func requestCodeRaw() async throws {
        let _: OKResult = try await model.api!.send("POST", "/api/apple/2fa/request", json: ["index": methodIndex])
        info = "Code angefordert"
    }

    private func requestCode() async { await run { try await requestCodeRaw() } }

    private func submit() async {
        await run {
            let s: AppleStatus = try await model.api!.send("POST", "/api/apple/2fa/submit",
                                                           json: ["index": methodIndex, "code": code], timeout: 120)
            apple = s
            code = ""
            if s.isLoggedIn {
                info = "✅ Angemeldet – der erste 7-Tage-Scan läuft."
                await model.reloadStatus()
            }
        }
    }

    private func logout() async {
        await run {
            let _: OKResult = try await model.api!.send("POST", "/api/apple/logout")
            await reload()
            await model.reloadStatus()
        }
    }
}

// MARK: - Sicherheit (Passwort, TOTP, Passkeys, Sitzungen)

struct SecurityView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.webAuthenticationSession) private var webAuth
    @Environment(\.openURL) private var openURL

    @State private var current = ""
    @State private var newPW = ""
    @State private var newPW2 = ""
    @State private var newUser = ""
    @State private var pwTotp = ""
    @State private var totpSetup: TOTPSetup?
    @State private var totpCode = ""
    @State private var disablePW = ""
    @State private var busy = false
    @State private var message: String?

    var body: some View {
        Form {
            if let me = model.me {
                passwordSection(me)
                totpSection(me)
                passkeySection(me)
                sessionsSection(me)
            } else {
                ProgressView()
            }
            if let message { Section { Text(message) } }
        }
        .navigationTitle("Sicherheit")
        .task { await model.reloadMe() }
        .disabled(busy)
    }

    private func passwordSection(_ me: MeInfo) -> some View {
        Section {
            SecureField("Aktuelles Passwort", text: $current).textContentType(.password)
            TextField("Neuer Benutzername (optional)", text: $newUser)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            SecureField("Neues Passwort (min. 8 Zeichen)", text: $newPW).textContentType(.newPassword)
            SecureField("Neues Passwort wiederholen", text: $newPW2).textContentType(.newPassword)
            if me.totpEnabled {
                TextField("2FA-Code", text: $pwTotp).keyboardType(.numberPad).textContentType(.oneTimeCode)
            }
            Button("Passwort ändern") { Task { await changePassword() } }
                .disabled(current.isEmpty || newPW.count < 8 || newPW != newPW2)
        } header: {
            Text("Passwort · \(me.username)")
        } footer: {
            Text(me.passwordIsGenerated
                 ? "Du nutzt noch das generierte Passwort. Tipp: Löschst du data/credentials.json auf dem Server, werden beim Neustart neue Zugangsdaten erzeugt."
                 : "Andere Sitzungen werden dabei abgemeldet. Zugangsdaten vergessen? data/credentials.json auf dem Server löschen und neu starten.")
        }
    }

    @ViewBuilder
    private func totpSection(_ me: MeInfo) -> some View {
        Section {
            if me.totpEnabled {
                Label("Zwei-Faktor aktiv", systemImage: "checkmark.shield.fill").foregroundStyle(.green)
                SecureField("Passwort zum Deaktivieren", text: $disablePW)
                Button("2FA deaktivieren", role: .destructive) { Task { await disableTOTP() } }
                    .disabled(disablePW.isEmpty)
            } else if let s = totpSetup {
                VStack(spacing: 12) {
                    QRCodeView(text: s.uri).frame(width: 200, height: 200)
                        .padding(10).background(.white, in: .rect(cornerRadius: 16))
                    Text(s.secret).font(.footnote.monospaced()).textSelection(.enabled)
                    HStack {
                        Button("In Passwörter öffnen") { if let u = URL(string: s.uri) { openURL(u) } }
                            .buttonStyle(.glass)
                        Button { UIPasteboard.general.string = s.secret; model.showToast("Schlüssel kopiert") } label: {
                            Image(systemName: "doc.on.doc")
                        }
                        .buttonStyle(.glass)
                    }
                }
                .frame(maxWidth: .infinity)
                TextField("Code aus der Authenticator-App", text: $totpCode)
                    .keyboardType(.numberPad).textContentType(.oneTimeCode)
                Button("Aktivieren") { Task { await enableTOTP() } }.disabled(totpCode.count < 6)
            } else {
                Button("2FA einrichten (Authenticator / Passwörter-App)") { Task { await setupTOTP() } }
            }
        } header: {
            Text("Zwei-Faktor (TOTP)")
        } footer: {
            Text("Optional. Funktioniert mit der Passwörter-App von iOS, Google Authenticator, 1Password usw.")
        }
    }

    private func passkeySection(_ me: MeInfo) -> some View {
        Section {
            ForEach(me.passkeys) { p in
                VStack(alignment: .leading) {
                    Text(p.name)
                    Text("Erstellt \(p.created?.prefix(10) ?? "–") · \(p.rpId ?? "")").font(.caption).foregroundStyle(.secondary)
                }
                .swipeActions {
                    Button("Löschen", role: .destructive) { Task { await deletePasskey(p.id) } }
                }
            }
            Button {
                Task { await addPasskey() }
            } label: {
                Label("Passkey hinzufügen", systemImage: "person.badge.key.fill")
            }
        } header: {
            Text("Passkeys")
        } footer: {
            Text("Passkeys brauchen eine HTTPS-Adresse mit gültigem Zertifikat (z. B. über Caddy, Tailscale oder Cloudflare Tunnel). Die Anmeldung läuft über eine sichere Safari-Ansicht.")
        }
    }

    private func sessionsSection(_ me: MeInfo) -> some View {
        Section("Angemeldete Geräte") {
            ForEach(me.sessions) { s in
                VStack(alignment: .leading) {
                    HStack {
                        Text(s.label ?? "Sitzung").lineLimit(1)
                        if s.current { Text("diese").font(.caption2.bold()).foregroundStyle(.green) }
                    }
                    Text("\(s.ip ?? "") · zuletzt \(Date(timeIntervalSince1970: s.lastUsed).relativeDE)")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .swipeActions {
                    if !s.current {
                        Button("Abmelden", role: .destructive) { Task { await revoke(s.id) } }
                    }
                }
            }
        }
    }

    // MARK: Aktionen

    private func run(_ op: () async throws -> Void) async {
        busy = true; message = nil
        defer { busy = false }
        do { try await op() } catch { message = "⚠️ \(error.localizedDescription)" }
        await model.reloadMe()
    }

    private func changePassword() async {
        await run {
            var body: [String: Any] = ["current": current, "new": newPW, "totp": pwTotp]
            if !newUser.isEmpty { body["username"] = newUser }
            let _: OKResult = try await model.api!.send("POST", "/api/auth/password", json: body)
            current = ""; newPW = ""; newPW2 = ""; pwTotp = ""; newUser = ""
            message = "✅ Passwort geändert"
        }
    }

    private func setupTOTP() async {
        await run { totpSetup = try await model.api!.send("POST", "/api/auth/totp/setup") }
    }

    private func enableTOTP() async {
        await run {
            let _: OKResult = try await model.api!.send("POST", "/api/auth/totp/enable", json: ["code": totpCode])
            totpSetup = nil; totpCode = ""
            message = "✅ Zwei-Faktor aktiviert"
        }
    }

    private func disableTOTP() async {
        await run {
            let _: OKResult = try await model.api!.send("POST", "/api/auth/totp/disable", json: ["password": disablePW])
            disablePW = ""
            message = "Zwei-Faktor deaktiviert"
        }
    }

    private func addPasskey() async {
        await run {
            let link: LinkCode = try await model.api!.send("POST", "/api/auth/link")
            guard let base = model.api?.baseURL,
                  let url = URL(string: base.absoluteString + "/auth/app?action=register&callback=findmyultra&code=\(link.code)")
            else { return }
            do {
                let cb = try await webAuth.authenticate(using: url, callbackURLScheme: "findmyultra",
                                                        preferredBrowserSession: .ephemeral)
                let ok = URLComponents(url: cb, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "ok" }?.value == "1"
                message = ok ? "✅ Passkey gespeichert" : "Passkey wurde nicht gespeichert"
            } catch {
                if (error as NSError).code != ASWebAuthenticationSessionError.canceledLogin.rawValue { throw error }
            }
        }
    }

    private func deletePasskey(_ id: String) async {
        await run {
            let enc = id.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? id
            let _: OKResult = try await model.api!.send("DELETE", "/api/auth/passkeys/\(enc)")
        }
    }

    private func revoke(_ id: String) async {
        await run { let _: OKResult = try await model.api!.send("DELETE", "/api/auth/sessions/\(id)") }
    }
}
