import Foundation
import SwiftData

/// Every change made on the phone goes through here: it's saved, marked as not
/// sent yet, and a sync is asked for.
@MainActor struct Store {
    let ctx: ModelContext
    let sync: SyncEngine

    func save() {
        try? ctx.save()
        sync.soon()
    }

    // MARK: expenses

    @discardableResult
    func addExpense(amountCents: Int, merchant: String, date: String, note: String?, categoryUid: String?,
                    categorySource: String, repeatMonthly: Bool) -> Expense {
        var recurringUid: String?
        if repeatMonthly {
            let d = day(date)
            let dom = mondayCalendar.component(.day, from: d)
            let bill = Bill(merchant: merchant, amountCents: amountCents, categoryUid: categoryUid, note: note, day: dom,
                            nextDate: iso(nextMonth(after: d, day: dom)))
            ctx.insert(bill)
            recurringUid = bill.uid
        }
        let e = Expense(amountCents: amountCents, merchant: merchant, date: date, note: note, categoryUid: categoryUid,
                        categorySource: categorySource, recurringUid: recurringUid)
        if let recurringUid { e.uid = occurrenceUID(recurringUid, date) }
        ctx.insert(e)
        if categorySource == "manual" { learn(merchant, categoryUid) }
        save()
        return e
    }

    func update(_ e: Expense, amountCents: Int, merchant: String, date: String, note: String?, categoryUid: String?, categorySource: String) {
        if categorySource == "manual" && categoryUid != e.categoryUid { learn(merchant, categoryUid) }
        e.amountCents = amountCents; e.merchant = merchant; e.merchantNorm = normalizeMerchant(merchant); e.date = date
        e.note = note; e.categoryUid = categoryUid; e.categorySource = categorySource
        touch(e)
        save()
    }

    func delete(_ e: Expense) {
        if e.source == "email" { ForgottenEmails.add(e.uid) }     // so a Gmail check doesn't bring it back
        ctx.insert(Tombstone(table: "expenses", key: e.uid))
        ctx.delete(e)
        save()
    }

    func touch(_ e: Expense) { e.modifiedAt = nowStamp(); e.dirty = true }

    /// Remember your choice for this merchant (it wins next time, on both devices).
    func learn(_ merchant: String, _ categoryUid: String?) {
        let norm = normalizeMerchant(merchant)
        guard !norm.isEmpty, let categoryUid else { return }
        if let r = try? ctx.fetch(FetchDescriptor<MerchantRule>(predicate: #Predicate { $0.merchantNorm == norm })).first {
            r.categoryUid = categoryUid; r.hitCount += 1; r.modifiedAt = nowStamp(); r.dirty = true
        } else {
            ctx.insert(MerchantRule(merchantNorm: norm, categoryUid: categoryUid))
        }
    }

    // MARK: budgets

    func setLimit(categoryUid: String?, period: String, cents: Int?) {
        let all = (try? ctx.fetch(FetchDescriptor<BudgetLimit>())) ?? []
        let existing = all.first { $0.categoryUid == categoryUid && $0.period == period }
        switch (existing, cents) {
        case (let b?, let c?): b.limitCents = c; b.modifiedAt = nowStamp(); b.dirty = true
        case (let b?, nil): ctx.insert(Tombstone(table: "budgets", key: b.uid)); ctx.delete(b)
        case (nil, let c?): ctx.insert(BudgetLimit(categoryUid: categoryUid, period: period, limitCents: c))
        case (nil, nil): break
        }
        save()
    }

    // MARK: bills, categories, settings

    func delete(_ b: Bill) {
        for e in (try? ctx.fetch(FetchDescriptor<Expense>())) ?? [] where e.recurringUid == b.uid { e.recurringUid = nil; touch(e) }
        ctx.insert(Tombstone(table: "recurring", key: b.uid))
        ctx.delete(b)
        save()
    }

    func addCategory(name: String, color: String) {
        let count = (try? ctx.fetchCount(FetchDescriptor<Category>())) ?? 0
        ctx.insert(Category(name: name, color: color, sortOrder: count))
        save()
    }

    func setTheme(_ id: String) {
        let s = (try? ctx.fetch(FetchDescriptor<AppSetting>(predicate: #Predicate { $0.key == "preferences" })).first)
        var prefs = (s.flatMap { try? JSONSerialization.jsonObject(with: Data($0.json.utf8)) as? [String: Any] }) ?? [:]
        prefs["theme"] = id
        let json = String(data: (try? JSONSerialization.data(withJSONObject: prefs)) ?? Data("{}".utf8), encoding: .utf8) ?? "{}"
        if let s { s.json = json; s.modifiedAt = nowStamp(); s.dirty = true } else { ctx.insert(AppSetting(key: "preferences", json: json)) }
        save()
    }
}

func themeID(_ settings: [AppSetting]) -> String {
    guard let s = settings.first(where: { $0.key == "preferences" }),
          let prefs = try? JSONSerialization.jsonObject(with: Data(s.json.utf8)) as? [String: Any] else { return "auto" }
    return prefs["theme"] as? String ?? "auto"
}
