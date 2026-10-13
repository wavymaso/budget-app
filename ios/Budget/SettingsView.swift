import SwiftUI
import SwiftData

struct SettingsView: View {
    @Environment(\.modelContext) private var ctx
    @Environment(\.theme) private var theme
    @EnvironmentObject private var sync: SyncEngine
    @Query private var settings: [AppSetting]
    @Query(sort: \Category.sortOrder) private var categories: [Category]
    @Query(sort: \Bill.nextDate) private var bills: [Bill]
    @Query private var limits: [BudgetLimit]
    @Query private var months: [SavingsMonth]
    @Query private var moves: [SavingsMove]

    private var store: Store { Store(ctx: ctx, sync: sync) }

    var body: some View {
        NavigationStack {
            Form {
                MacSection()
                GmailSection()
                Section("Look") {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: 4), spacing: 10) {
                        ForEach(["auto"] + Theme.all.map(\.id), id: \.self) { id in themeSwatch(id) }
                    }.padding(.vertical, 6)
                }
                Section("Budgets") {
                    NavigationLink("Spending limits") { LimitsView() }
                    if let m = limits.first(where: { $0.categoryUid == nil && $0.period == "month" }) {
                        LabeledContent("Each month", value: money(m.limitCents))
                    }
                    if let w = limits.first(where: { $0.categoryUid == nil && $0.period == "week" }) {
                        LabeledContent("Each week", value: money(w.limitCents))
                    }
                }
                Section {
                    ForEach(bills) { b in
                        LabeledContent {
                            Text(money(b.amountCents)).monospacedDigit()
                        } label: {
                            Text(b.merchant)
                            Text("Day \(b.day) · next \(relativeDay(b.nextDate))").font(.caption).foregroundStyle(theme.secondary)
                        }
                        .swipeActions { Button("Stop", role: .destructive) { store.delete(b) } }
                    }
                    if bills.isEmpty { Text("Turn on “Repeat every month” when adding an expense.").font(.footnote).foregroundStyle(theme.secondary) }
                } header: { Text("Monthly bills") }
                Section("Categories") {
                    ForEach(categories) { c in
                        HStack { Circle().fill(Color(hex: c.color)).frame(width: 10, height: 10); Text(c.name) }
                    }
                    NavigationLink("Add a category") { NewCategoryView() }
                }
                if !months.isEmpty || !moves.isEmpty {
                    Section("Savings") {
                        LabeledContent("Saved so far", value: money(months.reduce(0) { $0 + $1.savedCents } + moves.reduce(0) { $0 + $1.amountCents }))
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(theme.background.ignoresSafeArea())
            .navigationTitle("Settings")
        }
    }

    private func themeSwatch(_ id: String) -> some View {
        let t = Theme.named(id, systemDark: false)
        let on = themeID(settings) == id
        return Button { store.setTheme(id) } label: {
            VStack(spacing: 6) {
                ZStack {
                    RoundedRectangle(cornerRadius: 10).fill(id == "auto"
                        ? AnyShapeStyle(LinearGradient(colors: [Theme.all[0].background, Theme.all[1].background], startPoint: .leading, endPoint: .trailing))
                        : AnyShapeStyle(t.background))
                    Circle().fill(id == "auto" ? Theme.all[1].accent : t.accent).frame(width: 14, height: 14)
                }
                .frame(height: 44)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(on ? theme.accent : theme.line, lineWidth: on ? 2 : 1))
                Text(id == "auto" ? "Auto" : t.label).font(.caption2).foregroundStyle(on ? theme.text : theme.secondary)
            }
        }.buttonStyle(.plain)
    }
}

/// Connecting to the Mac (once), and how syncing is going.
struct MacSection: View {
    @EnvironmentObject private var sync: SyncEngine
    @Environment(\.theme) private var theme
    @State private var address = ""
    @State private var password = ""
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        Section {
            if sync.isConnected && sync.state != .signedOut {
                LabeledContent("Mac", value: URL(string: sync.serverURL)?.host() ?? sync.serverURL)
                SyncBadge()
                Button { Task { await sync.sync() } } label: { Label("Sync now", systemImage: "arrow.triangle.2.circlepath") }
                    .disabled(sync.state == .syncing)
                Button("Disconnect", role: .destructive) { sync.signOut() }
            } else {
                TextField("Mac address (https://….ts.net)", text: $address)
                    .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                SecureField("Phone password", text: $password)
                if let error { Text(error).font(.footnote).foregroundStyle(theme.levelColor(.red)) }
                Button {
                    busy = true; error = nil
                    Task {
                        do { try await sync.signIn(address: address, password: password); password = "" }
                        catch { self.error = (error as? SyncError)?.text ?? error.localizedDescription }
                        busy = false
                    }
                } label: { if busy { ProgressView() } else { Text("Connect") } }
                .disabled(address.isEmpty || password.isEmpty || busy)
            }
        } header: {
            Text("Your Mac")
        } footer: {
            Text(sync.isConnected
                 ? "Everything is on this phone, so Budget works anywhere. Changes go both ways whenever the Mac can be reached (Tailscale on, Budget open)."
                 : "On the Mac: Budget → Settings → Use on your phone shows the address and the password.")
        }
        .onAppear { if address.isEmpty { address = sync.serverURL } }
    }
}

