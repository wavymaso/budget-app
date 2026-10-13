import Foundation
import SwiftData

// Your data on the phone. The same rows as on the Mac, linked by `uid` (the same
// on both devices) instead of numbers. `dirty` = changed here, not sent yet.

@Model final class Category {
    @Attribute(.unique) var uid: String
    var name: String
    var color: String
    var sortOrder: Int
    var modifiedAt: String
    var dirty: Bool

    init(uid: String = newUID(), name: String, color: String, sortOrder: Int = 0, modifiedAt: String = nowStamp(), dirty: Bool = true) {
        self.uid = uid; self.name = name; self.color = color; self.sortOrder = sortOrder
        self.modifiedAt = modifiedAt; self.dirty = dirty
    }
}

@Model final class Expense {
    @Attribute(.unique) var uid: String
    var amountCents: Int            // positive = spending, negative = refund
    var merchant: String
    var merchantNorm: String
    var date: String                // yyyy-MM-dd
    var note: String?
    var categoryUid: String?
    var categorySource: String      // learned | rule | fuzzy | ai | manual | none
    var source: String              // manual | csv | api | recurring | phone ...
    var recurringUid: String?
    var createdAt: String
    var modifiedAt: String
    var dirty: Bool

    init(uid: String = newUID(), amountCents: Int, merchant: String, date: String, note: String? = nil,
         categoryUid: String? = nil, categorySource: String = "none", source: String = "phone", recurringUid: String? = nil,
         createdAt: String = nowStamp(), modifiedAt: String = nowStamp(), dirty: Bool = true) {
        self.uid = uid; self.amountCents = amountCents; self.merchant = merchant
        self.merchantNorm = normalizeMerchant(merchant); self.date = date; self.note = note
        self.categoryUid = categoryUid; self.categorySource = categorySource; self.source = source
        self.recurringUid = recurringUid; self.createdAt = createdAt; self.modifiedAt = modifiedAt; self.dirty = dirty
    }
}

@Model final class BudgetLimit {
    @Attribute(.unique) var uid: String
    var categoryUid: String?        // nil = overall
    var period: String              // week | month
    var limitCents: Int
    var modifiedAt: String
    var dirty: Bool

    init(uid: String = newUID(), categoryUid: String?, period: String, limitCents: Int, modifiedAt: String = nowStamp(), dirty: Bool = true) {
        self.uid = uid; self.categoryUid = categoryUid; self.period = period; self.limitCents = limitCents
        self.modifiedAt = modifiedAt; self.dirty = dirty
    }
}

@Model final class Bill {
    @Attribute(.unique) var uid: String
    var merchant: String
    var amountCents: Int
    var categoryUid: String?
    var note: String?
    var day: Int
    var nextDate: String
    var modifiedAt: String
    var dirty: Bool

    init(uid: String = newUID(), merchant: String, amountCents: Int, categoryUid: String?, note: String?, day: Int,
         nextDate: String, modifiedAt: String = nowStamp(), dirty: Bool = true) {
        self.uid = uid; self.merchant = merchant; self.amountCents = amountCents; self.categoryUid = categoryUid
        self.note = note; self.day = day; self.nextDate = nextDate; self.modifiedAt = modifiedAt; self.dirty = dirty
    }
}

@Model final class SavingsMove {
    @Attribute(.unique) var uid: String
    var date: String
    var amountCents: Int
    var note: String?
    var modifiedAt: String
    var dirty: Bool

    init(uid: String = newUID(), date: String, amountCents: Int, note: String?, modifiedAt: String = nowStamp(), dirty: Bool = true) {
        self.uid = uid; self.date = date; self.amountCents = amountCents; self.note = note
        self.modifiedAt = modifiedAt; self.dirty = dirty
    }
}

/// "This merchant is this category": your own choices, learned as you go.
@Model final class MerchantRule {
    @Attribute(.unique) var merchantNorm: String
    var categoryUid: String?
    var hitCount: Int
    var modifiedAt: String
    var dirty: Bool

    init(merchantNorm: String, categoryUid: String?, hitCount: Int = 1, modifiedAt: String = nowStamp(), dirty: Bool = true) {
        self.merchantNorm = merchantNorm; self.categoryUid = categoryUid; self.hitCount = hitCount
        self.modifiedAt = modifiedAt; self.dirty = dirty
    }
}

/// Built-in keywords for common merchants (from the Mac; read-only here).
@Model final class KeywordRule {
    @Attribute(.unique) var keyword: String
    var categoryUid: String?
    init(keyword: String, categoryUid: String?) { self.keyword = keyword; self.categoryUid = categoryUid }
}

/// A finished month's savings, worked out on the Mac.
@Model final class SavingsMonth {
    @Attribute(.unique) var month: String
    var limitCents: Int?
    var spentCents: Int
    var savedCents: Int
    init(month: String, limitCents: Int?, spentCents: Int, savedCents: Int) {
        self.month = month; self.limitCents = limitCents; self.spentCents = spentCents; self.savedCents = savedCents
    }
}

/// Shared settings as JSON: "preferences" (theme) and "savings" (goal).
@Model final class AppSetting {
    @Attribute(.unique) var key: String
    var json: String
    var modifiedAt: String
    var dirty: Bool
    init(key: String, json: String, modifiedAt: String = nowStamp(), dirty: Bool = true) {
        self.key = key; self.json = json; self.modifiedAt = modifiedAt; self.dirty = dirty
    }
}

/// Something deleted here, waiting to be deleted on the Mac too.
@Model final class Tombstone {
    var table: String
    var key: String
    var deletedAt: String
    init(table: String, key: String, deletedAt: String = nowStamp()) { self.table = table; self.key = key; self.deletedAt = deletedAt }
}

let allModels: [any PersistentModel.Type] = [Category.self, Expense.self, BudgetLimit.self, Bill.self, SavingsMove.self,
                                             MerchantRule.self, KeywordRule.self, SavingsMonth.self, AppSetting.self, Tombstone.self]

// MARK: - ids and times

func newUID() -> String { UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased() }

private let stampFormatter: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    f.timeZone = TimeZone(identifier: "UTC")
    return f
}()

/// "2026-10-13T14:32:05.123Z": sorts as text in time order, like the Mac's.
func nowStamp() -> String { stampFormatter.string(from: Date()) }

func parseStamp(_ s: String) -> Date? { stampFormatter.date(from: s) }
