import Foundation
import SwiftData
import SwiftUI

/// Keeps this phone and the Mac in step, whenever the Mac can be reached.
///
/// 1. Send what changed here (rows marked dirty, and deletions).
/// 2. Ask the Mac for everything that changed there since last time.
/// 3. The newer edit wins. Nothing is ever needed from the Mac to use the app.
@MainActor final class SyncEngine: ObservableObject {
    enum State: Equatable { case idle, syncing, offline, signedOut, failed(String) }

    @Published private(set) var state: State = .idle
    @Published private(set) var lastSync: Date? = UserDefaults.standard.object(forKey: "lastSync") as? Date
    @AppStorage("serverURL") var serverURL = ""
    @AppStorage("lastRev") private var lastRev = 0

    let context: ModelContext
    private var pendingTask: Task<Void, Never>?
    private let session: URLSession = {
        let c = URLSessionConfiguration.default
        c.timeoutIntervalForRequest = 15
        c.httpCookieStorage = .shared            // the Mac's sign-in cookie (lasts 30 days, renewed on use)
        c.httpShouldSetCookies = true
        c.waitsForConnectivity = false
        return URLSession(configuration: c)
    }()

    init(context: ModelContext) { self.context = context }

    var isConnected: Bool { !serverURL.isEmpty }

    // MARK: signing in

