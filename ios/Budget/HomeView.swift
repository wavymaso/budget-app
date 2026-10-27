import SwiftUI
import SwiftData

/// Campo: the field's colour is the budget's state. What's left this month on the field, a ring
/// (spent against the plan for today), this week as seven flat tiles; then where it went as one
/// flat band, and recent expenses.
struct HomeView: View {
    @Binding var tab: Int
    @Environment(\.theme) private var theme
    @EnvironmentObject private var sync: SyncEngine
    @Query(sort: \Expense.date, order: .reverse) private var expenses: [Expense]
    @Query(sort: \Category.sortOrder) private var categories: [Category]
    @Query private var limits: [BudgetLimit]
    @Query private var bills: [Bill]
    @State private var editing: Expense?
    @ScaledMetric(relativeTo: .largeTitle) private var bigSize: CGFloat = 68

    private var month: PeriodSummary { summarize(expenses, limits: limits, period: "month") }
    private var week: PeriodSummary { summarize(expenses, limits: limits, period: "week") }
    private var pace: MonthPace { monthPace(expenses, limits: limits, bills: bills) }

    var body: some View {
        let state = pace.state
        NavigationStack {
            ScrollView {
                VStack(spacing: 0) {
                    field(state)
                    VStack(spacing: 14) {
                        if !sync.isConnected && expenses.isEmpty { connectCard }
                        whereItWent
                        recent
                    }
                    .padding(.horizontal, 16).padding(.top, 22).padding(.bottom, 24)
                    .frame(maxWidth: .infinity)
                    .background(theme.background, in: UnevenRoundedRectangle(topLeadingRadius: 28, topTrailingRadius: 28, style: .continuous))
                    .padding(.top, -28)
                }
            }
            .background(alignment: .top) {
                // The field runs up under the bar; the page ground below.
                VStack(spacing: 0) { theme.field(state).frame(height: 600); theme.background }.ignoresSafeArea()
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    HStack(spacing: 8) {
                        Text("€").font(.system(size: 15, weight: .black)).foregroundStyle(theme.field(state))
                            .frame(width: 30, height: 30).background(.white, in: Circle())
                        Text("Budget").font(.headline.weight(.bold)).foregroundStyle(.white)
                    }
                    .accessibilityElement(children: .combine).accessibilityLabel("Budget")
                }
                ToolbarItem(placement: .topBarTrailing) { SyncBadge().colorScheme(.dark) }
            }
            .toolbarBackground(theme.field(state), for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .navigationBarTitleDisplayMode(.inline)
            .refreshable { await sync.sync() }
            .sheet(item: $editing) { e in ExpenseSheet(expense: e) }
            .animation(.smooth(duration: 0.6), value: state)
        }
    }

    // MARK: The field

