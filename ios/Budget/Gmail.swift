import CryptoKit
import Foundation
import Network
import Security

// Reading the Apple Pay emails your iPhone Shortcut sends to Gmail, on the phone
// itself: the same rules as the Mac (app/gmail.py, app/email_sync.py).
//
// Gmail is opened read-only over IMAP: nothing is ever marked, moved or deleted.
// The app password is kept in the iPhone Keychain.

let gmailSubject = "BUDGET"

// MARK: - Keychain

enum Keychain {
    private static let service = "Budget – Gmail app password"

    static func password(for address: String) -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: address.lowercased(), kSecReturnData as String: true]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    static func setPassword(_ password: String, for address: String) {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: address.lowercased()]
        SecItemDelete(q as CFDictionary)
        var add = q
        add[kSecValueData as String] = Data(password.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly   // readable in background checks
        SecItemAdd(add as CFDictionary, nil)
    }

    static func deletePassword(for address: String) {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: address.lowercased()]
        SecItemDelete(q as CFDictionary)
    }
}

/// Google shows app passwords as "abcd efgh ijkl mnop"; the spaces aren't part of it.
func cleanAppPassword(_ p: String) -> String { p.filter { !$0.isWhitespace } }

// MARK: - The transaction line

struct Transaction {
    let line: String
    let date: String?           // yyyy-MM-dd, the phone's local date
    let merchant: String
    let amountCents: Int?
    let currency: String
    let problem: String?        // why the Mac should look at it instead
}

