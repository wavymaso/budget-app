import Foundation
import SwiftData

// The same rules as the Mac app (app/normalize.py, app/budgets.py, app/categorizer.py),
// so both devices agree on every number.

// MARK: - Merchant names

private let noiseWords: Set<String> = [
    "madrid", "barcelona", "valencia", "sevilla", "alcala", "henares", "getafe", "mostoles", "leganes", "alcobendas",
    "pozuelo", "majadahonda", "fuenlabrada", "alcorcon", "torrejon", "boadilla", "rivas", "parla", "aravaca", "chamartin",
    "chamberi", "moncloa", "salamanca", "retiro", "centro", "sol", "atocha", "es", "esp", "spain", "espana", "eu", "ue",
    "sa", "sl", "slu", "sau", "sll", "scoop", "ltd", "inc", "gmbh", "bv", "llc", "srl",
    "compra", "pago", "en", "tarjeta", "tarj", "card", "purchase", "pos", "tpv", "contactless", "paypal", "sumup", "sq",
    "zettle", "ref", "www",
]

private func plainLower(_ s: String) -> String {
    s.folding(options: [.diacriticInsensitive, .widthInsensitive], locale: Locale(identifier: "en_US_POSIX")).lowercased()
}

private func alnumSpaced(_ s: String) -> String {
    String(s.map { ($0.isASCII && ($0.isLetter || $0.isNumber)) ? $0 : " " })
}

/// "MERCADONA MADRID 4521" -> "mercadona", "UBER *EATS" -> "uber eats", "McDonald's" -> "mcdonalds".
func normalizeMerchant(_ raw: String) -> String {
    var text = plainLower(raw)
    text = text.replacingOccurrences(of: "['’`´]", with: "", options: .regularExpression)
    text = text.replacingOccurrences(of: "(?<=\\w)&(?=\\w)", with: "", options: .regularExpression)
    let tokens = alnumSpaced(text).split(separator: " ").map(String.init).filter { t in
        t.count > 1 && !t.contains(where: \.isNumber) && !noiseWords.contains(t)
    }
    if !tokens.isEmpty { return tokens.joined(separator: " ") }
    return alnumSpaced(plainLower(raw)).split(separator: " ").joined(separator: " ")
}

// MARK: - Categories

struct Suggestion { let categoryUid: String?; let source: String }

/// Your own choice for this merchant first, then the built-in keywords.
/// (The Mac also tries close spellings and AI; it fills in what's left when it syncs.)
func suggestCategory(_ merchant: String, rules: [MerchantRule], keywords: [KeywordRule]) -> Suggestion {
    let norm = normalizeMerchant(merchant)
    guard !norm.isEmpty else { return Suggestion(categoryUid: nil, source: "none") }
    if let r = rules.first(where: { $0.merchantNorm == norm }), r.categoryUid != nil {
        return Suggestion(categoryUid: r.categoryUid, source: "learned")
    }
    let padded = " \(norm) "
    let tokens = norm.split(separator: " ").map(String.init)
    var best: (rank: (Int, Int), uid: String?)?
    for k in keywords {
        let kw = k.keyword
        var rank: (Int, Int)?
        if padded.contains(" \(kw) ") || (kw.contains(" ") && tokens.contains(kw.replacingOccurrences(of: " ", with: ""))) {
            rank = (1, kw.count)
        } else if !kw.contains(" "), kw.count >= 5, tokens.contains(where: { $0.hasPrefix(kw) }) {
            rank = (0, kw.count)
        }
        if let r = rank, best == nil || r > best!.rank { best = (r, k.categoryUid) }
    }
    if let b = best { return Suggestion(categoryUid: b.uid, source: "rule") }
    return Suggestion(categoryUid: nil, source: "none")
}

// MARK: - Dates (weeks run Monday to Sunday)

let isoDay: DateFormatter = {
    let f = DateFormatter()
    f.calendar = Calendar(identifier: .gregorian)
    f.locale = Locale(identifier: "en_US_POSIX")
    f.dateFormat = "yyyy-MM-dd"
    return f
}()

var mondayCalendar: Calendar = {
    var c = Calendar(identifier: .gregorian)
    c.firstWeekday = 2
    c.locale = Locale(identifier: "en_GB")
    return c
}()

func iso(_ d: Date) -> String { isoDay.string(from: d) }
func day(_ s: String) -> Date { isoDay.date(from: s) ?? Date() }
func today() -> Date { mondayCalendar.startOfDay(for: Date()) }

func weekBounds(_ d: Date) -> (Date, Date) {
    let cal = mondayCalendar
    let weekday = (cal.component(.weekday, from: d) + 5) % 7      // Monday = 0
    let start = cal.date(byAdding: .day, value: -weekday, to: cal.startOfDay(for: d))!
    return (start, cal.date(byAdding: .day, value: 6, to: start)!)
}

func monthBounds(_ d: Date) -> (Date, Date) {
    let cal = mondayCalendar
    let start = cal.date(from: cal.dateComponents([.year, .month], from: d))!
    let end = cal.date(byAdding: DateComponents(month: 1, day: -1), to: start)!
    return (start, end)
}

