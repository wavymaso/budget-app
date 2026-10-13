import BackgroundTasks
import Foundation
import SwiftData
import SwiftUI

/// Checks Gmail for Apple Pay emails on the phone, without needing the Mac.
///
/// An expense from an email gets the same uid as on the Mac, so if both read the
/// same email, sync keeps one. Only emails that arrive after you turn this on are
/// read here: older ones are already on the Mac and come over with sync.
/// Anything unclear (other currency, blank merchant, looks like an expense you
/// typed) is left for the Mac's "Needs review".
@MainActor final class GmailEngine: ObservableObject {
    enum State: Equatable { case idle, checking, failed(String) }

    static let refreshTask = "com.wavymaso.budget.refresh"

    @AppStorage("gmailAddress") var address = ""
    @AppStorage("gmailLabel") var label = "Budget"
    @AppStorage("gmailOn") private(set) var isOn = false
    // Where we got to in the label: UIDs only grow, unless Gmail renumbers it (UIDVALIDITY changes).
    @AppStorage("gmailCursorFor") private var cursorFor = ""
    @AppStorage("gmailUIDValidity") private var uidValidity = 0
    @AppStorage("gmailLastUID") private var lastUID = 0

    @Published private(set) var state: State = .idle
    @Published private(set) var lastCheck: Date? = UserDefaults.standard.object(forKey: "gmailLastCheck") as? Date
    @Published private(set) var lastAdded = 0

    let context: ModelContext
    let sync: SyncEngine

    init(context: ModelContext, sync: SyncEngine) { self.context = context; self.sync = sync }

    // MARK: turning it on and off

    /// Sign in once to check the password, then start reading new emails from now on.
    func turnOn(address newAddress: String, password: String) async throws {
        let addr = newAddress.trimmingCharacters(in: .whitespaces)
        let pw = cleanAppPassword(password)
        guard addr.contains("@") else { throw GmailError(text: "Enter your Gmail address first.") }
        guard !pw.isEmpty else { throw GmailError(text: "Enter your Gmail app password first.") }
        let client = IMAPClient.gmail()
        defer { client.close() }
        try await withDeadline(client) {
            try await client.open()
            try await client.login(addr, pw)
            try await client.examine(self.label)
        }
        Keychain.setPassword(pw, for: addr)
        address = addr
        try await startFromNow(client)
        isOn = true
        state = .idle
        lastCheck = Date(); lastAdded = 0
        UserDefaults.standard.set(lastCheck, forKey: "gmailLastCheck")
        Self.scheduleRefresh()
    }

    func turnOff() {
        Keychain.deletePassword(for: address)
        isOn = false
        cursorFor = ""
        state = .idle
    }

    private var cursorKey: String { "\(address.lowercased())|\(label)" }

    private func startFromNow(_ client: IMAPClient) async throws {
        if let next = client.uidNext {
            lastUID = next - 1
        } else {
            lastUID = try await client.searchBudget(after: 0).max() ?? 0
        }
        uidValidity = client.uidValidity ?? 0
        cursorFor = cursorKey
    }

    // MARK: checking

    /// `force`: the Check now button. Otherwise a check that just happened is enough.
    func check(force: Bool = false) async {
        guard isOn, state != .checking else { return }
        if !force, let t = lastCheck, Date().timeIntervalSince(t) < 30 { return }
        guard let password = Keychain.password(for: address) else {
            state = .failed("Enter your Gmail app password again in Settings.")
            return
        }
        state = .checking
        let client = IMAPClient.gmail()
        defer { client.close() }
        do {
            var added = 0
            try await withDeadline(client) {
                try await client.open()
                try await client.login(self.address, password)
                try await client.examine(self.label)
                if self.cursorFor != self.cursorKey || (client.uidValidity ?? 0) != self.uidValidity {
                    try await self.startFromNow(client)       // Gmail renumbered the label: only read new emails
                    return
                }
                let uids = try await client.searchBudget(after: self.lastUID)
                for (uid, raw) in try await client.fetch(uids) {
                    if self.importEmail(Mail(raw)) { added += 1 }
                    self.lastUID = max(self.lastUID, uid)
                }
            }
            try context.save()
            lastAdded = added
            lastCheck = Date()
            UserDefaults.standard.set(lastCheck, forKey: "gmailLastCheck")
            state = .idle
            if added > 0 { sync.soon() }
        } catch let e as GmailError {
            state = .failed(e.text)
        } catch {
            state = .failed("Couldn't reach Gmail. Check that the phone is online.")
        }
    }

