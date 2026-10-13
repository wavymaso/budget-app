import SwiftUI
import SwiftData

/// One clear number first, then this week, where it went, and recent expenses.
struct HomeView: View {
    @Binding var tab: Int
    @Environment(\.theme) private var theme
    @EnvironmentObject private var sync: SyncEngine
    @Query(sort: \Expense.date, order: .reverse) private var expenses: [Expense]
    @Query(sort: \Category.sortOrder) private var categories: [Category]
    @Query private var limits: [BudgetLimit]
    @State private var editing: Expense?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 14) {
                    HStack { SyncBadge(); Spacer() }.padding(.horizontal, 4)
                    if !sync.isConnected && expenses.isEmpty {
                        connectCard
                    }
                    hero
                    whereItWent
                    recent
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 24)
            }
            .background(theme.background.ignoresSafeArea())
            .navigationTitle("Budget")
            .refreshable { await sync.sync() }
            .sheet(item: $editing) { e in ExpenseSheet(expense: e) }
        }
    }

    private var month: PeriodSummary { summarize(expenses, limits: limits, period: "month") }
    private var week: PeriodSummary { summarize(expenses, limits: limits, period: "week") }

    private var hero: some View {
        Card {
            let m = month
            if let left = m.left {
                Text("Left this month").font(.subheadline).foregroundStyle(theme.secondary)
                Text(money(left)).font(theme.display(46)).foregroundStyle(left < 0 ? theme.levelColor(.red) : theme.text)
                    .minimumScaleFactor(0.6).lineLimit(1).padding(.top, 2)
                if let perDay = m.perDay, m.daysLeft > 0 {
                    Text("\(money(perDay)) a day for \(m.daysLeft) \(m.daysLeft == 1 ? "day" : "days")")
                        .font(.subheadline).foregroundStyle(theme.secondary)
                }
                ProgressView(value: m.fraction).tint(theme.levelColor(m.level)).padding(.top, 12)
                Text("Spent \(money(m.spent)) of \(money(m.limit ?? 0))").font(.footnote).foregroundStyle(theme.faint).padding(.top, 4)
            } else {
                Text("Spent in \(today().formatted(.dateTime.month(.wide)))").font(.subheadline).foregroundStyle(theme.secondary)
                Text(money(m.spent)).font(theme.display(46)).foregroundStyle(theme.text).padding(.top, 2)
                Button("Set a monthly budget") { tab = 3 }
                    .font(.subheadline.weight(.medium)).buttonStyle(.bordered).padding(.top, 8)
            }
            Divider().padding(.vertical, 14)
            HStack {
                Text("This week").foregroundStyle(theme.secondary)
                Spacer()
                let w = week
                if let left = w.left {
                    Text("\(money(left)) left").foregroundStyle(theme.levelColor(w.level)).fontWeight(.medium)
                } else {
                    Text("\(money(w.spent)) spent").foregroundStyle(theme.text)
                }
            }.font(.subheadline)
        }
    }

    private var whereItWent: some View {
        let (start, end) = monthBounds(today())
        let s = iso(start), e = iso(end)
        let inMonth = expenses.filter { $0.date >= s && $0.date <= e }
        var spent: [String?: Int] = [:]
        for x in inMonth { spent[x.categoryUid, default: 0] += x.amountCents }
        let total = max(1, spent.values.reduce(0, +))
        let rows: [(name: String, color: Color, cents: Int, limit: Int?)] = spent
            .map { uid, cents in
                let c = categories.first { $0.uid == uid }
                let lim = limits.first { $0.period == "month" && $0.categoryUid == uid && uid != nil }?.limitCents
                return (c?.name ?? "Uncategorized", c.map { Color(hex: $0.color) } ?? theme.faint, cents, lim)
            }
            .filter { $0.cents != 0 }
            .sorted { $0.cents > $1.cents }
        return Group {
            if !rows.isEmpty {
                Card {
                    Text("Where it went").font(.headline).foregroundStyle(theme.text).padding(.bottom, 10)
                    ForEach(rows.prefix(6), id: \.name) { r in
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Circle().fill(r.color).frame(width: 8, height: 8)
                                Text(r.name).foregroundStyle(theme.text)
                                Spacer()
                                Text(r.limit.map { "\(money(r.cents)) / \(money($0, whole: true))" } ?? money(r.cents))
                                    .foregroundStyle(theme.text).monospacedDigit()
                            }.font(.subheadline)
                            let frac = r.limit.map { Double(r.cents) / Double(max($0, 1)) } ?? Double(r.cents) / Double(total)
                            ProgressView(value: min(1, max(0, frac)))
                                .tint(r.limit != nil ? theme.levelColor(level(spent: r.cents, limit: r.limit)) : r.color)
                        }.padding(.vertical, 5)
                    }
                }
            }
        }
    }

    private var recent: some View {
        Group {
            if !expenses.isEmpty {
                Card {
                    HStack {
                        Text("Recent").font(.headline).foregroundStyle(theme.text)
                        Spacer()
                        Button("See all") { tab = 1 }.font(.subheadline)
                    }.padding(.bottom, 6)
                    ForEach(Array(expenses.sorted { ($0.date, $0.createdAt) > ($1.date, $1.createdAt) }.prefix(6))) { e in
                        Button { editing = e } label: { ExpenseRow(expense: e, categories: categories) }
                            .buttonStyle(.plain)
                        if e.uid != expenses.prefix(6).last?.uid { Divider() }
                    }
                }
            }
        }
    }

    private var connectCard: some View {
        Card {
            Text("Connect to your Mac").font(.headline).foregroundStyle(theme.text)
            Text("Budget works on its own here. Connect it once to bring over everything from the Mac and keep both in sync.")
                .font(.subheadline).foregroundStyle(theme.secondary).padding(.top, 4)
            Button("Connect") { tab = 3 }.buttonStyle(.borderedProminent).padding(.top, 10)
        }
    }
}

struct ExpenseRow: View {
    let expense: Expense
    let categories: [Category]
    @Environment(\.theme) private var theme

    var body: some View {
        let c = categories.first { $0.uid == expense.categoryUid }
        HStack(spacing: 12) {
            ZStack {
                Circle().fill((c.map { Color(hex: $0.color) } ?? Color.orange).opacity(0.18))
                Text(c.map { String($0.name.prefix(1)) } ?? "?").font(.subheadline.weight(.semibold))
                    .foregroundStyle(c.map { Color(hex: $0.color) } ?? Color.orange)
            }.frame(width: 38, height: 38)
            VStack(alignment: .leading, spacing: 2) {
                Text(expense.merchant).foregroundStyle(theme.text).lineLimit(1)
                Text("\(c?.name ?? "Needs a category") · \(relativeDay(expense.date))")
                    .font(.caption).foregroundStyle(c == nil ? Color.orange : theme.secondary)
            }
            Spacer()
            HStack(spacing: 4) {
                if expense.dirty { Image(systemName: "arrow.up.circle").font(.caption2).foregroundStyle(theme.faint) }
                Text(money(-expense.amountCents < 0 ? expense.amountCents : expense.amountCents))
                    .foregroundStyle(expense.amountCents < 0 ? theme.levelColor(.green) : theme.text).monospacedDigit()
            }
        }
        .padding(.vertical, 8)
        .contentShape(Rectangle())
    }
}

func relativeDay(_ isoDate: String) -> String {
    let d = day(isoDate), t = today()
    if d == t { return "Today" }
    if d == mondayCalendar.date(byAdding: .day, value: -1, to: t) { return "Yesterday" }
    return d.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated).locale(Locale(identifier: "en_GB")))
}
