import SwiftUI
import SwiftData

/// Add tab: the expense form, ready to type.
struct AddView: View {
    @Binding var tab: Int
    @Environment(\.theme) private var theme
    @State private var savedMessage: String?

    var body: some View {
        NavigationStack {
            ExpenseForm(expense: nil) { message in
                savedMessage = message
                Task { try? await Task.sleep(nanoseconds: 2_200_000_000); savedMessage = nil }
            }
            .navigationTitle("Add expense")
            .overlay(alignment: .bottom) {
                if let savedMessage {
                    Text(savedMessage).font(.subheadline.weight(.medium)).foregroundStyle(theme.onAccent)
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        .background(theme.accent, in: Capsule()).padding(.bottom, 12)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .animation(.snappy, value: savedMessage)
        }
    }
}

/// Edit an expense (from Home or Transactions).
struct ExpenseSheet: View {
    let expense: Expense
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ExpenseForm(expense: expense) { _ in dismiss() }
                .navigationTitle("Edit expense")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
    }
}

struct ExpenseForm: View {
    let expense: Expense?
    var onSaved: (String) -> Void

    @Environment(\.modelContext) private var ctx
    @Environment(\.theme) private var theme
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var sync: SyncEngine
    @Query(sort: \Category.sortOrder) private var categories: [Category]
    @Query private var rules: [MerchantRule]
    @Query private var keywords: [KeywordRule]
    @Query(sort: \Expense.date, order: .reverse) private var all: [Expense]

    @State private var amount = ""
    @State private var merchant = ""
    @State private var categoryUid: String?
    @State private var categorySource = "none"
    @State private var userPicked = false
    @State private var date = today()
    @State private var note = ""
    @State private var refund = false
    @State private var repeatMonthly = false
    @State private var showAllCategories = false
    @State private var error: String?
    @FocusState private var focus: Field?
    enum Field { case amount, merchant, note }

    private var store: Store { Store(ctx: ctx, sync: sync) }

