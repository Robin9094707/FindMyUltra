import Foundation
import CryptoKit
import Security

enum APIError: LocalizedError {
    case invalidURL
    case http(Int, String, needTotp: Bool)
    case untrustedCertificate(fingerprint: String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: "Ungültige Server-Adresse"
        case .http(let code, let msg, _): code == 0 ? msg : "\(msg) (\(code))"
        case .untrustedCertificate(let fp): "Unbekanntes Zertifikat (SHA-256 \(fp.prefix(16))…)"
        case .decoding(let s): "Antwort unlesbar: \(s)"
        }
    }

    var isUnauthorized: Bool { if case .http(401, _, _) = self { return true }; return false }
}

/// HTTP-Client für den FindMy-Ultra-Server inkl. Zertifikats-Pinning (selbstsignierte Zertifikate).
final class APIClient: NSObject, URLSessionDelegate, @unchecked Sendable {
    var baseURL: URL
    var token: String?
    var pinnedFingerprint: String?
    private(set) var lastUntrustedFingerprint: String?

    private lazy var session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 60
        cfg.timeoutIntervalForResource = 3600 * 6
        cfg.waitsForConnectivity = false
        cfg.httpCookieAcceptPolicy = .never
        return URLSession(configuration: cfg, delegate: self, delegateQueue: nil)
    }()

    let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    init(baseURL: URL, token: String? = nil, pinnedFingerprint: String? = nil) {
        self.baseURL = baseURL
        self.token = token
        self.pinnedFingerprint = pinnedFingerprint
    }

    static func normalize(_ input: String) -> URL? {
        var s = input.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.isEmpty { return nil }
        if !s.lowercased().hasPrefix("http://") && !s.lowercased().hasPrefix("https://") {
            s = "http://" + s
        }
        while s.hasSuffix("/") { s.removeLast() }
        guard let u = URL(string: s), u.host != nil else { return nil }
        return u
    }

    func url(_ path: String, query: [URLQueryItem] = []) throws -> URL {
        guard var c = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { throw APIError.invalidURL }
        c.path = (c.path.hasSuffix("/") ? String(c.path.dropLast()) : c.path) + path
        if !query.isEmpty { c.queryItems = query }
        guard let u = c.url else { throw APIError.invalidURL }
        return u
    }

    // MARK: Requests

    func raw(_ method: String, _ path: String, query: [URLQueryItem] = [], body: Data? = nil,
             contentType: String = "application/json", timeout: TimeInterval = 60) async throws -> Data {
        var req = URLRequest(url: try url(path, query: query))
        req.httpMethod = method
        req.timeoutInterval = timeout
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            req.httpBody = body
            req.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }
        let data: Data
        let resp: URLResponse
        do {
            (data, resp) = try await session.data(for: req)
        } catch {
            if let fp = lastUntrustedFingerprint, fp != pinnedFingerprint?.uppercased(), error is URLError {
                throw APIError.untrustedCertificate(fingerprint: fp)
            }
            throw error
        }
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let msg = obj?["error"] as? String ?? HTTPURLResponse.localizedString(forStatusCode: code)
            throw APIError.http(code, msg, needTotp: obj?["need_totp"] as? Bool ?? false)
        }
        return data
    }

    func get<T: Decodable>(_ path: String, query: [URLQueryItem] = [], as: T.Type = T.self) async throws -> T {
        try decode(try await raw("GET", path, query: query))
    }

    func send<T: Decodable>(_ method: String, _ path: String, json: [String: Any]? = nil,
                            timeout: TimeInterval = 60, as: T.Type = T.self) async throws -> T {
        let body = try json.map { try JSONSerialization.data(withJSONObject: $0) }
        return try decode(try await raw(method, path, body: body ?? (method == "GET" ? nil : Data("{}".utf8)),
                                        timeout: timeout))
    }

    func sendEncodable<T: Decodable, B: Encodable>(_ method: String, _ path: String, body: B,
                                                   as: T.Type = T.self) async throws -> T {
        try decode(try await raw(method, path, body: try encoder.encode(body)))
    }

    func upload(files: [(name: String, data: Data)]) async throws -> ImportResult {
        let boundary = "fmu-\(UUID().uuidString)"
        var body = Data()
        for f in files {
            body.append(Data("--\(boundary)\r\n".utf8))
            body.append(Data("Content-Disposition: form-data; name=\"files\"; filename=\"\(f.name)\"\r\n".utf8))
            body.append(Data("Content-Type: application/octet-stream\r\n\r\n".utf8))
            body.append(f.data)
            body.append(Data("\r\n".utf8))
        }
        body.append(Data("--\(boundary)--\r\n".utf8))
        do {
            return try decode(try await raw("POST", "/api/import", body: body,
                                            contentType: "multipart/form-data; boundary=\(boundary)"))
        } catch APIError.http(400, let msg, _) {
            return ImportResult(ok: false, added: [], errors: [.init(file: "Import", error: msg)])
        }
    }

    func decode<T: Decodable>(_ data: Data) throws -> T {
        do { return try decoder.decode(T.self, from: data) } catch {
            throw APIError.decoding(String(describing: error).prefix(300).description)
        }
    }

    // MARK: Live-Ereignisse (Server-Sent Events)

    func events() -> AsyncThrowingStream<(event: String, data: Data), Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var req = URLRequest(url: try self.url("/api/events"))
                    req.timeoutInterval = 90
                    req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    if let token = self.token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
                    let (bytes, resp) = try await self.session.bytes(for: req)
                    let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
                    guard code == 200 else { throw APIError.http(code, "Live-Verbindung abgelehnt", needTotp: false) }
                    var event = "message"
                    for try await line in bytes.lines {
                        if line.hasPrefix("event:") {
                            event = line.dropFirst(6).trimmingCharacters(in: .whitespaces)
                        } else if line.hasPrefix("data:") {
                            let payload = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                            continuation.yield((event, Data(payload.utf8)))
                            event = "message"
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: TLS / Zertifikats-Pinning

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust else {
            completionHandler(.performDefaultHandling, nil)
            return
        }
        var err: CFError?
        if SecTrustEvaluateWithError(trust, &err) {
            completionHandler(.performDefaultHandling, nil)
            return
        }
        guard let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate], let leaf = chain.first else {
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }
        let der = SecCertificateCopyData(leaf) as Data
        let fp = SHA256.hash(data: der).map { String(format: "%02X", $0) }.joined()
        if let pinned = pinnedFingerprint, pinned.uppercased() == fp {
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            lastUntrustedFingerprint = fp
            completionHandler(.cancelAuthenticationChallenge, nil)
        }
    }
}