/// Reading the Apple Pay emails on this phone too, so it doesn't need the Mac.
struct GmailSection: View {
    @EnvironmentObject private var gmail: GmailEngine
    @Environment(\.theme) private var theme
    @State private var address = ""
    @State private var password = ""
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        Section {
            if gmail.isOn {
                LabeledContent("Gmail", value: gmail.address)
                Text(status).font(.footnote).foregroundStyle(statusIsError ? theme.levelColor(.red) : theme.secondary)
                Button { Task { await gmail.check(force: true) } } label: { Label("Check now", systemImage: "envelope.arrow.triangle.branch") }
                    .disabled(gmail.state == .checking)
                Button("Stop checking on this phone", role: .destructive) { gmail.turnOff() }
            } else {
                TextField("Gmail address", text: $address)
                    .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.emailAddress)
                SecureField("App password (16 letters)", text: $password)
                if let error { Text(error).font(.footnote).foregroundStyle(theme.levelColor(.red)) }
                Button {
                    busy = true; error = nil
                    Task {
                        do { try await gmail.turnOn(address: address, password: password); password = "" }
                        catch { self.error = (error as? GmailError)?.text ?? "Couldn't reach Gmail. Check that the phone is online." }
                        busy = false
                    }
                } label: { if busy { ProgressView() } else { Text("Check Gmail on this phone") } }
                .disabled(address.isEmpty || password.isEmpty || busy)
            }
        } header: {
            Text("Apple Pay emails")
        } footer: {
            Text(gmail.isOn
                 ? "New payments are added when you open Budget, and now and then in the background. The Mac does the same; each payment is only added once."
                 : "The same Gmail app password the Mac uses. Only emails from now on are read here; older ones come from the Mac.")
        }
        .onAppear { if address.isEmpty { address = gmail.address } }
    }

    private var statusIsError: Bool { if case .failed = gmail.state { return true } else { return false } }

    private var status: String {
        switch gmail.state {
        case .checking: return "Checking…"
        case .failed(let m): return m
        case .idle:
            guard let t = gmail.lastCheck else { return "Not checked yet" }
            let when = t.formatted(date: Calendar.current.isDateInToday(t) ? .omitted : .abbreviated, time: .shortened)
            return "Checked \(when)" + (gmail.lastAdded > 0 ? " · \(gmail.lastAdded) added" : "")
        }
    }
}

struct LimitsView: View {
    @Environment(\.modelContext) private var ctx
    @EnvironmentObject private var sync: SyncEngine
    @Environment(\.theme) private var theme
    @Query(sort: \Category.sortOrder) private var categories: [Category]
    @Query private var limits: [BudgetLimit]

    var body: some View {
        Form {
            Section {
                row("Each month", nil, "month")
                row("Each week", nil, "week")
            } header: { Text("Overall") } footer: { Text("Weeks run Monday to Sunday. Leave empty for no limit.") }
            Section("Per category, each month") {
                ForEach(categories) { c in row(c.name, c.uid, "month") }
            }
        }
        .scrollContentBackground(.hidden)
        .background(theme.background.ignoresSafeArea())
        .navigationTitle("Spending limits")
    }

    private func row(_ label: String, _ uid: String?, _ period: String) -> some View {
        LimitField(label: label, current: limits.first { $0.categoryUid == uid && $0.period == period }?.limitCents) { cents in
            Store(ctx: ctx, sync: sync).setLimit(categoryUid: uid, period: period, cents: cents)
        }
    }
}

private struct LimitField: View {
    let label: String
    let current: Int?
    let save: (Int?) -> Void
    @State private var text = ""
    @FocusState private var focused: Bool

    var body: some View {
        LabeledContent(label) {
            TextField("No limit", text: $text).keyboardType(.decimalPad).multilineTextAlignment(.trailing).focused($focused)
                .onSubmit(commit)
                .onChange(of: focused) { _, f in if !f { commit() } }
        }
        .onAppear { text = current.map { String(format: "%.0f", Double($0) / 100) } ?? "" }
    }

    private func commit() {
        let cents = text.trimmingCharacters(in: .whitespaces).isEmpty ? nil : parseAmount(text)
        if cents != current { save(cents) }
    }
}

struct NewCategoryView: View {
    @Environment(\.modelContext) private var ctx
    @EnvironmentObject private var sync: SyncEngine
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var color = "#2a78d6"
    private let colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

    var body: some View {
        Form {
            TextField("Name, e.g. Gym", text: $name)
            HStack {
                ForEach(colors, id: \.self) { c in
                    Circle().fill(Color(hex: c)).frame(width: 28, height: 28)
                        .overlay(Circle().stroke(.primary, lineWidth: c == color ? 2 : 0))
                        .onTapGesture { color = c }
                }
            }
            Button("Add") {
                Store(ctx: ctx, sync: sync).addCategory(name: name.trimmingCharacters(in: .whitespaces), color: color)
                dismiss()
            }.disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .navigationTitle("New category")
    }
}