private let lineRegex = try! NSRegularExpression(pattern: #"""
    ^\s*
    (?<when>\d{4}-\d{2}-\d{2}(?:[T\s]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?(?:Z|[+-]\d{2}:?\d{2})?)
    \s*;\s*(?<merchant>[^;]*?)
    \s*;\s*(?<amount>[^;]*?)
    \s*(?:;\s*(?<currency>[A-Za-z]{3})?\s*)?$
    """#, options: [.allowCommentsAndWhitespace])

/// The first line that looks like date;merchant;amount;currency.
func findTransaction(_ text: String) -> Transaction? {
    for raw in text.components(separatedBy: .newlines) {
        let s = raw.replacingOccurrences(of: "\u{00A0}", with: " ")
        let ns = s as NSString
        guard let m = lineRegex.firstMatch(in: s, range: NSRange(location: 0, length: ns.length)) else { continue }
        func group(_ name: String) -> String? {
            let r = m.range(withName: name)
            return r.location == NSNotFound ? nil : ns.substring(with: r)
        }
        return buildTransaction(line: raw.trimmingCharacters(in: .whitespaces), when: group("when") ?? "",
                                merchant: group("merchant") ?? "", amount: group("amount") ?? "", currency: group("currency"))
    }
    return nil
}

private func buildTransaction(line: String, when: String, merchant rawMerchant: String, amount: String, currency rawCurrency: String?) -> Transaction {
    // The date as written (the offset in the timestamp is already the phone's local time).
    let datePart = String(when.prefix(10))
    let date = isoDay.date(from: datePart).map(iso) == datePart ? datePart : nil
    let merchant = rawMerchant.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    let currency = (rawCurrency ?? "EUR").uppercased()
    // Keep digits, separators and sign: "12,45 €", "€12.45", "12,45 EUR" -> "12,45".
    let amountText = String(amount.filter { $0.isASCII && ($0.isNumber || ",.-+".contains($0)) })
    let cents = amountText.isEmpty ? nil : toCents(amountText)

    var problem: String?
    if date == nil { problem = "unreadable date" }
    else if currency != "EUR" { problem = "amount is in \(currency), not EUR" }
    else if merchant.isEmpty { problem = "blank merchant" }
    else if cents == nil { problem = amount.trimmingCharacters(in: .whitespaces).isEmpty ? "blank amount" : "unreadable amount" }
    else if cents == 0 { problem = "amount is 0,00 €" }
    return Transaction(line: line, date: date, merchant: merchant, amountCents: cents, currency: currency, problem: problem)
}

/// Euros -> cents, like the Mac's to_cents: "12,45", "1.234,56", "1,234.56", "-3,10".
func toCents(_ raw: String) -> Int? {
    var t = raw
    if t.contains(",") && t.contains(".") {
        // Whichever separator comes last is the decimal one.
        if t.range(of: ",", options: .backwards)!.lowerBound > t.range(of: ".", options: .backwards)!.lowerBound {
            t = t.replacingOccurrences(of: ".", with: "").replacingOccurrences(of: ",", with: ".")
        } else {
            t = t.replacingOccurrences(of: ",", with: "")
        }
    } else {
        t = t.replacingOccurrences(of: ",", with: ".")
    }
    guard t.range(of: #"^[+-]?(\d+\.?\d*|\.\d+)$"#, options: .regularExpression) != nil,
          let v = Decimal(string: t, locale: Locale(identifier: "en_US_POSIX")) else { return nil }
    var x = v * 100, rounded = Decimal()
    NSDecimalRound(&rounded, &x, 0, .plain)          // .plain = half away from zero, like ROUND_HALF_UP
    return NSDecimalNumber(decimal: rounded).intValue
}

// MARK: - Emails

/// Just enough of an email to read a BUDGET message: headers and the text body.
struct Mail {
    let raw: Data
    private let headers: [(name: String, value: String)]
    private let body: Data

    init(_ raw: Data) {
        self.raw = raw
        (headers, body) = Mail.split(raw)
    }

    func header(_ name: String) -> String? { headers.first { $0.name.caseInsensitiveCompare(name) == .orderedSame }?.value }
    func headers(_ name: String) -> [String] { headers.filter { $0.name.caseInsensitiveCompare(name) == .orderedSame }.map(\.value) }

    var subject: String { decodeEncodedWords(header("Subject") ?? "").trimmingCharacters(in: .whitespaces) }
    var subjectOK: Bool { subject.uppercased() == gmailSubject }

    /// The Message-ID, or a hash of the whole email when there isn't one (like the Mac).
    var messageID: String {
        let mid = (header("Message-ID") ?? "").trimmingCharacters(in: .whitespaces)
        if !mid.isEmpty { return mid }
        return "sha1:" + Insecure.SHA1.hash(data: raw).map { String(format: "%02x", $0) }.joined()
    }

    var sender: String {
        let from = header("From") ?? ""
        if let r = from.range(of: #"<([^>]*)>"#, options: .regularExpression) {
            return String(from[r].dropFirst().dropLast()).trimmingCharacters(in: .whitespaces)
        }
        return from.trimmingCharacters(in: .whitespaces)
    }

    /// Plain-text body, or the HTML body with tags stripped if there's no plain part.
    var text: String {
        let (plain, html) = Mail.textParts(headers: headers, body: body)
        if let plain { return plain }
        guard var h = html else { return "" }
        h = h.replacingOccurrences(of: #"(?i)<br\s*/?>|</p>|</div>"#, with: "\n", options: .regularExpression)
        h = h.replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
        return unescapeHTML(h)
    }

    // Headers end at the first blank line; folded lines continue the one above.
    private static func split(_ raw: Data) -> ([(String, String)], Data) {
        let crlf = raw.range(of: Data("\r\n\r\n".utf8)), lf = raw.range(of: Data("\n\n".utf8))
        let end = [crlf, lf].compactMap { $0 }.min { $0.lowerBound < $1.lowerBound }
        let head = end.map { raw[raw.startIndex..<$0.lowerBound] } ?? raw
        let body = end.map { raw[$0.upperBound...] } ?? Data()
        let text = String(data: head, encoding: .utf8) ?? String(decoding: head, as: UTF8.self)
        var out: [(String, String)] = []
        for line in text.components(separatedBy: "\n").map({ $0.hasSuffix("\r") ? String($0.dropLast()) : $0 }) {
            if let first = line.first, first == " " || first == "\t", !out.isEmpty {
                out[out.count - 1].1 += " " + line.trimmingCharacters(in: .whitespaces)
            } else if let colon = line.firstIndex(of: ":") {
                out.append((String(line[..<colon]).trimmingCharacters(in: .whitespaces),
                            String(line[line.index(after: colon)...]).trimmingCharacters(in: .whitespaces)))
            }
        }
        return (out, Data(body))
    }

    private static func param(_ name: String, in value: String) -> String? {
        let pattern = "(?i)(?:^|;)\\s*\(name)\\s*=\\s*(\"[^\"]*\"|[^;\\s]+)"
        guard let r = value.range(of: pattern, options: .regularExpression) else { return nil }
        var v = String(value[r])
        v = String(v[v.index(after: v.firstIndex(of: "=")!)...]).trimmingCharacters(in: .whitespaces)
        return v.trimmingCharacters(in: CharacterSet(charactersIn: "\""))
    }

    private static func textParts(headers: [(name: String, value: String)], body: Data) -> (String?, String?) {
        func h(_ n: String) -> String { headers.first { $0.name.caseInsensitiveCompare(n) == .orderedSame }?.value ?? "" }
        let ctype = h("Content-Type")
        let kind = (ctype.split(separator: ";").first.map(String.init) ?? "text/plain").trimmingCharacters(in: .whitespaces).lowercased()
        if kind.hasPrefix("multipart/"), let boundary = param("boundary", in: ctype) {
            var plain: String?, html: String?
            for part in splitParts(body, boundary: boundary) {
                let (ph, pb) = split(part)
                let (p, x) = textParts(headers: ph, body: pb)
                plain = plain ?? p; html = html ?? x
            }
            return (plain, html)
        }
        guard kind == "text/plain" || kind == "text/html" || ctype.isEmpty else { return (nil, nil) }
        let decoded = decodeTransfer(body, h("Content-Transfer-Encoding"))
        let text = decodeCharset(decoded, param("charset", in: ctype))
        return kind == "text/html" ? (nil, text) : (text, nil)
    }

    private static func splitParts(_ body: Data, boundary: String) -> [Data] {
        let s = String(data: body, encoding: .isoLatin1) ?? ""          // byte-for-byte, so parts can be turned back into bytes
        var parts: [Data] = []
        for chunk in s.components(separatedBy: "--" + boundary).dropFirst() {
            if chunk.hasPrefix("--") { break }
            var c = Substring(chunk)
            if c.hasPrefix("\r\n") { c = c.dropFirst(2) } else if c.hasPrefix("\n") { c = c.dropFirst() }
            parts.append(String(c).data(using: .isoLatin1) ?? Data())
        }
        return parts
    }

    private static func decodeTransfer(_ body: Data, _ encoding: String) -> Data {
        switch encoding.lowercased().trimmingCharacters(in: .whitespaces) {
        case "base64":
            let compact = String(decoding: body, as: UTF8.self).filter { !$0.isWhitespace }
            return Data(base64Encoded: compact, options: .ignoreUnknownCharacters) ?? body
        case "quoted-printable":
            return decodeQuotedPrintable(body)
        default:
            return body
        }
    }

    private static func decodeCharset(_ d: Data, _ charset: String?) -> String {
        switch (charset ?? "utf-8").lowercased() {
        case "iso-8859-1", "latin1", "us-ascii": return String(data: d, encoding: .isoLatin1) ?? String(decoding: d, as: UTF8.self)
        case "windows-1252", "cp1252": return String(data: d, encoding: .windowsCP1252) ?? String(decoding: d, as: UTF8.self)
        default: return String(data: d, encoding: .utf8) ?? String(decoding: d, as: UTF8.self)
        }
    }
}

func decodeQuotedPrintable(_ d: Data, underscoreIsSpace: Bool = false) -> Data {
    var out = Data(), bytes = [UInt8](d), i = 0
    func hex(_ b: UInt8) -> UInt8? {
        switch b { case 48...57: return b - 48; case 65...70: return b - 55; case 97...102: return b - 87; default: return nil }
    }
    while i < bytes.count {
        let b = bytes[i]
        if b == UInt8(ascii: "=") {
            if i + 1 < bytes.count, bytes[i + 1] == 10 { i += 2; continue }                                   // soft line break
            if i + 2 < bytes.count, bytes[i + 1] == 13, bytes[i + 2] == 10 { i += 3; continue }
            if i + 2 < bytes.count, let hi = hex(bytes[i + 1]), let lo = hex(bytes[i + 2]) { out.append(hi << 4 | lo); i += 3; continue }
        }
        out.append(underscoreIsSpace && b == UInt8(ascii: "_") ? 32 : b)
        i += 1
    }
    return out
}

/// "=?UTF-8?Q?BUDGET?=" -> "BUDGET".
func decodeEncodedWords(_ s: String) -> String {
    let re = try! NSRegularExpression(pattern: #"=\?([^?]+)\?([bBqQ])\?([^?]*)\?="#)
    var out = s
    for m in re.matches(in: s, range: NSRange(s.startIndex..., in: s)).reversed() {
        let ns = s as NSString
        let charset = ns.substring(with: m.range(at: 1)).lowercased(), enc = ns.substring(with: m.range(at: 2)).lowercased()
        let payload = ns.substring(with: m.range(at: 3))
        let data = enc == "b" ? Data(base64Encoded: payload) : decodeQuotedPrintable(Data(payload.utf8), underscoreIsSpace: true)
        guard let data, let r = Range(m.range, in: out) else { continue }
        let text = charset.contains("8859") ? String(data: data, encoding: .isoLatin1) : String(data: data, encoding: .utf8)
        out.replaceSubrange(r, with: text ?? "")
    }
    return out
}

private func unescapeHTML(_ s: String) -> String {
    var t = s
    for (k, v) in ["&nbsp;": " ", "&lt;": "<", "&gt;": ">", "&quot;": "\"", "&#39;": "'", "&apos;": "'", "&euro;": "€"] {
        t = t.replacingOccurrences(of: k, with: v)
    }
    let re = try! NSRegularExpression(pattern: "&#(x?)([0-9a-fA-F]+);")
    for m in re.matches(in: t, range: NSRange(t.startIndex..., in: t)).reversed() {
        let ns = t as NSString
        let isHex = ns.substring(with: m.range(at: 1)) == "x"
        guard let n = UInt32(ns.substring(with: m.range(at: 2)), radix: isHex ? 16 : 10), let u = Unicode.Scalar(n),
              let r = Range(m.range, in: t) else { continue }
        t.replaceSubrange(r, with: String(Character(u)))
    }
    return t.replacingOccurrences(of: "&amp;", with: "&")
}

/// j.doe+budget@googlemail.com and jdoe@gmail.com are the same Gmail inbox.
func canonicalGmail(_ address: String) -> String {
    let a = address.trimmingCharacters(in: .whitespaces).lowercased()
    guard let at = a.lastIndex(of: "@") else { return a }
    var local = String(a[..<at]), domain = String(a[a.index(after: at)...])
    if domain == "gmail.com" || domain == "googlemail.com" {
        local = String(local.split(separator: "+", maxSplits: 1, omittingEmptySubsequences: false).first ?? "")
            .replacingOccurrences(of: ".", with: "")
        domain = "gmail.com"
    }
    return "\(local)@\(domain)"
}

/// nil if the email really comes from you, otherwise why it was refused.
func senderProblem(_ mail: Mail, myAddress: String) -> String? {
    if canonicalGmail(mail.sender) != canonicalGmail(myAddress) {
        return "sent from \(mail.sender.isEmpty ? "an unknown address" : mail.sender), not from you"
    }
    for verdict in mail.headers("Authentication-Results").map({ $0.lowercased() })
    where verdict.contains("dmarc=fail") || verdict.contains("spf=fail") || verdict.contains("dkim=fail") {
        return "failed Gmail's sender check (possibly forged)"
    }
    return nil
}

/// The uid of the expense made from this email: the same on the Mac (email_sync.expense_uid).
func emailExpenseUID(_ messageID: String) -> String {
    SHA256.hash(data: Data("email:\(messageID)".utf8)).map { String(format: "%02x", $0) }.joined().prefix(32).lowercased()
}

// MARK: - IMAP

struct GmailError: Error { let text: String }

/// A small IMAP client: sign in, open a label read-only, search, fetch. That's all Budget needs.
final class IMAPClient {
    private let connection: NWConnection
    private var buffer = Data()
    private var tag = 0
    private(set) var uidValidity: Int?
    private(set) var uidNext: Int?

    init(host: String = "imap.gmail.com", port: UInt16 = 993, tls: Bool = true) {
        connection = NWConnection(host: NWEndpoint.Host(host), port: NWEndpoint.Port(rawValue: port)!, using: tls ? .tls : .tcp)
    }

    /// Gmail, or (testing only: -imapHost 127.0.0.1 -imapPort 1143) a fake one without TLS.
    static func gmail() -> IMAPClient {
        #if DEBUG
        if let host = UserDefaults.standard.string(forKey: "imapHost") {
            return IMAPClient(host: host, port: UInt16(UserDefaults.standard.integer(forKey: "imapPort")), tls: false)
        }
        #endif
        return IMAPClient()
    }

    func open() async throws {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            let once = Once()
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready: if once.claim() { cont.resume() }
                case .failed(let e), .waiting(let e): if once.claim() { cont.resume(throwing: e) }   // waiting = offline: don't hang around
                case .cancelled: if once.claim() { cont.resume(throwing: GmailError(text: "Stopped.")) }
                default: break
                }
            }
            connection.start(queue: .global(qos: .utility))
        }
        _ = try await readLine()                                                     // "* OK Gimap ready"
    }

    func close() {
        if connection.state == .ready { connection.send(content: Data("z LOGOUT\r\n".utf8), completion: .idempotent) }
        connection.cancel()
    }

    func login(_ user: String, _ password: String) async throws {
        _ = try await command("LOGIN \(quote(user)) \(quote(password))")
    }

    /// Open the label read-only (EXAMINE), noting UIDVALIDITY and UIDNEXT.
    func examine(_ label: String) async throws {
        for r in try await command("EXAMINE \(quote(label))") {
            if let v = Self.number(after: "[UIDVALIDITY ", in: r.line) { uidValidity = v }
            if let v = Self.number(after: "[UIDNEXT ", in: r.line) { uidNext = v }
        }
    }

    /// UIDs whose subject contains BUDGET, above `after` (exact match is checked later).
    func searchBudget(after: Int) async throws -> [Int] {
        let lines = try await command("UID SEARCH UID \(after + 1):* SUBJECT \"\(gmailSubject)\"")
        let uids = lines.filter { $0.line.hasPrefix("* SEARCH") }
            .flatMap { $0.line.dropFirst(8).split(separator: " ").compactMap { Int($0) } }
        return uids.filter { $0 > after }.sorted()                 // "n:*" can return the last UID even if < n
    }

    func fetch(_ uids: [Int]) async throws -> [(uid: Int, raw: Data)] {
        var out: [(Int, Data)] = []
        for start in stride(from: 0, to: uids.count, by: 50) {
            let set = uids[start..<min(start + 50, uids.count)].map(String.init).joined(separator: ",")
            for r in try await command("UID FETCH \(set) (UID BODY.PEEK[])") where r.line.contains("FETCH") {   // PEEK: don't mark as read
                if let uid = Self.number(after: "UID ", in: r.line), let raw = r.literals.first { out.append((uid, raw)) }
            }
        }
        return out.sorted { $0.0 < $1.0 }
    }

    // --- the protocol underneath

    private struct Untagged { var line: String; var literals: [Data] }

    private func command(_ text: String) async throws -> [Untagged] {
        tag += 1
        let t = "b\(tag)"
        try await send("\(t) \(text)\r\n")
        var untagged: [Untagged] = []
        while true {
            var line = try await readLine()
            var literals: [Data] = []
            // A line ending in {n} is followed by n bytes, then the rest of the line.
            while let n = Self.literalSize(line) {
                literals.append(try await readBytes(n))
                line += try await readLine()
            }
            if line.hasPrefix(t + " ") {
                let rest = line.dropFirst(t.count + 1)
                if rest.hasPrefix("OK") { return untagged }
                throw GmailError(text: explainIMAP(String(rest)))
            }
            untagged.append(Untagged(line: line, literals: literals))
        }
    }

    private func send(_ s: String) async throws {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            connection.send(content: Data(s.utf8), completion: .contentProcessed { e in
                if let e { cont.resume(throwing: e) } else { cont.resume() }
            })
        }
    }

    private func more() async throws {
        let chunk: Data = try await withCheckedThrowingContinuation { cont in
            connection.receive(minimumIncompleteLength: 1, maximumLength: 256 * 1024) { data, _, complete, error in
                if let error { cont.resume(throwing: error) }
                else if let data, !data.isEmpty { cont.resume(returning: data) }
                else if complete { cont.resume(throwing: GmailError(text: "Gmail closed the connection.")) }
                else { cont.resume(returning: Data()) }
            }
        }
        buffer.append(chunk)
    }

    private func readLine() async throws -> String {
        while true {
            if let r = buffer.range(of: Data("\r\n".utf8)) {
                let line = buffer[buffer.startIndex..<r.lowerBound]
                buffer.removeSubrange(buffer.startIndex..<r.upperBound)
                return String(decoding: line, as: UTF8.self)
            }
            try await more()
        }
    }

    private func readBytes(_ n: Int) async throws -> Data {
        while buffer.count < n { try await more() }
        let d = Data(buffer.prefix(n))
        buffer.removeFirst(n)
        return d
    }

    private func quote(_ s: String) -> String {
        "\"" + s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\""
    }

    private static func literalSize(_ line: String) -> Int? {
        guard line.hasSuffix("}"), let open = line.lastIndex(of: "{") else { return nil }
        return Int(line[line.index(after: open)..<line.index(before: line.endIndex)])
    }

    private static func number(after marker: String, in line: String) -> Int? {
        guard let r = line.range(of: marker) else { return nil }
        return Int(line[r.upperBound...].prefix { $0.isNumber })
    }
}

/// True the first time only: a continuation must be resumed exactly once.
private final class Once: @unchecked Sendable {
    private let lock = NSLock()
    private var done = false
    func claim() -> Bool { lock.lock(); defer { lock.unlock() }; if done { return false }; done = true; return true }
}

/// What Gmail said, in plain words (same wording as the Mac).
func explainIMAP(_ text: String) -> String {
    let low = text.lowercased()
    if low.contains("authenticationfailed") || low.contains("application-specific password required")
        || low.contains("invalid credentials") {
        return "Gmail rejected the address or app password. Use a 16-letter app password (not your normal Google password); app passwords need 2-Step Verification turned on."
    }
    if low.contains("not enabled for imap") || low.contains("imap access is disabled") {
        return "IMAP is turned off for this Gmail account. Turn it on in Gmail → Settings → Forwarding and POP/IMAP."
    }
    if low.contains("too many") || low.contains("web login required") {
        return "Gmail is temporarily blocking sign-ins for this account. Wait a few minutes, or sign in at gmail.com once, then try again."
    }
    if low.contains("nonexistent") || low.contains("unknown mailbox") || low.contains("no such") {
        return "Signed in, but there's no Gmail label with that name. Check the label name (it's case-sensitive)."
    }
    return "Gmail said: \(text)"
}