    /// Add the expense in this email, if it's clearly fine. Returns whether one was added.
    func importEmail(_ mail: Mail) -> Bool {
        guard mail.subjectOK, senderProblem(mail, myAddress: address) == nil else { return false }
        let uid = emailExpenseUID(mail.messageID)
        let exists = (try? context.fetchCount(FetchDescriptor<Expense>(predicate: #Predicate { $0.uid == uid }))) ?? 0
        guard exists == 0, !ForgottenEmails.contains(uid) else { return false }     // the Mac's copy, or you deleted it
        guard let tx = findTransaction(mail.text), tx.problem == nil, let date = tx.date, let cents = tx.amountCents else {
            return false
        }
        guard !looksTyped(date: date, cents: cents, merchant: tx.merchant) else { return false }
        let s = suggestCategory(tx.merchant, rules: (try? context.fetch(FetchDescriptor<MerchantRule>())) ?? [],
                                keywords: (try? context.fetch(FetchDescriptor<KeywordRule>())) ?? [])
        context.insert(Expense(uid: uid, amountCents: cents, merchant: tx.merchant, date: date,
                               categoryUid: s.categoryUid, categorySource: s.source, source: "email"))
        return true
    }

    /// Same amount, a similar merchant, within a day, and typed by hand or from a bank file.
    private func looksTyped(date: String, cents: Int, merchant: String) -> Bool {
        let d = day(date)
        let from = iso(mondayCalendar.date(byAdding: .day, value: -1, to: d)!)
        let to = iso(mondayCalendar.date(byAdding: .day, value: 1, to: d)!)
        let candidates = (try? context.fetch(FetchDescriptor<Expense>(predicate: #Predicate {
            $0.amountCents == cents && $0.date >= from && $0.date <= to && $0.source != "email"
        }))) ?? []
        let norm = normalizeMerchant(merchant)
        let words = Set(norm.split(separator: " ").filter { $0.count >= 3 })
        return candidates.contains { c in
            c.merchantNorm == norm || c.merchantNorm.contains(norm) || norm.contains(c.merchantNorm)
                || !words.isDisjoint(with: c.merchantNorm.split(separator: " "))
        }
    }

    /// Gmail can hang on a bad network: give up after 40 seconds.
    private func withDeadline(_ client: IMAPClient, _ work: () async throws -> Void) async throws {
        let timer = Task { try await Task.sleep(nanoseconds: 40_000_000_000); client.close() }
        defer { timer.cancel() }
        try await work()
    }

    // MARK: in the background

    /// iOS decides when this runs (usually every few hours); opening the app always checks.
    func backgroundRefresh() async {
        Self.scheduleRefresh()
        await sync.sync()
        await check()
        await sync.sync()
    }

    static func scheduleRefresh() {
        let r = BGAppRefreshTaskRequest(identifier: refreshTask)
        r.earliestBeginDate = Date(timeIntervalSinceNow: 30 * 60)
        try? BGTaskScheduler.shared.submit(r)
    }
}

/// Expenses from emails that were deleted (here or on the Mac), so they aren't added again.
enum ForgottenEmails {
    private static let key = "forgottenEmailExpenses"

    static func contains(_ uid: String) -> Bool { (UserDefaults.standard.stringArray(forKey: key) ?? []).contains(uid) }

    static func add(_ uid: String) {
        var all = UserDefaults.standard.stringArray(forKey: key) ?? []
        guard !all.contains(uid) else { return }
        all.append(uid)
        UserDefaults.standard.set(Array(all.suffix(2000)), forKey: key)
    }
}