    private func field(_ state: BudgetState?) -> some View {
        let m = month, p = pace
        let monthName = today().formatted(.dateTime.month(.wide).locale(Locale(identifier: "en_GB")))
        return VStack(alignment: .leading, spacing: 0) {
                if let limit = m.limit, limit > 0 {
                    HStack { Spacer(); Ring(spent: m.fraction, plan: p.planCents.map { Double($0) / Double(limit) }, daysLeft: m.daysLeft, deep: theme.fieldDeep(state)) }
                        .padding(.bottom, -18)
                    let over = (m.left ?? 0) < 0
                    Text(over ? "Over budget in \(monthName) by" : "Left to spend in \(monthName)")
                        .font(.subheadline.weight(.semibold)).foregroundStyle(.white.opacity(0.86))
                    bigMoney(abs(m.left ?? 0)).padding(.top, 4)
                    Group {
                        if over {
                            Text("\(m.daysLeft) \(m.daysLeft == 1 ? "day" : "days") to go.")
                        } else {
                            let perDay = m.daysLeft > 0 ? max(0, (m.left ?? 0) - p.upcomingBillsCents) / m.daysLeft : 0
                            Text("About **\(money(perDay))** a day for \(m.daysLeft) \(m.daysLeft == 1 ? "day" : "days")")
                        }
                    }
                    .font(.body.weight(.medium)).foregroundStyle(.white.opacity(0.9)).padding(.top, 8)
                    statePill(state == .red ? "Over: \(money(m.spent)) of \(money(limit, whole: true))"
                              : state == .amber ? "\(money(-(p.diffCents ?? 0))) ahead of plan"
                              : (p.diffCents ?? 0) >= Int(Double(p.everydayCents ?? 0) * 0.03) && (p.diffCents ?? 0) > 0 ? "\(money(p.diffCents ?? 0)) under plan" : "On plan")
                        .padding(.top, 14)
                } else {
                    Text("Spent in \(monthName)").font(.subheadline.weight(.semibold)).foregroundStyle(.white.opacity(0.86)).padding(.top, 12)
                    bigMoney(m.spent).padding(.top, 4)
                    Button("Set a monthly budget") { tab = 3 }
                        .font(.subheadline.weight(.semibold)).foregroundStyle(theme.field(state))
                        .padding(.horizontal, 16).padding(.vertical, 10).background(.white, in: Capsule()).padding(.top, 14)
                }
                weekRow.padding(.top, 26)
            }
        .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 48)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(alignment: .topTrailing) {
            // The deeper disc bleeding off the corner (decoration: it never sizes the field).
            Circle().fill(theme.fieldDeep(state)).frame(width: 560, height: 560).offset(x: 250, y: -300).accessibilityHidden(true)
        }
        .background(theme.field(state))
        .clipped()
        .foregroundStyle(.white)
    }

    private func bigMoney(_ cents: Int) -> some View {
        let text = money(cents).replacingOccurrences(of: " €", with: "").replacingOccurrences(of: "\u{00a0}€", with: "")
        return HStack(alignment: .top, spacing: 2) {
            Text(text).font(.system(size: bigSize, weight: .black)).tracking(-bigSize * 0.045).monospacedDigit()
            Text("€").font(.system(size: bigSize * 0.48, weight: .black)).padding(.top, bigSize * 0.08)
        }
        .lineLimit(1).minimumScaleFactor(0.5)
        .accessibilityElement(children: .ignore).accessibilityLabel(money(cents))
    }

    private func statePill(_ text: String) -> some View {
        HStack(spacing: 8) { Circle().fill(.white).frame(width: 8, height: 8); Text(text).monospacedDigit() }
            .font(.subheadline.weight(.bold)).padding(.horizontal, 12).padding(.vertical, 7)
            .background(.black.opacity(0.18), in: Capsule())
    }

    /// This week as seven flat tiles: each fills with that day's spending against a day's share.
    private var weekRow: some View {
        let (start, _) = weekBounds(today())
        let w = week, m = month
        let perDay = w.limit.map { Double($0) / 7 } ?? m.limit.map { Double($0) / 30 } ?? 0
        let todayISO = iso(today())
        let names = ["M", "T", "W", "T", "F", "S", "S"]
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("This week").foregroundStyle(.white.opacity(0.86))
                Spacer()
                Text(w.left.map { $0 < 0 ? "\(money(-$0)) over" : "\(money($0)) left" } ?? "\(money(w.spent)) spent").monospacedDigit()
                    .lineLimit(1).minimumScaleFactor(0.7)
            }
            .font(.subheadline.weight(.semibold))
            HStack(spacing: 6) {
                ForEach(0..<7, id: \.self) { i in
                    let d = iso(mondayCalendar.date(byAdding: .day, value: i, to: start)!)
                    let cents = expenses.filter { $0.date == d }.reduce(0) { $0 + $1.amountCents }
                    let future = d > todayISO
                    let frac = future || perDay <= 0 ? 0 : min(1, max(0, Double(cents) / perDay))
                    VStack(spacing: 6) {
                        ZStack(alignment: .bottom) {
                            RoundedRectangle(cornerRadius: 7, style: .continuous).fill(.white.opacity(future ? 0.08 : 0.17))
                            RoundedRectangle(cornerRadius: 7, style: .continuous).fill(.white).frame(height: 40 * frac)
                        }
                        .frame(height: 40)
                        .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
                        .overlay { if d == todayISO { RoundedRectangle(cornerRadius: 7, style: .continuous).stroke(.white, lineWidth: 2.5) } }
                        Text(names[i]).font(.caption2.weight(.semibold)).foregroundStyle(.white.opacity(0.8))
                    }
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("\(day(d).formatted(.dateTime.weekday(.wide).locale(Locale(identifier: "en_GB")))): \(future ? "still to come" : cents > 0 ? money(cents) : "nothing spent")")
                }
            }
        }
    }

    // MARK: The sheet

    private var whereItWent: some View {
        let (start, end) = monthBounds(today())
        let s = iso(start), e = iso(end)
        let inMonth = expenses.filter { $0.date >= s && $0.date <= e }
        var spent: [String?: Int] = [:]
        for x in inMonth { spent[x.categoryUid, default: 0] += x.amountCents }
        let rows: [(name: String, color: Color, cents: Int, limit: Int?)] = spent
            .map { uid, cents in
                let c = categories.first { $0.uid == uid }
                let lim = limits.first { $0.period == "month" && $0.categoryUid == uid && uid != nil }?.limitCents
                return (c?.name ?? "Uncategorized", c.map { Color(hex: $0.color) } ?? theme.faint, cents, lim)
            }
            .filter { $0.cents > 0 }
            .sorted { $0.cents > $1.cents }
        let total = max(1, rows.reduce(0) { $0 + $1.cents })
        return Group {
            if !rows.isEmpty {
                Card {
                    Text("Where it went").font(.title3.weight(.bold)).foregroundStyle(theme.text).padding(.bottom, 12)
                    // One flat band: a stripe per category, sized by its share.
                    GeometryReader { g in
                        HStack(spacing: 3) {
                            ForEach(rows, id: \.name) { r in
                                r.color.frame(width: max(3, (g.size.width - CGFloat(rows.count - 1) * 3) * CGFloat(r.cents) / CGFloat(total)))
                            }
                        }
                    }
                    .frame(height: 22).clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(rows.map { "\($0.name) \(Int((Double($0.cents) * 100 / Double(total)).rounded()))%" }.joined(separator: ", "))
                    .padding(.bottom, 8)
                    ForEach(rows.prefix(6), id: \.name) { r in
                        HStack(spacing: 10) {
                            RoundedRectangle(cornerRadius: 3).fill(r.color).frame(width: 12, height: 12)
                            Text(r.name).foregroundStyle(theme.text).lineLimit(1)
                            Spacer()
                            Text(money(r.cents)).fontWeight(.semibold).foregroundStyle(theme.text).monospacedDigit()
                            if let lim = r.limit {
                                let over = r.cents > lim
                                Text(over ? "over \(money(lim, whole: true))" : "of \(money(lim, whole: true))")
                                    .font(.caption.weight(over ? .semibold : .regular)).monospacedDigit()
                                    .foregroundStyle(over ? theme.levelColor(.red) : level(spent: r.cents, limit: lim) == .amber ? theme.levelColor(.amber) : theme.faint)
                                    .frame(minWidth: 64, alignment: .trailing)
                            }
                        }
                        .font(.subheadline).padding(.vertical, 6)
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
                        Text("Recent").font(.title3.weight(.bold)).foregroundStyle(theme.text)
                        Spacer()
                        Button("See all") { tab = 1 }.font(.subheadline.weight(.semibold))
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

/// The ring: white fills it as you spend; the dark notch is where the plan says you'd be by today.
struct Ring: View {
    let spent: Double
    let plan: Double?
    let daysLeft: Int
    let deep: Color
    @State private var shown: Double = 0

    var body: some View {
        ZStack {
            Circle().stroke(.white.opacity(0.22), lineWidth: 18)
            Circle().trim(from: 0, to: shown).stroke(.white, style: StrokeStyle(lineWidth: 18)).rotationEffect(.degrees(-90))
            if let plan {
                Capsule().fill(deep).frame(width: 5, height: 22)
                    .offset(y: -57).rotationEffect(.degrees(plan * 360))
            }
            VStack(spacing: 2) {
                Text("\(daysLeft)").font(.system(size: 34, weight: .black)).monospacedDigit()
                Text(daysLeft == 1 ? "day to go" : "days to go").font(.caption2.weight(.semibold)).opacity(0.86)
            }
        }
        .frame(width: 132, height: 132)
        .dynamicTypeSize(...DynamicTypeSize.xLarge)      // the ring is a fixed size: its label stays inside it
        .onAppear { withAnimation(.smooth(duration: 0.7)) { shown = min(1, max(0, spent)) } }
        .onChange(of: spent) { _, v in withAnimation(.smooth(duration: 0.7)) { shown = min(1, max(0, v)) } }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Spent \(Int((spent * 100).rounded()))% of the budget\(plan.map { "; the plan for today is \(Int(($0 * 100).rounded()))%" } ?? ""). \(daysLeft) \(daysLeft == 1 ? "day" : "days") to go.")
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
