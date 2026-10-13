import SwiftUI
import SwiftData

@main
struct BudgetApp: App {
    let container: ModelContainer = {
        let schema = Schema(allModels)
        return try! ModelContainer(for: schema, configurations: ModelConfiguration(schema: schema))
    }()

    var body: some Scene {
        WindowGroup {
            Root(sync: SyncEngine(context: container.mainContext))
        }
        .modelContainer(container)
    }
}

struct Root: View {
    @StateObject var sync: SyncEngine
    @Environment(\.colorScheme) private var scheme
    @Environment(\.scenePhase) private var phase
    @Environment(\.modelContext) private var ctx
    @Query private var settings: [AppSetting]
    @State private var tab = 0

    var theme: Theme { Theme.named(themeID(settings), systemDark: scheme == .dark) }

    var body: some View {
        TabView(selection: $tab) {
            HomeView(tab: $tab).tabItem { Label("Home", systemImage: "house") }.tag(0)
            TransactionsView().tabItem { Label("Transactions", systemImage: "list.bullet") }.tag(1)
            AddView(tab: $tab).tabItem { Label("Add", systemImage: "plus.circle.fill") }.tag(2)
            SettingsView().tabItem { Label("Settings", systemImage: "gearshape") }.tag(3)
        }
        .environment(\.theme, theme)
        .environmentObject(sync)
        .tint(theme.accent)
        .preferredColorScheme(themeID(settings) == "auto" ? nil : (theme.dark ? .dark : .light))
        .task {
            addDueBills(ctx)
            #if DEBUG
            // Testing only: connect to a test Mac without typing (-connect <address> -password <pw>).
            let args = UserDefaults.standard
            if let address = args.string(forKey: "connect"), let pw = args.string(forKey: "password") {
                try? await sync.signIn(address: address, password: pw)
            }
            if let add = args.string(forKey: "addExpense") {
                let parts = add.split(separator: ":").map(String.init)
                let s = suggestCategory(parts[0], rules: (try? ctx.fetch(FetchDescriptor<MerchantRule>())) ?? [],
                                        keywords: (try? ctx.fetch(FetchDescriptor<KeywordRule>())) ?? [])
                Store(ctx: ctx, sync: sync).addExpense(amountCents: parseAmount(parts[1]) ?? 100, merchant: parts[0], date: iso(today()),
                                                       note: nil, categoryUid: s.categoryUid, categorySource: s.source, repeatMonthly: false)
            }
            if let t = args.string(forKey: "tab"), let n = Int(t) { tab = n }
            #endif
            await sync.sync()
        }
        .onChange(of: phase) { _, now in
            if now == .active { Task { await sync.sync() } }
        }
        .task {
            // While open, check the Mac every minute.
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 60_000_000_000)
                if phase == .active { await sync.sync() }
            }
        }
    }
}

/// "Synced 14:32", "Mac not reachable", ... shown at the top of Home.
struct SyncBadge: View {
    @EnvironmentObject var sync: SyncEngine
    @Environment(\.theme) private var theme
    @Query(filter: #Predicate<Expense> { $0.dirty }) private var unsent: [Expense]

    var body: some View {
        if sync.isConnected {
            HStack(spacing: 6) {
                Circle().fill(color).frame(width: 7, height: 7)
                Text(text).font(.footnote).foregroundStyle(theme.secondary)
            }
        }
    }

    private var color: Color {
        switch sync.state {
        case .idle: return unsent.isEmpty ? theme.levelColor(.green) : theme.levelColor(.amber)
        case .syncing: return theme.accent
        case .offline: return theme.levelColor(.amber)
        case .signedOut, .failed: return theme.levelColor(.red)
        }
    }

    private var text: String {
        let waiting = unsent.isEmpty ? "" : " · \(unsent.count) to send"
        switch sync.state {
        case .syncing: return "Syncing…"
        case .offline: return "Mac not reachable\(waiting)"
        case .signedOut: return "Sign in again in Settings"
        case .failed(let m): return m
        case .idle:
            guard let t = sync.lastSync else { return "Not synced yet\(waiting)" }
            return "Synced \(t.formatted(date: Calendar.current.isDateInToday(t) ? .omitted : .abbreviated, time: .shortened))\(waiting)"
        }
    }
}