    var body: some View {
        Form {
            Section {
                HStack {
                    TextField("0,00", text: $amount).font(theme.display(40)).keyboardType(.decimalPad).focused($focus, equals: .amount)
                    Text("€").font(theme.display(28)).foregroundStyle(theme.faint)
                }
                TextField("Where? e.g. Mercadona", text: $merchant)
                    .focused($focus, equals: .merchant).submitLabel(.done)
                    .onChange(of: merchant) { _, m in suggest(m) }
                if focus == .merchant, !merchantMatches.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack { ForEach(merchantMatches, id: \.self) { m in chip(m, on: false) { merchant = m; focus = nil } } }
                    }
                }
            }
            Section("Category") {
                FlowChips(items: visibleCategories, selected: categoryUid, suggested: !userPicked && categoryUid != nil) { uid in
                    userPicked = true
                    categoryUid = categoryUid == uid ? nil : uid
                    categorySource = categoryUid == nil ? "none" : "manual"
                }
                if categories.count > 6 {
                    Button(showAllCategories ? "Fewer" : "\(categories.count - 6) more…") { showAllCategories.toggle() }.font(.subheadline)
                }
            }
            Section("When") {
                HStack {
                    DatePicker("Date", selection: $date, in: ...Date().addingTimeInterval(86400 * 365), displayedComponents: .date)
                        .labelsHidden().environment(\.locale, Locale(identifier: "en_GB"))
                    Spacer()
                    chip("Today", on: date == today()) { date = today() }
                    chip("Yesterday", on: date == mondayCalendar.date(byAdding: .day, value: -1, to: today())) {
                        date = mondayCalendar.date(byAdding: .day, value: -1, to: today())!
                    }
                }
            }
            Section {
                DisclosureGroup("More options") {
                    TextField("Note", text: $note, axis: .vertical).focused($focus, equals: .note)
                    Toggle("It's a refund (money back)", isOn: $refund)
                    if expense == nil { Toggle("Repeat every month", isOn: $repeatMonthly) }
                }
            }
            if let error { Section { Text(error).foregroundStyle(theme.levelColor(.red)) } }
            Section {
                Button(action: save) {
                    Text(expense == nil ? "Add expense" : "Save").font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent)
                .listRowInsets(EdgeInsets()).listRowBackground(Color.clear)
                if let expense {
                    Button("Delete", role: .destructive) { store.delete(expense); onSaved("Deleted") }
                        .frame(maxWidth: .infinity)
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(theme.background.ignoresSafeArea())
        .onAppear(perform: load)
        .toolbar { ToolbarItemGroup(placement: .keyboard) { Spacer(); Button("Done") { focus = nil } } }
    }

    // MARK: helpers

    private var visibleCategories: [Category] {
        // The ones you use most first, like on the Mac.
        var uses: [String: Int] = [:]
        for e in all.prefix(400) { if let u = e.categoryUid { uses[u, default: 0] += 1 } }
        let sorted = categories.sorted { (uses[$0.uid] ?? 0, -$0.sortOrder) > (uses[$1.uid] ?? 0, -$1.sortOrder) }
        var shown = showAllCategories ? sorted : Array(sorted.prefix(6))
        if let sel = categoryUid, !shown.contains(where: { $0.uid == sel }), let c = categories.first(where: { $0.uid == sel }) { shown.append(c) }
        return shown
    }

    private var merchantMatches: [String] {
        let q = merchant.lowercased()
        guard q.count >= 1 else { return [] }
        var seen = Set<String>(), out: [String] = []
        for e in all where e.merchant.lowercased().hasPrefix(q) && e.merchant.lowercased() != q {
            if seen.insert(e.merchant.lowercased()).inserted { out.append(e.merchant) }
            if out.count == 4 { break }
        }
        return out
    }

    private func suggest(_ m: String) {
        guard !userPicked else { return }
        let s = suggestCategory(m, rules: rules, keywords: keywords)
        categoryUid = s.categoryUid
        categorySource = s.source
    }

    private func chip(_ label: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label).font(.subheadline).padding(.horizontal, 12).padding(.vertical, 6)
                .background(on ? theme.accent : theme.surface, in: Capsule())
                .foregroundStyle(on ? theme.onAccent : theme.text)
                .overlay(Capsule().stroke(theme.line, lineWidth: on ? 0 : 1))
        }.buttonStyle(.plain)
    }

    private func load() {
        guard let e = expense else { focus = .amount; return }
        amount = String(format: "%.2f", Double(abs(e.amountCents)) / 100).replacingOccurrences(of: ".", with: ",")
        merchant = e.merchant; categoryUid = e.categoryUid; categorySource = e.categorySource; userPicked = true
        date = day(e.date); note = e.note ?? ""; refund = e.amountCents < 0
    }

    private func save() {
        guard let cents = parseAmount(amount) else { error = "Enter an amount, like 12,50."; focus = .amount; return }
        let m = merchant.trimmingCharacters(in: .whitespaces)
        guard !m.isEmpty else { error = "Enter where you spent it."; focus = .merchant; return }
        error = nil
        let signed = refund ? -cents : cents
        let n = note.trimmingCharacters(in: .whitespaces).isEmpty ? nil : note
        if let e = expense {
            store.update(e, amountCents: signed, merchant: m, date: iso(date), note: n, categoryUid: categoryUid, categorySource: categorySource)
            onSaved("Saved")
        } else {
            store.addExpense(amountCents: signed, merchant: m, date: iso(date), note: n, categoryUid: categoryUid,
                             categorySource: categorySource, repeatMonthly: repeatMonthly)
            onSaved("Added \(money(cents)) · \(m)")
            amount = ""; merchant = ""; categoryUid = nil; categorySource = "none"; userPicked = false
            note = ""; refund = false; repeatMonthly = false; date = today(); focus = .amount
        }
    }
}

