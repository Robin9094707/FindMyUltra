import SwiftUI
import AuthenticationServices

struct ConnectView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.webAuthenticationSession) private var webAuth

    @State private var server = ""
    @State private var username = "admin"
    @State private var password = ""
    @State private var totp = ""
    @State private var needTotp = false
    @State private var health: HealthInfo?
    @State private var busy = false
    @State private var error: String?
    @State private var untrustedFP: String?
    @FocusState private var focus: Field?

    enum Field { case server, user, pass, totp }

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(hex: "#0A84FF"), Color(hex: "#5E5CE6"), .black],
                           startPoint: .topLeading, endPoint: .bottom)
                .ignoresSafeArea()
            ScrollView {
                VStack(spacing: 22) {
                    header
                    serverCard
                    if health != nil { loginCard }
                    if let error {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .font(.footnote)
                            .foregroundStyle(.white)
                            .padding(12)
                            .glassEffect(.regular.tint(.red.opacity(0.4)), in: .rect(cornerRadius: 16))
                    }
                    Text("Den Server startest du mit `python3 findmy_ultra.py`. Benutzer & erstes Passwort stehen in der Konsole bzw. in data/ERSTES-PASSWORT.txt.")
                        .font(.footnote).foregroundStyle(.white.opacity(0.7))
                        .multilineTextAlignment(.center).padding(.horizontal)
                }
                .padding(20)
                .padding(.top, 30)
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .onAppear { if server.isEmpty { server = model.serverURLString } }
        .alert("Zertifikat vertrauen?", isPresented: Binding(get: { untrustedFP != nil }, set: { if !$0 { untrustedFP = nil } })) {
            Button("Vertrauen") {
                if let fp = untrustedFP { model.trust(fingerprint: fp) }
                untrustedFP = nil
                Task { await check() }
            }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Der Server nutzt ein selbstsigniertes Zertifikat.\n\nSHA-256:\n\(formatFP(untrustedFP ?? ""))\n\nVergleiche den Anfang mit der Ausgabe in der Server-Konsole.")
        }
    }

    private var header: some View {
        VStack(spacing: 10) {
            Image(systemName: "dot.radiowaves.left.and.right")
                .font(.system(size: 46, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 96, height: 96)
                .glassEffect(.regular.tint(.white.opacity(0.15)), in: .rect(cornerRadius: 28))
            Text("FindMy Ultra").font(.largeTitle.bold()).foregroundStyle(.white)
            Text("Verbinde dich mit deinem Server").foregroundStyle(.white.opacity(0.8))
        }
    }

    private var serverCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Server", systemImage: "server.rack").font(.headline)
            TextField("https://findmy.example.com  oder  192.168.1.20:8787", text: $server)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .focused($focus, equals: .server)
                .submitLabel(.go)
                .onSubmit { Task { await check() } }
                .padding(12)
                .background(.white.opacity(0.08), in: .rect(cornerRadius: 14))
            HStack {
                if let h = health {
                    Label("\(h.app ?? "Server") \(h.version ?? "")\(h.demo == true ? " · Demo" : "")", systemImage: "checkmark.seal.fill")
                        .font(.footnote).foregroundStyle(.green)
                }
                Spacer()
                Button {
                    Task { await check() }
                } label: {
                    if busy && health == nil { ProgressView() } else { Text(health == nil ? "Verbinden" : "Erneut prüfen") }
                }
                .buttonStyle(.glassProminent)
                .disabled(server.isEmpty || busy)
            }
        }
        .padding(18)
        .glassEffect(.regular, in: .rect(cornerRadius: 28))
    }

    private var loginCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Anmelden", systemImage: "person.badge.key.fill").font(.headline)
            TextField("Benutzer", text: $username)
                .textContentType(.username).textInputAutocapitalization(.never).autocorrectionDisabled()
                .focused($focus, equals: .user)
                .padding(12).background(.white.opacity(0.08), in: .rect(cornerRadius: 14))
            SecureField("Passwort", text: $password)
                .textContentType(.password)
                .focused($focus, equals: .pass)
                .submitLabel(.go)
                .onSubmit { Task { await login() } }
                .padding(12).background(.white.opacity(0.08), in: .rect(cornerRadius: 14))
            if needTotp || health?.totp == true {
                TextField("2FA-Code (Authenticator)", text: $totp)
                    .textContentType(.oneTimeCode).keyboardType(.numberPad)
                    .focused($focus, equals: .totp)
                    .padding(12).background(.white.opacity(0.08), in: .rect(cornerRadius: 14))
            }
            GlassEffectContainer(spacing: 10) {
                HStack(spacing: 10) {
                    Button {
                        Task { await login() }
                    } label: {
                        HStack { if busy { ProgressView() }; Text("Anmelden").frame(maxWidth: .infinity) }
                    }
                    .buttonStyle(.glassProminent)
                    .disabled(password.isEmpty || busy)
                    if (health?.passkeys ?? 0) > 0 {
                        Button {
                            Task { await passkeyLogin() }
                        } label: {
                            Label("Passkey", systemImage: "person.badge.key")
                        }
                        .buttonStyle(.glass)
                        .disabled(busy)
                    }
                }
            }
            .controlSize(.large)
        }
        .padding(18)
        .glassEffect(.regular, in: .rect(cornerRadius: 28))
    }

    private func formatFP(_ s: String) -> String {
        stride(from: 0, to: s.count, by: 2).map { i in
            let a = s.index(s.startIndex, offsetBy: i)
            return String(s[a..<s.index(a, offsetBy: min(2, s.count - i))])
        }.joined(separator: ":")
    }

    private func check() async {
        busy = true; error = nil
        defer { busy = false }
        do {
            health = try await model.health(for: server)
            focus = .pass
        } catch APIError.untrustedCertificate(let fp) {
            untrustedFP = fp
        } catch {
            health = nil
            self.error = "Server nicht erreichbar: \(error.localizedDescription)"
        }
    }

    private func login() async {
        busy = true; error = nil
        defer { busy = false }
        do {
            try await model.login(server: server, username: username, password: password, totp: totp)
        } catch APIError.http(_, let msg, let need) {
            if need { needTotp = true; focus = .totp }
            error = msg
        } catch APIError.untrustedCertificate(let fp) {
            untrustedFP = fp
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func passkeyLogin() async {
        guard let base = APIClient.normalize(server),
              let url = URL(string: base.absoluteString + "/auth/app?action=login&callback=findmyultra") else { return }
        busy = true; error = nil
        defer { busy = false }
        do {
            let cb = try await webAuth.authenticate(using: url, callbackURLScheme: "findmyultra",
                                                    preferredBrowserSession: .ephemeral)
            guard let token = URLComponents(url: cb, resolvingAgainstBaseURL: false)?
                .queryItems?.first(where: { $0.name == "token" })?.value else {
                error = "Keine Anmeldung erhalten"
                return
            }
            try await model.finishLogin(url: base, token: token)
        } catch {
            if (error as NSError).code != ASWebAuthenticationSessionError.canceledLogin.rawValue {
                self.error = error.localizedDescription
            }
        }
    }
}