func bounds(_ period: String, _ d: Date) -> (Date, Date) { period == "week" ? weekBounds(d) : monthBounds(d) }

/// Days remaining in the period, counting today.
func daysLeft(_ start: Date, _ end: Date, _ now: Date) -> Int {
    let cal = mondayCalendar
    if now < start { return cal.dateComponents([.day], from: start, to: end).day! + 1 }
    if now > end { return 0 }
    return cal.dateComponents([.day], from: cal.startOfDay(for: now), to: end).day! + 1
}

enum Level { case green, amber, red }

/// Green under 75%, amber from 75% up to 100%, red when over.
func level(spent: Int, limit: Int?) -> Level? {
    guard let limit else { return nil }
    if limit <= 0 { return spent > 0 ? .red : .green }
    let pct = Double(spent) * 100 / Double(limit)
    return pct > 100 ? .red : pct >= 75 ? .amber : .green
}

struct PeriodSummary {
    let spent: Int
    let limit: Int?
    let daysLeft: Int
    var left: Int? { limit.map { $0 - spent } }
    var perDay: Int? { guard let left, daysLeft > 0 else { return nil }; return max(left, 0) / daysLeft }
    var level: Level? { Budget.level(spent: spent, limit: limit) }
    var fraction: Double { guard let limit, limit > 0 else { return 0 }; return min(1, max(0, Double(spent) / Double(limit))) }
}

func summarize(_ expenses: [Expense], limits: [BudgetLimit], period: String, categoryUid: String?? = .none,
               on d: Date = today()) -> PeriodSummary {
    let (start, end) = bounds(period, d)
    let s = iso(start), e = iso(end)
    let spent = expenses.filter { x in
        x.date >= s && x.date <= e && { if case .some(let c) = categoryUid { return x.categoryUid == c } else { return true } }()
    }.reduce(0) { $0 + $1.amountCents }
    let catKey: String? = { if case .some(let c) = categoryUid { return c } else { return nil } }()
    let limit = limits.first { $0.period == period && $0.categoryUid == catKey }?.limitCents
    return PeriodSummary(spent: spent, limit: limit, daysLeft: daysLeft(start, end, d))
}

// MARK: - Monthly bills

/// The same bill on the same day gets the same id on the Mac and the phone, so it's only added once.
func occurrenceUID(_ billUid: String, _ date: String) -> String { "rec:\(billUid):\(date)" }

func nextMonth(after d: Date, day dayOfMonth: Int) -> Date {
    let cal = mondayCalendar
    let firstOfNext = cal.date(byAdding: .month, value: 1, to: monthBounds(d).0)!
    let lastDay = cal.range(of: .day, in: .month, for: firstOfNext)!.count
    return cal.date(bySetting: .day, value: min(dayOfMonth, lastDay), of: firstOfNext) ?? firstOfNext
}

/// Add every bill whose date has come (catching up on missed months, up to a year).
@MainActor func addDueBills(_ ctx: ModelContext) {
    let now = today()
    guard let bills = try? ctx.fetch(FetchDescriptor<Bill>()) else { return }
    for b in bills where b.nextDate <= iso(now) {
        var next = day(b.nextDate)
        var steps = 0
        while next <= now && steps < 12 {
            let uid = occurrenceUID(b.uid, iso(next))
            let exists = (try? ctx.fetchCount(FetchDescriptor<Expense>(predicate: #Predicate { $0.uid == uid }))) ?? 0
            if exists == 0 {
                ctx.insert(Expense(uid: uid, amountCents: b.amountCents, merchant: b.merchant, date: iso(next), note: b.note,
                                   categoryUid: b.categoryUid, categorySource: b.categoryUid == nil ? "none" : "manual",
                                   source: "recurring", recurringUid: b.uid))
            }
            next = nextMonth(after: next, day: b.day)
            steps += 1
        }
        while next <= now { next = nextMonth(after: next, day: b.day) }
        b.nextDate = iso(next); b.modifiedAt = nowStamp(); b.dirty = true
    }
    try? ctx.save()
}

// MARK: - Money

let euro: NumberFormatter = {
    let f = NumberFormatter()
    f.numberStyle = .currency
    f.locale = Locale(identifier: "es_ES")
    f.currencyCode = "EUR"
    return f
}()

func money(_ cents: Int, whole: Bool = false) -> String {
    euro.maximumFractionDigits = whole ? 0 : 2
    euro.minimumFractionDigits = whole ? 0 : 2
    return euro.string(from: NSNumber(value: Double(cents) / 100)) ?? "\(cents / 100) €"
}

/// "12,50", "12.50", "1.234,56" -> cents.
func parseAmount(_ text: String) -> Int? {
    var t = text.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: "€", with: "").replacingOccurrences(of: " ", with: "")
    if t.contains(",") { t = t.replacingOccurrences(of: ".", with: "").replacingOccurrences(of: ",", with: ".") }
    guard let v = Decimal(string: t, locale: Locale(identifier: "en_US_POSIX")), v > 0 else { return nil }
    var cents = v * 100, rounded = Decimal()
    NSDecimalRound(&rounded, &cents, 0, .plain)
    return NSDecimalNumber(decimal: rounded).intValue
}