/// Category chips that wrap onto new lines.
struct FlowChips: View {
    let items: [Category]
    let selected: String?
    let suggested: Bool
    let pick: (String) -> Void
    @Environment(\.theme) private var theme

    var body: some View {
        FlowLayout(spacing: 8) {
            ForEach(items) { c in
                let on = c.uid == selected
                Button { pick(c.uid) } label: {
                    HStack(spacing: 6) {
                        Circle().fill(Color(hex: c.color)).frame(width: 8, height: 8)
                        Text(c.name)
                        if on && suggested { Text("suggested").font(.caption2).foregroundStyle(theme.onAccent.opacity(0.7)) }
                    }
                    .font(.subheadline).padding(.horizontal, 12).padding(.vertical, 7)
                    .background(on ? theme.accent : theme.surface, in: Capsule())
                    .foregroundStyle(on ? theme.onAccent : theme.text)
                    .overlay(Capsule().stroke(theme.line, lineWidth: on ? 0 : 1))
                }.buttonStyle(.plain)
            }
        }.padding(.vertical, 4)
    }
}

struct FlowLayout: Layout {
    var spacing: CGFloat = 8
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 320
        var x: CGFloat = 0, y: CGFloat = 0, row: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x + size.width > width, x > 0 { x = 0; y += row + spacing; row = 0 }
            x += size.width + spacing; row = max(row, size.height)
        }
        return CGSize(width: width, height: y + row)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, row: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX, x > bounds.minX { x = bounds.minX; y += row + spacing; row = 0 }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing; row = max(row, size.height)
        }
    }
}

/// Every expense, newest first, grouped by day. Search, tap to edit, swipe to delete.
struct TransactionsView: View {
    @Environment(\.modelContext) private var ctx
    @Environment(\.theme) private var theme
    @EnvironmentObject private var sync: SyncEngine
    @Query(sort: \Expense.date, order: .reverse) private var expenses: [Expense]
    @Query(sort: \Category.sortOrder) private var categories: [Category]
    @State private var search = ""
    @State private var editing: Expense?

    var body: some View {
        NavigationStack {
            List {
                ForEach(days, id: \.0) { dayIso, items in
                    Section {
                        ForEach(items) { e in
                            Button { editing = e } label: { ExpenseRow(expense: e, categories: categories) }
                                .buttonStyle(.plain)
                                .swipeActions { Button("Delete", role: .destructive) { Store(ctx: ctx, sync: sync).delete(e) } }
                        }
                    } header: {
                        HStack {
                            Text(relativeDay(dayIso))
                            Spacer()
                            Text(money(items.reduce(0) { $0 + $1.amountCents })).monospacedDigit()
                        }
                    }
                    .listRowBackground(theme.surface)
                }
                if days.isEmpty {
                    Text(search.isEmpty ? "No expenses yet." : "Nothing matches “\(search)”.").foregroundStyle(theme.secondary)
                        .listRowBackground(Color.clear)
                }
            }
            .scrollContentBackground(.hidden)
            .background(theme.background.ignoresSafeArea())
            .navigationTitle("Transactions")
            .searchable(text: $search, prompt: "Search")
            .refreshable { await sync.sync() }
            .sheet(item: $editing) { e in ExpenseSheet(expense: e) }
        }
    }

    private var days: [(String, [Expense])] {
        let q = search.lowercased()
        let names = Dictionary(uniqueKeysWithValues: categories.map { ($0.uid, $0.name.lowercased()) })
        let shown = q.isEmpty ? expenses : expenses.filter {
            $0.merchant.lowercased().contains(q) || ($0.note ?? "").lowercased().contains(q) ||
            (names[$0.categoryUid ?? ""] ?? "").contains(q)
        }
        let grouped = Dictionary(grouping: shown.prefix(1500), by: \.date)
        return grouped.keys.sorted(by: >).map { k in (k, grouped[k]!.sorted { $0.createdAt > $1.createdAt }) }
    }
}