    func signIn(address: String, password: String) async throws {
        var base = address.trimmingCharacters(in: .whitespacesAndNewlines)
        if !base.hasPrefix("http") { base = "https://" + base }
        while base.hasSuffix("/") { base.removeLast() }
        guard let url = URL(string: base + "/api/auth/login") else { throw SyncError.message("That address doesn't look right.") }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["password": password])
        let (data, resp) = try await session.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard code == 200 else { throw SyncError.message(Self.detail(data) ?? "Couldn't sign in (error \(code)).") }
        if serverURL != base { lastRev = 0 }         // a different Mac: start from everything
        serverURL = base
        await sync()
    }

    func signOut() {
        if let url = URL(string: serverURL), let cookies = HTTPCookieStorage.shared.cookies(for: url) {
            cookies.forEach(HTTPCookieStorage.shared.deleteCookie)
        }
        serverURL = ""
        lastRev = 0
        state = .signedOut
    }

    // MARK: syncing

    /// Sync soon (after a change), not after every keystroke.
    func soon() {
        pendingTask?.cancel()
        pendingTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            guard !Task.isCancelled else { return }
            await self?.sync()
        }
    }

    func sync() async {
        guard isConnected, state != .syncing else { return }
        addDueBills(context)
        state = .syncing
        do {
            try await push()
            try await pull()
            lastSync = Date()
            UserDefaults.standard.set(lastSync, forKey: "lastSync")
            state = .idle
        } catch SyncError.signedOut {
            state = .signedOut
        } catch let e as URLError where [.notConnectedToInternet, .timedOut, .cannotConnectToHost, .cannotFindHost,
                                          .networkConnectionLost, .dnsLookupFailed, .secureConnectionFailed].contains(e.code) {
            state = .offline
        } catch SyncError.unreachable {
            state = .offline
        } catch {
            state = .failed((error as? SyncError)?.text ?? error.localizedDescription)
        }
    }

    private func request(_ method: String, _ path: String, body: [String: Any]? = nil) async throws -> [String: Any] {
        guard let url = URL(string: serverURL + path) else { throw SyncError.message("No Mac address") }
        var req = URLRequest(url: url)
        req.httpMethod = method
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, resp) = try await session.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401 { throw SyncError.signedOut }
        if (502...504).contains(code) { throw SyncError.unreachable }      // Budget closed on the Mac
        guard code == 200 else { throw SyncError.message(Self.detail(data) ?? "The Mac answered with error \(code).") }
        return (try JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
    }

    private static func detail(_ data: Data) -> String? {
        ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any])?["detail"] as? String
    }

    // MARK: 1. send

    private func push() async throws {
        let cats = try context.fetch(FetchDescriptor<Category>(predicate: #Predicate { $0.dirty }))
        let exps = try context.fetch(FetchDescriptor<Expense>(predicate: #Predicate { $0.dirty }))
        let lims = try context.fetch(FetchDescriptor<BudgetLimit>(predicate: #Predicate { $0.dirty }))
        let bills = try context.fetch(FetchDescriptor<Bill>(predicate: #Predicate { $0.dirty }))
        let moves = try context.fetch(FetchDescriptor<SavingsMove>(predicate: #Predicate { $0.dirty }))
        let rules = try context.fetch(FetchDescriptor<MerchantRule>(predicate: #Predicate { $0.dirty }))
        let sets = try context.fetch(FetchDescriptor<AppSetting>(predicate: #Predicate { $0.dirty }))
        let tombs = try context.fetch(FetchDescriptor<Tombstone>())
        if cats.isEmpty && exps.isEmpty && lims.isEmpty && bills.isEmpty && moves.isEmpty && rules.isEmpty && sets.isEmpty && tombs.isEmpty {
            return
        }
        let n = { (v: String?) -> Any in v ?? NSNull() }
        let changes: [String: Any] = [
            "categories": cats.map { ["uid": $0.uid, "name": $0.name, "color": $0.color, "sort_order": $0.sortOrder, "modified_at": $0.modifiedAt] },
            "expenses": exps.map { ["uid": $0.uid, "amount_cents": $0.amountCents, "merchant": $0.merchant, "date": $0.date,
                                    "note": n($0.note), "category_uid": n($0.categoryUid), "category_source": $0.categorySource,
                                    "source": $0.source, "recurring_uid": n($0.recurringUid), "modified_at": $0.modifiedAt] },
            "budgets": lims.map { ["uid": $0.uid, "category_uid": n($0.categoryUid), "period": $0.period, "limit_cents": $0.limitCents,
                                   "modified_at": $0.modifiedAt] },
            "recurring": bills.map { ["uid": $0.uid, "merchant": $0.merchant, "amount_cents": $0.amountCents, "category_uid": n($0.categoryUid),
                                      "note": n($0.note), "day": $0.day, "next_date": $0.nextDate, "modified_at": $0.modifiedAt] },
            "savings_moves": moves.map { ["uid": $0.uid, "date": $0.date, "amount_cents": $0.amountCents, "note": n($0.note), "modified_at": $0.modifiedAt] },
            "merchant_rules": rules.map { ["merchant_norm": $0.merchantNorm, "category_uid": n($0.categoryUid), "hit_count": $0.hitCount,
                                           "modified_at": $0.modifiedAt] },
            "settings": sets.compactMap { s -> [String: Any]? in
                guard let v = try? JSONSerialization.jsonObject(with: Data(s.json.utf8), options: .fragmentsAllowed) else { return nil }
                return ["key": s.key, "value": v, "modified_at": s.modifiedAt]
            },
        ]
        let deleted = tombs.map { ["table": $0.table, "key": $0.key, "deleted_at": $0.deletedAt] }
        // What was sent, so edits made while sending stay marked as not sent.
        var sent: [PersistentIdentifier: String] = [:]
        for r in cats { sent[r.persistentModelID] = r.modifiedAt }
        for r in exps { sent[r.persistentModelID] = r.modifiedAt }
        for r in lims { sent[r.persistentModelID] = r.modifiedAt }
        for r in bills { sent[r.persistentModelID] = r.modifiedAt }
        for r in moves { sent[r.persistentModelID] = r.modifiedAt }
        for r in rules { sent[r.persistentModelID] = r.modifiedAt }
        for r in sets { sent[r.persistentModelID] = r.modifiedAt }

        let answer = try await request("POST", "/api/sync", body: ["changes": changes, "deleted": deleted])

        func clean<T: PersistentModel>(_ rows: [T], _ stamp: (T) -> String, _ done: (T) -> Void) {
            for r in rows where sent[r.persistentModelID] == stamp(r) { done(r) }
        }
        clean(cats, \.modifiedAt) { $0.dirty = false }
        clean(exps, \.modifiedAt) { $0.dirty = false }
        clean(lims, \.modifiedAt) { $0.dirty = false }
        clean(bills, \.modifiedAt) { $0.dirty = false }
        clean(moves, \.modifiedAt) { $0.dirty = false }
        clean(rules, \.modifiedAt) { $0.dirty = false }
        clean(sets, \.modifiedAt) { $0.dirty = false }
        tombs.forEach(context.delete)
        if let remap = answer["remap"] as? [String: String] { try applyRemap(remap) }
        try context.save()
    }

    /// The Mac already had this category/budget (made on both devices): use the Mac's.
    private func applyRemap(_ remap: [String: String]) throws {
        for (old, new) in remap {
            if let c = try context.fetch(FetchDescriptor<Category>(predicate: #Predicate { $0.uid == old })).first {
                for e in try context.fetch(FetchDescriptor<Expense>(predicate: #Predicate { $0.categoryUid == old })) { e.categoryUid = new }
                for b in try context.fetch(FetchDescriptor<BudgetLimit>(predicate: #Predicate { $0.categoryUid == old })) { b.categoryUid = new }
                for b in try context.fetch(FetchDescriptor<Bill>(predicate: #Predicate { $0.categoryUid == old })) { b.categoryUid = new }
                for r in try context.fetch(FetchDescriptor<MerchantRule>(predicate: #Predicate { $0.categoryUid == old })) { r.categoryUid = new }
                context.delete(c)
            }
            if let b = try context.fetch(FetchDescriptor<BudgetLimit>(predicate: #Predicate { $0.uid == old })).first {
                context.delete(b)      // the Mac's limit arrives with the pull
            }
        }
    }

    // MARK: 2. receive

    private func pull() async throws {
        let answer = try await request("GET", "/api/sync?since=\(lastRev)")
        let tables = answer["tables"] as? [String: [[String: Any]]] ?? [:]

        // Keep local only if it's unsent and newer than what the Mac has.
        func keepLocal(dirty: Bool, local: String, incoming: String?) -> Bool { dirty && local > (incoming ?? "") }

        for r in tables["categories"] ?? [] {
            let uid = r.str("uid")
            if let c = try context.fetch(FetchDescriptor<Category>(predicate: #Predicate { $0.uid == uid })).first {
                if keepLocal(dirty: c.dirty, local: c.modifiedAt, incoming: r["modified_at"] as? String) { continue }
                c.name = r.str("name"); c.color = r.str("color"); c.sortOrder = r.int("sort_order"); c.modifiedAt = r.str("modified_at"); c.dirty = false
            } else {
                context.insert(Category(uid: uid, name: r.str("name"), color: r.str("color"), sortOrder: r.int("sort_order"),
                                        modifiedAt: r.str("modified_at"), dirty: false))
            }
        }
        for r in tables["expenses"] ?? [] {
            let uid = r.str("uid")
            if let e = try context.fetch(FetchDescriptor<Expense>(predicate: #Predicate { $0.uid == uid })).first {
                if keepLocal(dirty: e.dirty, local: e.modifiedAt, incoming: r["modified_at"] as? String) { continue }
                e.amountCents = r.int("amount_cents"); e.merchant = r.str("merchant"); e.merchantNorm = r.str("merchant_norm")
                e.date = r.str("date"); e.note = r["note"] as? String; e.categoryUid = r["category_uid"] as? String
                e.categorySource = r.str("category_source"); e.source = r.str("source"); e.recurringUid = r["recurring_uid"] as? String
                e.modifiedAt = r.str("modified_at"); e.dirty = false
            } else {
                let e = Expense(uid: uid, amountCents: r.int("amount_cents"), merchant: r.str("merchant"), date: r.str("date"),
                                note: r["note"] as? String, categoryUid: r["category_uid"] as? String,
                                categorySource: r.str("category_source"), source: r.str("source"),
                                recurringUid: r["recurring_uid"] as? String, createdAt: r.str("created_at"),
                                modifiedAt: r.str("modified_at"), dirty: false)
                context.insert(e)
            }
        }
        for r in tables["budgets"] ?? [] {
            let uid = r.str("uid")
            if let b = try context.fetch(FetchDescriptor<BudgetLimit>(predicate: #Predicate { $0.uid == uid })).first {
                if keepLocal(dirty: b.dirty, local: b.modifiedAt, incoming: r["modified_at"] as? String) { continue }
                b.categoryUid = r["category_uid"] as? String; b.period = r.str("period"); b.limitCents = r.int("limit_cents")
                b.modifiedAt = r.str("modified_at"); b.dirty = false
            } else {
                context.insert(BudgetLimit(uid: uid, categoryUid: r["category_uid"] as? String, period: r.str("period"),
                                           limitCents: r.int("limit_cents"), modifiedAt: r.str("modified_at"), dirty: false))
            }
        }
        for r in tables["recurring"] ?? [] {
            let uid = r.str("uid")
            if let b = try context.fetch(FetchDescriptor<Bill>(predicate: #Predicate { $0.uid == uid })).first {
                if keepLocal(dirty: b.dirty, local: b.modifiedAt, incoming: r["modified_at"] as? String) { continue }
                b.merchant = r.str("merchant"); b.amountCents = r.int("amount_cents"); b.categoryUid = r["category_uid"] as? String
                b.note = r["note"] as? String; b.day = r.int("day"); b.nextDate = max(b.nextDate, r.str("next_date"))
                b.modifiedAt = r.str("modified_at"); b.dirty = false
            } else {
                context.insert(Bill(uid: uid, merchant: r.str("merchant"), amountCents: r.int("amount_cents"),
                                    categoryUid: r["category_uid"] as? String, note: r["note"] as? String, day: r.int("day"),
                                    nextDate: r.str("next_date"), modifiedAt: r.str("modified_at"), dirty: false))
            }
        }
        for r in tables["savings_moves"] ?? [] {
            let uid = r.str("uid")
            if let m = try context.fetch(FetchDescriptor<SavingsMove>(predicate: #Predicate { $0.uid == uid })).first {
                if keepLocal(dirty: m.dirty, local: m.modifiedAt, incoming: r["modified_at"] as? String) { continue }
                m.date = r.str("date"); m.amountCents = r.int("amount_cents"); m.note = r["note"] as? String
                m.modifiedAt = r.str("modified_at"); m.dirty = false
            } else {
                context.insert(SavingsMove(uid: uid, date: r.str("date"), amountCents: r.int("amount_cents"), note: r["note"] as? String,
                                           modifiedAt: r.str("modified_at"), dirty: false))
            }
        }
        for r in tables["merchant_rules"] ?? [] {
            let key = r.str("merchant_norm")
            if let m = try context.fetch(FetchDescriptor<MerchantRule>(predicate: #Predicate { $0.merchantNorm == key })).first {
                if keepLocal(dirty: m.dirty, local: m.modifiedAt, incoming: r["modified_at"] as? String) { continue }
                m.categoryUid = r["category_uid"] as? String; m.hitCount = r.int("hit_count"); m.modifiedAt = r.str("modified_at"); m.dirty = false
            } else {
                context.insert(MerchantRule(merchantNorm: key, categoryUid: r["category_uid"] as? String, hitCount: r.int("hit_count"),
                                            modifiedAt: r.str("modified_at"), dirty: false))
            }
        }
        for r in tables["keyword_rules"] ?? [] {
            let key = r.str("keyword")
            if let k = try context.fetch(FetchDescriptor<KeywordRule>(predicate: #Predicate { $0.keyword == key })).first {
                k.categoryUid = r["category_uid"] as? String
            } else {
                context.insert(KeywordRule(keyword: key, categoryUid: r["category_uid"] as? String))
            }
        }
        for r in tables["savings_months"] ?? [] {
            let key = r.str("month")
            let m = try context.fetch(FetchDescriptor<SavingsMonth>(predicate: #Predicate { $0.month == key })).first
                ?? { let m = SavingsMonth(month: key, limitCents: nil, spentCents: 0, savedCents: 0); context.insert(m); return m }()
            m.limitCents = r["limit_cents"] as? Int; m.spentCents = r.int("spent_cents"); m.savedCents = r.int("saved_cents")
        }
        for r in tables["settings"] ?? [] {
            let key = r.str("key")
            guard let data = try? JSONSerialization.data(withJSONObject: r["value"] ?? NSNull(), options: .fragmentsAllowed),
                  let json = String(data: data, encoding: .utf8) else { continue }
            if let s = try context.fetch(FetchDescriptor<AppSetting>(predicate: #Predicate { $0.key == key })).first {
                if keepLocal(dirty: s.dirty, local: s.modifiedAt, incoming: r["modified_at"] as? String) { continue }
                s.json = json; s.modifiedAt = r.str("modified_at"); s.dirty = false
            } else {
                context.insert(AppSetting(key: key, json: json, modifiedAt: r.str("modified_at"), dirty: false))
            }
        }
        for d in answer["deleted"] as? [[String: Any]] ?? [] {
            try applyDeletion(table: d.str("table"), key: d.str("key"), at: d.str("deleted_at"))
        }
        try context.save()
        lastRev = answer["rev"] as? Int ?? lastRev
    }

    private func applyDeletion(table: String, key: String, at: String) throws {
        // Edited here after it was deleted on the Mac: the edit wins (it's sent back next time).
        func gone(_ dirty: Bool, _ modified: String) -> Bool { !(dirty && modified > at) }
        switch table {
        case "categories":
            if let x = try context.fetch(FetchDescriptor<Category>(predicate: #Predicate { $0.uid == key })).first, gone(x.dirty, x.modifiedAt) {
                for e in try context.fetch(FetchDescriptor<Expense>(predicate: #Predicate { $0.categoryUid == key })) { e.categoryUid = nil }
                context.delete(x)
            }
        case "expenses":
            if let x = try context.fetch(FetchDescriptor<Expense>(predicate: #Predicate { $0.uid == key })).first, gone(x.dirty, x.modifiedAt) { context.delete(x) }
        case "budgets":
            if let x = try context.fetch(FetchDescriptor<BudgetLimit>(predicate: #Predicate { $0.uid == key })).first, gone(x.dirty, x.modifiedAt) { context.delete(x) }
        case "recurring":
            if let x = try context.fetch(FetchDescriptor<Bill>(predicate: #Predicate { $0.uid == key })).first, gone(x.dirty, x.modifiedAt) { context.delete(x) }
        case "savings_moves":
            if let x = try context.fetch(FetchDescriptor<SavingsMove>(predicate: #Predicate { $0.uid == key })).first, gone(x.dirty, x.modifiedAt) { context.delete(x) }
        case "merchant_rules":
            if let x = try context.fetch(FetchDescriptor<MerchantRule>(predicate: #Predicate { $0.merchantNorm == key })).first, gone(x.dirty, x.modifiedAt) { context.delete(x) }
        case "keyword_rules":
            if let x = try context.fetch(FetchDescriptor<KeywordRule>(predicate: #Predicate { $0.keyword == key })).first { context.delete(x) }
        default: break
        }
    }
}

enum SyncError: Error {
    case signedOut, unreachable, message(String)
    var text: String {
        switch self {
        case .signedOut: return "Sign in again."
        case .unreachable: return "Budget isn't open on the Mac."
        case .message(let m): return m
        }
    }
}

private extension Dictionary where Key == String, Value == Any {
    func str(_ k: String) -> String { self[k] as? String ?? "" }
    func int(_ k: String) -> Int { (self[k] as? Int) ?? Int((self[k] as? Double) ?? 0) }
}
